"""
Tests für den Shutdown-Pfad des Docker-Executors.

Zwei Verhaltensweisen, die vorher fehlten:

1. ``graceful_shutdown`` stoppte Container nacheinander. Ein einzelner
   ``container.stop(timeout=30)`` blockiert bis zu 30 s plus dem Client-Timeout
   von docker-py (60 s) – bei Dockers Standard-Grace-Period von 10 s war der
   Prozess längst per SIGKILL weg, und alle übrigen Runs blieben unbearbeitet.
2. ``_re_attach_container`` brach seine Stream-Tasks mit ``cancel()`` ohne
   ``await`` ab. Das Entfernen des Containers rannte damit gegen das Aufräumen
   der Streams, und die letzten Logzeilen fehlten – ausgerechnet nach einer
   Crash-Recovery.
"""

import asyncio
import threading
import time
from uuid import uuid4

import pytest

from app.core.config import config
from app.executor import core as executor_core
from app.models import PipelineRun, RunStatus


@pytest.fixture
def shutdown_budget():
    """Setzt GRACEFUL_SHUTDOWN_TIMEOUT temporär."""
    original = config.GRACEFUL_SHUTDOWN_TIMEOUT

    def _set(value):
        config.GRACEFUL_SHUTDOWN_TIMEOUT = value

    yield _set
    config.GRACEFUL_SHUTDOWN_TIMEOUT = original


@pytest.fixture
def tracked_containers(monkeypatch):
    """Isoliert das Container-Tracking und das zugehörige Lock vom Rest."""
    monkeypatch.setattr(executor_core, "_running_containers", {})
    # asyncio.Lock bindet sich an den Event-Loop des ersten Await.
    monkeypatch.setattr(executor_core, "_concurrency_lock", asyncio.Lock())
    return executor_core._running_containers


class _SlowContainer:
    """Container, dessen stop() eine feste Zeit im Worker-Thread blockiert."""

    def __init__(self, seconds, container_id="0123456789ab"):
        self.id = container_id
        self._seconds = seconds
        self.stopped = threading.Event()

    def stop(self, timeout=None):
        time.sleep(self._seconds)
        self.stopped.set()


class _FailingContainer:
    id = "0123456789ab"

    def stop(self, timeout=None):
        raise RuntimeError("daemon weg")


def _running_run(session, name="demo"):
    run = PipelineRun(
        pipeline_name=name,
        status=RunStatus.RUNNING,
        log_file=f"/tmp/{uuid4()}.log",
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


# --- Graceful Shutdown -------------------------------------------------------

async def test_all_containers_are_stopped_within_the_budget(
    test_session, shutdown_budget, tracked_containers
):
    """
    Fünf Container à 0,4 s: parallel gut 0,4 s, nacheinander über 2 s. Das
    Budget liegt dazwischen – sequenziell würde der Test scheitern.
    """
    shutdown_budget(2)
    runs = [_running_run(test_session, f"p{i}") for i in range(5)]
    containers = [_SlowContainer(0.4) for _ in runs]
    for run, container in zip(runs, containers):
        tracked_containers[run.id] = container

    started = time.monotonic()
    await asyncio.wait_for(executor_core.graceful_shutdown(test_session), timeout=10)
    elapsed = time.monotonic() - started

    assert all(c.stopped.is_set() for c in containers), "nicht alle Container gestoppt"
    assert elapsed < 2, f"lief {elapsed:.2f}s – offenbar nacheinander"
    for run in runs:
        test_session.refresh(run)
        assert run.status == RunStatus.INTERRUPTED
        assert run.finished_at is not None


async def test_budget_is_honoured_and_unfinished_runs_stay_running(
    test_session, shutdown_budget, tracked_containers
):
    """
    Läuft ein Stop über das Budget, darf der Shutdown nicht mitwarten – und der
    Run muss auf RUNNING bleiben: nur so hängt sich die Zombie-Reconciliation
    beim nächsten Start wieder an den Container bzw. schreibt ihn fort.
    """
    shutdown_budget(1)
    quick_run = _running_run(test_session, "schnell")
    slow_run = _running_run(test_session, "langsam")
    quick = _SlowContainer(0.0)
    slow = _SlowContainer(30.0)
    tracked_containers[quick_run.id] = quick
    tracked_containers[slow_run.id] = slow

    started = time.monotonic()
    await asyncio.wait_for(executor_core.graceful_shutdown(test_session), timeout=10)
    elapsed = time.monotonic() - started

    assert elapsed < 5, f"Shutdown wartete {elapsed:.2f}s auf den hängenden Container"
    test_session.refresh(quick_run)
    test_session.refresh(slow_run)
    assert quick_run.status == RunStatus.INTERRUPTED
    assert slow_run.status == RunStatus.RUNNING, (
        "Ein anderer Status würde die Zombie-Reconciliation überspringen"
    )
    assert slow_run.finished_at is None


async def test_stop_timeout_stays_below_the_budget(
    test_session, shutdown_budget, tracked_containers
):
    """Dockers SIGKILL-Frist muss ins Budget passen, sonst kommt keine Antwort."""
    shutdown_budget(8)
    run = _running_run(test_session)
    seen = {}

    class _RecordingContainer:
        id = "0123456789ab"

        def stop(self, timeout=None):
            seen["timeout"] = timeout

    tracked_containers[run.id] = _RecordingContainer()
    await asyncio.wait_for(executor_core.graceful_shutdown(test_session), timeout=10)

    assert 0 < seen["timeout"] < config.GRACEFUL_SHUTDOWN_TIMEOUT


async def test_failed_and_untracked_containers_become_warning(
    test_session, shutdown_budget, tracked_containers
):
    """Fehlgeschlagener Stop und nicht mehr getrackter Container: WARNING."""
    shutdown_budget(2)
    failing_run = _running_run(test_session, "fehler")
    untracked_run = _running_run(test_session, "untracked")
    tracked_containers[failing_run.id] = _FailingContainer()

    await asyncio.wait_for(executor_core.graceful_shutdown(test_session), timeout=10)

    test_session.refresh(failing_run)
    test_session.refresh(untracked_run)
    assert failing_run.status == RunStatus.WARNING
    assert untracked_run.status == RunStatus.WARNING


async def test_shutdown_without_running_runs_is_a_noop(
    test_session, shutdown_budget, tracked_containers
):
    shutdown_budget(2)
    await asyncio.wait_for(executor_core.graceful_shutdown(test_session), timeout=5)


# --- Streams beenden (normaler Run und Re-Attach) ----------------------------

@pytest.fixture
def no_flush_grace(monkeypatch):
    """Kürzt die Wartezeit, mit der der Stream seine letzten Zeilen schreibt."""
    monkeypatch.setattr(executor_core, "STREAM_FLUSH_GRACE_SECONDS", 0.0)


async def test_finalize_waits_for_the_stream_cleanup(tmp_path, no_flush_grace):
    """
    Der finally-Block des Stream-Tasks schliesst den Docker-Stream. Läuft der
    Aufrufer weiter, ohne darauf zu warten, schneidet das Entfernen des
    Containers ab, was noch nicht geschrieben war.
    """
    cleaned_up = threading.Event()

    async def _streaming():
        try:
            await asyncio.sleep(30)
        finally:
            cleaned_up.set()

    log_task = asyncio.create_task(_streaming())
    metrics_task = asyncio.create_task(_streaming())

    await asyncio.wait_for(
        executor_core._finalize_run_streams(
            log_task, metrics_task, None, tmp_path / "run.log", uuid4()
        ),
        timeout=5,
    )

    assert cleaned_up.is_set()
    assert log_task.done() and metrics_task.done()


async def test_finalize_survives_a_hanging_stream_task(tmp_path, no_flush_grace):
    """Ein Task, der die Cancellation ignoriert, darf den Shutdown nicht halten."""
    monkeypatch_timeout = 0.2

    async def _stubborn():
        while True:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                pass  # ignoriert den Abbruch bewusst

    task = asyncio.create_task(_stubborn())
    try:
        started = time.monotonic()
        await asyncio.wait_for(
            executor_core._stop_stream_task(task, uuid4(), "Test", monkeypatch_timeout),
            timeout=5,
        )
        assert time.monotonic() - started < 2
    finally:
        task.cancel()


async def test_remaining_logs_are_appended_before_removal(tmp_path):
    """Die letzten Zeilen holt nur container.logs(tail=…) – vor dem remove()."""
    log_file = tmp_path / "run.log"
    log_file.write_text("[2026-01-01 00:00:00.000] erste Zeile\n", encoding="utf-8")

    class _ContainerWithTail:
        id = "0123456789ab"

        def logs(self, **kwargs):
            assert kwargs.get("tail") == 1000
            return b"erste Zeile\nletzte Zeile vor dem Ende\n"

    await asyncio.wait_for(
        executor_core._recover_remaining_logs(_ContainerWithTail(), log_file, uuid4()),
        timeout=5,
    )

    content = log_file.read_text(encoding="utf-8")
    assert "erste Zeile" in content
    assert "letzte Zeile vor dem Ende" in content


async def test_re_attach_finalizes_streams_before_removing_the_container(
    test_session, tracked_containers, no_flush_grace, monkeypatch
):
    """
    Der Kern des Befunds: Re-Attach brach seine Tasks mit cancel() ohne await ab
    und entfernte den Container, während die Streams noch aufräumten.
    """
    order = []

    run = _running_run(test_session, "reattach")
    run.metrics_file = str(uuid4())
    test_session.add(run)
    test_session.commit()

    class _FakePipeline:
        name = "reattach"
        metadata = type("Meta", (), {"cpu_soft_limit": None, "mem_soft_limit": None})()

    async def _never_ending(*args, **kwargs):
        await asyncio.sleep(30)

    async def _record_finalize(*args, **kwargs):
        order.append("finalize")

    async def _record_remove(*args, **kwargs):
        order.append("remove")

    async def _noop_stats(*args, **kwargs):
        return None

    class _ExitedContainer:
        id = "0123456789ab"

        def wait(self):
            return {"StatusCode": 0}

    monkeypatch.setattr(executor_core, "get_pipeline", lambda name: _FakePipeline())
    monkeypatch.setattr(executor_core, "_stream_logs", _never_ending)
    monkeypatch.setattr(executor_core, "_monitor_metrics", _never_ending)
    monkeypatch.setattr(executor_core, "_finalize_run_streams", _record_finalize)
    monkeypatch.setattr(executor_core, "_remove_container", _record_remove)
    monkeypatch.setattr(executor_core, "_update_pipeline_stats", _noop_stats)

    await asyncio.wait_for(
        executor_core._re_attach_container(run.id, _ExitedContainer(), test_session),
        timeout=10,
    )

    assert order == ["finalize", "remove"], (
        f"Streams müssen vor dem Entfernen abgeschlossen sein, war: {order}"
    )
    test_session.refresh(run)
    assert run.status == RunStatus.SUCCESS
