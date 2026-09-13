"""
Tests gegen die Erschöpfung des Executor-Thread-Pools.

Vorher lief alles über einen gemeinsamen ``ThreadPoolExecutor(max_workers=10)``.
Pro laufendem Run blockieren aber drei Calls dauerhaft — Log-Stream, Stats-Stream
und ``container.wait()`` — sodass ab dem vierten Run kein Worker mehr frei war:
``containers.run()`` startete stillschweigend nicht, und ``cancel_run()`` bzw. die
Zombie-Reconciliation hingen genau dann, wenn man sie braucht.

Geprüft werden die Eigenschaften, die das verhindern:
1. Der Stream-Pool fasst die drei Dauer-Calls aller MAX_CONCURRENT_RUNS Runs.
2. Der Control-Pool bleibt erreichbar, während der Stream-Pool voll ist.
3. Beide Pools wachsen mit, wenn MAX_CONCURRENT_RUNS zur Laufzeit steigt.
4. Ein abgebrochenes Await gibt den Worker nicht vorzeitig als frei aus.
"""

import asyncio
import threading
import time
from uuid import uuid4

import pytest

from app.core.config import config
from app.executor import core as executor_core
from app.executor import thread_pools as thread_pools_module
from app.executor.thread_pools import (
    BLOCKING_CALLS_PER_RUN,
    CONTROL_POOL_HEADROOM,
    CONTROL_POOL_MIN_WORKERS,
    DEFAULT_CONCURRENT_RUNS,
    MAX_POOL_WORKERS,
    STREAM_POOL_HEADROOM,
    BlockingCallPool,
    _control_pool_capacity,
    _stream_pool_capacity,
    control_pool,
    stream_pool,
)


@pytest.fixture
def max_concurrent_runs():
    """Setzt MAX_CONCURRENT_RUNS temporär (wie die Settings-UI zur Laufzeit)."""
    original = config.MAX_CONCURRENT_RUNS

    def _set(value):
        config.MAX_CONCURRENT_RUNS = value

    yield _set
    config.MAX_CONCURRENT_RUNS = original


class _Gate:
    """Blockiert Worker-Threads, bis der Test sie freigibt."""

    def __init__(self):
        self._released = threading.Event()
        self._entered = threading.Semaphore(0)

    def block(self):
        """Läuft im Worker-Thread: meldet den Eintritt, wartet auf Freigabe."""
        self._entered.release()
        assert self._released.wait(timeout=10), "Gate wurde nicht freigegeben"
        return "done"

    def wait_for_entries(self, count, timeout=5.0):
        """True, wenn ``count`` Aufrufe tatsächlich im Pool gestartet sind."""
        deadline = time.monotonic() + timeout
        for _ in range(count):
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self._entered.acquire(timeout=remaining):
                return False
        return True

    def release(self):
        self._released.set()


def _saturate(pool, gate):
    """Belegt jeden Worker des Pools; gibt die eingereichten Futures zurück."""
    calls = [pool.submit(gate.block)]  # erzwingt Anlegen/Wachsen des Pools
    calls += [pool.submit(gate.block) for _ in range(pool.stats()["max_workers"] - 1)]
    assert gate.wait_for_entries(len(calls)), "Pool wurde nicht vollständig belegt"
    return calls


def _drain(calls, gate, pool=None):
    gate.release()
    for call in calls:
        call.result(timeout=10)
    if pool is not None:
        pool.shutdown()


# --- Kapazitätsformeln -------------------------------------------------------

def test_stream_pool_holds_all_blocking_calls_of_all_runs(max_concurrent_runs):
    """Drei Dauer-Calls pro Run müssen gleichzeitig Platz haben, plus Reserve."""
    max_concurrent_runs(10)
    assert _stream_pool_capacity() == BLOCKING_CALLS_PER_RUN * 10 + STREAM_POOL_HEADROOM
    assert _stream_pool_capacity() > BLOCKING_CALLS_PER_RUN * 10


def test_control_pool_keeps_headroom_above_concurrent_runs(max_concurrent_runs):
    """
    Am Ende eines Runs fallen mehrere Control-Calls an (logs(tail), remove).
    Wäre der Pool genau MAX_CONCURRENT_RUNS gross, bliebe beim gleichzeitigen
    Aufräumen aller Runs nichts für Abbruch und Reconciliation übrig.
    """
    max_concurrent_runs(2)
    assert _control_pool_capacity() == CONTROL_POOL_MIN_WORKERS
    max_concurrent_runs(64)
    assert _control_pool_capacity() == 64 + CONTROL_POOL_HEADROOM
    assert _control_pool_capacity() > 64


@pytest.mark.parametrize("value", [0, None, -1, "kaputt"])
def test_capacity_falls_back_when_limit_is_unset(max_concurrent_runs, value):
    """0 heisst bei Kubernetes "unbegrenzt" – der Pool braucht trotzdem eine Grösse."""
    max_concurrent_runs(value)
    assert _stream_pool_capacity() == (
        BLOCKING_CALLS_PER_RUN * DEFAULT_CONCURRENT_RUNS + STREAM_POOL_HEADROOM
    )
    assert _control_pool_capacity() == max(
        CONTROL_POOL_MIN_WORKERS, DEFAULT_CONCURRENT_RUNS + CONTROL_POOL_HEADROOM
    )


def test_capacity_is_capped(max_concurrent_runs):
    """Eine absurd hohe Einstellung darf keine tausenden Threads erzeugen."""
    max_concurrent_runs(100_000)
    pool = BlockingCallPool("test-cap", _stream_pool_capacity)
    try:
        pool.submit(lambda: None).result(timeout=10)
        assert pool.stats()["max_workers"] == MAX_POOL_WORKERS
    finally:
        pool.shutdown()


# --- Laufzeitverhalten der Pools ---------------------------------------------

async def test_all_blocking_calls_of_all_runs_start_concurrently(max_concurrent_runs):
    """Kein Dauer-Call wartet in der Queue, solange MAX_CONCURRENT_RUNS gilt."""
    max_concurrent_runs(4)
    pool = BlockingCallPool("test-stream", _stream_pool_capacity)
    gate = _Gate()
    calls = []
    try:
        calls = [pool.submit(gate.block) for _ in range(BLOCKING_CALLS_PER_RUN * 4)]
        assert gate.wait_for_entries(len(calls)), "nicht alle Calls sind gestartet"
        assert pool.stats()["in_flight"] == len(calls)
    finally:
        _drain(calls, gate, pool)


async def test_pool_grows_when_demand_exceeds_configured_capacity(max_concurrent_runs):
    """
    Nicht jede Nachfrage lässt sich aus MAX_CONCURRENT_RUNS herleiten: Re-Attach
    nach Crash-Recovery läuft ohne Concurrency-Check, Streams eines beendeten
    Runs laufen nach, und bei Kubernetes heisst 0 "unbegrenzt". Der Pool muss
    dann mitwachsen statt still zu warten.
    """
    max_concurrent_runs(1)
    pool = BlockingCallPool("test-demand", _stream_pool_capacity)
    gate = _Gate()
    blocked = []
    try:
        blocked = _saturate(pool, gate)
        configured = pool.stats()["max_workers"]
        assert configured == _stream_pool_capacity()

        # Ein weiterer Call bei unveränderter Konfiguration: muss sofort laufen.
        extra = pool.submit(gate.block)
        blocked.append(extra)
        assert gate.wait_for_entries(1), "Call wartet in der Queue statt zu starten"
        assert pool.stats()["max_workers"] > configured
    finally:
        _drain(blocked, gate, pool)


async def test_pool_grows_when_limit_is_raised_at_runtime(max_concurrent_runs):
    """MAX_CONCURRENT_RUNS ist über die Settings-UI zur Laufzeit änderbar."""
    max_concurrent_runs(1)
    pool = BlockingCallPool("test-grow", _stream_pool_capacity)
    gate = _Gate()
    blocked = []
    try:
        blocked = _saturate(pool, gate)
        small = pool.stats()["max_workers"]

        max_concurrent_runs(8)
        assert await asyncio.wait_for(pool.run(lambda: "frei"), timeout=5) == "frei"
        assert pool.stats()["max_workers"] >= _stream_pool_capacity() > small
    finally:
        _drain(blocked, gate, pool)


async def test_pool_never_shrinks_below_running_calls(max_concurrent_runs):
    """Verkleinern würde laufende Streams abschneiden – die Grösse sinkt nie."""
    max_concurrent_runs(8)
    pool = BlockingCallPool("test-shrink", _stream_pool_capacity)
    try:
        await pool.run(lambda: None)
        large = pool.stats()["max_workers"]
        max_concurrent_runs(1)
        await pool.run(lambda: None)
        assert pool.stats()["max_workers"] == large
    finally:
        pool.shutdown()


async def test_cancelled_await_keeps_worker_counted_until_call_returns():
    """asyncio.wait_for bricht nur das Future ab – der Thread läuft weiter."""
    pool = BlockingCallPool("test-cancel", lambda: 1)
    gate = _Gate()
    try:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(pool.run(gate.block), timeout=0.5)

        # Der Worker ist weiterhin belegt, obwohl niemand mehr auf ihn wartet.
        assert pool.stats()["in_flight"] == 1

        gate.release()
        deadline = time.monotonic() + 5
        while pool.stats()["in_flight"] and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
        assert pool.stats()["in_flight"] == 0
    finally:
        gate.release()
        pool.shutdown()


async def test_exceptions_propagate_and_release_the_worker():
    pool = BlockingCallPool("test-error", lambda: 2)

    def _boom():
        raise ValueError("kaputt")

    try:
        with pytest.raises(ValueError, match="kaputt"):
            await pool.run(_boom)
        assert pool.stats()["in_flight"] == 0
    finally:
        pool.shutdown()


async def test_shutdown_does_not_wait_for_blocking_calls():
    """Ein hängender Stream-Read darf den App-Shutdown nicht aufhalten."""
    pool = BlockingCallPool("test-shutdown", lambda: 1)
    gate = _Gate()
    try:
        pool.submit(gate.block)
        assert gate.wait_for_entries(1)
        await asyncio.wait_for(asyncio.to_thread(pool.shutdown), timeout=5)
    finally:
        gate.release()


# --- Verdrahtung im Executor -------------------------------------------------

def test_executor_has_no_shared_pool_left():
    """Regression: ein gemeinsamer Pool bringt die Erschöpfung zurück."""
    assert not hasattr(executor_core, "_executor")
    assert executor_core.stream_pool is stream_pool
    assert executor_core.control_pool is control_pool


async def test_cancel_run_works_while_stream_pool_is_saturated(
    monkeypatch, max_concurrent_runs
):
    """Abbrechen muss gerade dann funktionieren, wenn alle Runs laufen."""
    max_concurrent_runs(2)
    stopped = threading.Event()
    gate = _Gate()
    blocked = []

    class _FakeContainer:
        def stop(self, timeout=None):
            stopped.set()

    class _FakeSession:
        def get(self, *args, **kwargs):
            return None

    run_id = uuid4()
    # Frisches Lock: asyncio.Lock bindet sich an den Event-Loop des ersten Await.
    monkeypatch.setattr(executor_core, "_concurrency_lock", asyncio.Lock())
    monkeypatch.setitem(executor_core._running_containers, run_id, _FakeContainer())
    try:
        blocked = _saturate(stream_pool, gate)
        assert await asyncio.wait_for(
            executor_core.cancel_run(run_id, _FakeSession()), timeout=5
        )
        assert stopped.is_set()
    finally:
        _drain(blocked, gate)


async def test_log_streaming_reads_via_stream_pool_and_sets_up_via_control_pool(tmp_path):
    """
    Hot-Path: der Dauer-Read ``next(stream)`` muss im Stream-Pool landen, das
    kurze Öffnen des Streams im Control-Pool. Vertauscht wäre der Bug zurück.
    """
    used = {"stream": 0, "control": 0}

    def _counting(pool, key):
        original = pool.run

        async def _run(fn, *args):
            used[key] += 1
            return await original(fn, *args)

        return _run

    class _FakeContainer:
        id = "0123456789ab"

        def logs(self, **kwargs):
            assert kwargs["stream"] and kwargs["follow"]
            return iter([b"erste Zeile\n", b"zweite ", b"Zeile\n"])

    log_file = tmp_path / "run.log"
    queue = asyncio.Queue()

    stream_pool.run = _counting(stream_pool, "stream")
    control_pool.run = _counting(control_pool, "control")
    try:
        await asyncio.wait_for(
            executor_core._stream_logs(_FakeContainer(), log_file, queue, uuid4()),
            timeout=10,
        )
    finally:
        del stream_pool.run
        del control_pool.run

    content = log_file.read_text(encoding="utf-8")
    assert "erste Zeile" in content
    assert "zweite Zeile" in content  # über zwei Chunks zusammengesetzt
    assert queue.qsize() == 2

    assert used["control"] == 1, "container.logs() gehört in den Control-Pool"
    # Ein next() je Chunk plus der abschliessende Read, der None liefert.
    assert used["stream"] == 4, "next(stream) gehört in den Stream-Pool"


# --- Freigabe der Stream-Worker ---------------------------------------------

class _FlakyContainer:
    """Container, dessen remove() erst nach `failures` Versuchen klappt."""

    id = "0123456789ab"

    def __init__(self, failures, error=None):
        self._remaining = failures
        self._error = error or RuntimeError("daemon busy")
        self.remove_calls = 0

    def remove(self, force=False):
        self.remove_calls += 1
        if self._remaining > 0:
            self._remaining -= 1
            raise self._error


async def test_container_removal_is_retried(monkeypatch):
    """
    Das Entfernen des Containers ist das einzige Mittel, den Stats-Stream zu
    beenden: er ist ein einfacher Generator, sein close() weckt den blockierten
    Worker nicht. Ein einzelner fehlgeschlagener Versuch würde den Worker
    dauerhaft kosten.
    """
    monkeypatch.setattr(executor_core, "CONTAINER_REMOVE_RETRY_DELAY_SECONDS", 0.01)
    container = _FlakyContainer(failures=2)
    await asyncio.wait_for(executor_core._remove_container(container, uuid4()), timeout=5)
    assert container.remove_calls == 3


async def test_container_removal_gives_up_loudly(monkeypatch):
    """Nach allen Versuchen muss der Fehler sichtbar werden, nicht verschluckt."""
    monkeypatch.setattr(executor_core, "CONTAINER_REMOVE_RETRY_DELAY_SECONDS", 0.01)
    container = _FlakyContainer(failures=99)
    with pytest.raises(RuntimeError, match="daemon busy"):
        await asyncio.wait_for(executor_core._remove_container(container, uuid4()), timeout=5)
    assert container.remove_calls == executor_core.CONTAINER_REMOVE_ATTEMPTS


async def test_already_removed_container_is_not_retried(monkeypatch):
    """404 heisst: Ziel erreicht – kein Grund für weitere Versuche."""
    from docker.errors import NotFound

    monkeypatch.setattr(executor_core, "CONTAINER_REMOVE_RETRY_DELAY_SECONDS", 0.01)
    container = _FlakyContainer(failures=99, error=NotFound("weg"))
    await asyncio.wait_for(executor_core._remove_container(container, uuid4()), timeout=5)
    assert container.remove_calls == 1


async def test_growth_stops_at_the_ceiling_without_creating_pools(monkeypatch):
    """
    Übersteigt die Nachfrage MAX_POOL_WORKERS, darf nicht pro Call ein neuer
    Pool entstehen – das wäre eine Thread-Explosion statt einer Obergrenze.
    """
    monkeypatch.setattr("app.executor.thread_pools.MAX_POOL_WORKERS", 4)
    created = []
    real_executor = thread_pools_module.ThreadPoolExecutor

    def _counting_executor(*args, **kwargs):
        created.append(kwargs.get("max_workers"))
        return real_executor(*args, **kwargs)

    monkeypatch.setattr("app.executor.thread_pools.ThreadPoolExecutor", _counting_executor)

    pool = BlockingCallPool("test-ceiling", lambda: 2)
    gate = _Gate()
    calls = []
    try:
        calls = [pool.submit(gate.block) for _ in range(12)]
        assert gate.wait_for_entries(4), "der Pool sollte bis zum Limit belegt sein"
        assert pool.stats()["max_workers"] == 4
        # 2 (konfiguriert) -> 4 (Limit); danach kein weiterer Pool mehr.
        assert created == [2, 4], f"unerwartete Pool-Erzeugungen: {created}"
    finally:
        _drain(calls, gate, pool)
