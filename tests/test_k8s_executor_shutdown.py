"""
Tests für den Shutdown- und Reconcile-Pfad des Kubernetes-Executors.

Analog zu ``test_executor_shutdown.py``, aber mit einem eigenen Problem:

1. ``graceful_shutdown`` arbeitete die Runs nacheinander ab, ohne Gesamtbudget.
   Pro Run sind zwei API-Calls fällig (``list_namespaced_job``,
   ``delete_namespaced_job``), und der K8s-Client hat kein Default-Timeout – ein
   nicht erreichbarer API-Server blockierte damit unbegrenzt. Bei mehreren Runs
   riss der Shutdown die ``terminationGracePeriodSeconds`` des Deployments (30)
   und wurde mitten drin per SIGKILL beendet.
2. Der Docker-Pfad darf nicht mehr geschaffte Runs auf RUNNING stehen lassen,
   weil die Zombie-Reconciliation sie beim nächsten Start einsammelt. Für
   Kubernetes galt das nicht: ``reconcile_zombie_jobs`` iterierte über
   vorhandene Jobs und sah einen Run, dessen Job weg war, nie wieder. Genau
   diese Kombination erzeugt der Shutdown aber selbst – er löscht den Job.
"""

import asyncio
import threading
import time
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from kubernetes.client.rest import ApiException

from app.core.config import config
from app.executor import kubernetes_backend as k8s
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
def shared_volume(tmp_path, monkeypatch):
    """Hält das Aufräumen des shared Volumes aus dem Repo heraus."""
    monkeypatch.setattr(
        config, "KUBERNETES_SHARED_CACHE_MOUNT_PATH", str(tmp_path / "shared")
    )
    return tmp_path / "shared"


@pytest.fixture
def batch_api(monkeypatch, shared_volume):
    """Registriert einen Fake-BatchV1Api als initialisiertes K8s-Backend."""
    api = _FakeBatchApi()
    monkeypatch.setattr(k8s, "_batch_api", api)
    monkeypatch.setattr(k8s, "_core_api", object())
    monkeypatch.setattr(k8s, "_initialized", True)
    return api


def _job(run_id, name=None, succeeded=0, failed=0):
    """Minimaler V1Job-Ersatz mit den Feldern, die der Code liest."""
    return SimpleNamespace(
        metadata=SimpleNamespace(
            name=name or f"fastflow-{run_id}",
            labels={k8s.JOB_LABEL_RUN_ID: str(run_id)},
        ),
        status=SimpleNamespace(succeeded=succeeded, failed=failed),
    )


class _FakeBatchApi:
    """
    Fake-K8s-API: blockiert pro Call eine einstellbare Zeit im Worker-Thread.

    ``block_seconds`` gilt für alle Calls, ``block_for`` überschreibt das für
    einzelne Runs – so lässt sich ein hängender API-Server neben antwortenden
    Runs simulieren.
    """

    def __init__(self, block_seconds=0.0):
        self.jobs = {}  # run_id -> list[job]
        self.block_seconds = block_seconds
        self.block_for = {}
        self.fail_list_for = set()
        self.fail_delete_for = set()
        self.deleted = []
        self.request_timeouts = []
        self.continue_token = None
        self.list_calls = 0

    def add_job(self, run_id, **kwargs):
        self.jobs.setdefault(run_id, []).append(_job(run_id, **kwargs))

    def _sleep_for(self, run_id):
        time.sleep(self.block_for.get(run_id, self.block_seconds))

    def list_namespaced_job(self, namespace=None, label_selector=None, _request_timeout=None):
        self.list_calls += 1
        self.request_timeouts.append(_request_timeout)
        run_id = _run_id_from_selector(label_selector)
        self._sleep_for(run_id)
        if run_id in self.fail_list_for:
            raise ApiException(status=500, reason="API-Server weg")
        if run_id is None:
            items = [job for jobs in self.jobs.values() for job in jobs]
        else:
            items = list(self.jobs.get(run_id, []))
        return SimpleNamespace(
            items=items,
            metadata=SimpleNamespace(_continue=self.continue_token),
        )

    def delete_namespaced_job(
        self, name=None, namespace=None, propagation_policy=None, _request_timeout=None
    ):
        self.request_timeouts.append(_request_timeout)
        run_id = next(
            (rid for rid, jobs in self.jobs.items() if any(j.metadata.name == name for j in jobs)),
            None,
        )
        self._sleep_for(run_id)
        if run_id in self.fail_delete_for:
            raise ApiException(status=500, reason="Löschen abgelehnt")
        self.deleted.append(name)
        self.jobs.pop(run_id, None)


def _run_id_from_selector(label_selector):
    if not label_selector or "=" not in label_selector:
        return None
    try:
        return UUID(label_selector.split("=", 1)[1])
    except ValueError:
        return None


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

async def test_all_jobs_are_deleted_within_the_budget(test_session, shutdown_budget, batch_api):
    """
    Fünf Runs à zwei Calls zu 0,3 s: parallel gut 0,6 s, nacheinander über 3 s.
    Das Budget liegt dazwischen – sequenziell würde der Test scheitern.
    """
    shutdown_budget(2)
    batch_api.block_seconds = 0.3
    runs = [_running_run(test_session, f"p{i}") for i in range(5)]
    for run in runs:
        batch_api.add_job(run.id)

    started = time.monotonic()
    await asyncio.wait_for(k8s.graceful_shutdown(test_session), timeout=30)
    elapsed = time.monotonic() - started

    assert len(batch_api.deleted) == 5, "nicht alle Jobs gelöscht"
    assert elapsed < 2, f"lief {elapsed:.2f}s – offenbar nacheinander"
    for run in runs:
        test_session.refresh(run)
        assert run.status == RunStatus.INTERRUPTED
        assert run.finished_at is not None


async def test_a_hanging_api_server_does_not_block_the_shutdown(
    test_session, shutdown_budget, batch_api
):
    """
    Der K8s-Client hat kein Default-Timeout. Hängt der API-Server für einen Run,
    darf der Shutdown weder auf ihn warten noch die übrigen Runs mitreissen.
    """
    shutdown_budget(1)
    quick_run = _running_run(test_session, "schnell")
    stuck_run = _running_run(test_session, "haengt")
    batch_api.add_job(quick_run.id)
    batch_api.add_job(stuck_run.id)
    batch_api.block_for[stuck_run.id] = 30.0

    started = time.monotonic()
    await asyncio.wait_for(k8s.graceful_shutdown(test_session), timeout=30)
    elapsed = time.monotonic() - started

    assert elapsed < 5, f"Shutdown wartete {elapsed:.2f}s auf den hängenden API-Call"
    test_session.refresh(quick_run)
    test_session.refresh(stuck_run)
    assert quick_run.status == RunStatus.INTERRUPTED
    assert stuck_run.status == RunStatus.RUNNING, (
        "Ein Endstatus würde den echten Ausgang eines noch laufenden Jobs verdecken"
    )
    assert stuck_run.finished_at is None


async def test_api_calls_carry_a_client_timeout(test_session, shutdown_budget, batch_api):
    """
    Ohne Client-Timeout läuft der Thread im Control-Pool weiter, auch wenn das
    Budget das Warten längst beendet hat – und hält den Prozess-Exit auf.
    Beide Calls eines Runs müssen zusammen ins Budget passen.
    """
    shutdown_budget(8)
    run = _running_run(test_session)
    batch_api.add_job(run.id)

    await asyncio.wait_for(k8s.graceful_shutdown(test_session), timeout=30)

    assert batch_api.request_timeouts, "keine API-Calls beobachtet"
    for timeout in batch_api.request_timeouts:
        # Der K8s-Client wertet nur int aus und verwirft einen float still.
        assert isinstance(timeout, int) and not isinstance(timeout, bool)
        assert 0 < timeout * k8s.SHUTDOWN_API_CALLS_PER_RUN <= config.GRACEFUL_SHUTDOWN_TIMEOUT


async def test_run_without_job_counts_as_interrupted(test_session, shutdown_budget, batch_api):
    """
    Leere Job-Liste ist die Antwort des API-Servers, keine Lücke im lokalen
    Tracking: zu dem Run läuft nichts mehr.
    """
    shutdown_budget(2)
    run = _running_run(test_session)

    await asyncio.wait_for(k8s.graceful_shutdown(test_session), timeout=30)

    test_session.refresh(run)
    assert run.status == RunStatus.INTERRUPTED
    assert run.finished_at is not None


async def test_api_errors_become_warning(test_session, shutdown_budget, batch_api):
    """Fehlgeschlagene Liste bzw. Löschung: WARNING statt stiller INTERRUPTED."""
    shutdown_budget(2)
    list_run = _running_run(test_session, "liste-kaputt")
    delete_run = _running_run(test_session, "loeschen-kaputt")
    batch_api.add_job(list_run.id)
    batch_api.add_job(delete_run.id)
    batch_api.fail_list_for.add(list_run.id)
    batch_api.fail_delete_for.add(delete_run.id)

    await asyncio.wait_for(k8s.graceful_shutdown(test_session), timeout=30)

    test_session.refresh(list_run)
    test_session.refresh(delete_run)
    assert list_run.status == RunStatus.WARNING
    assert delete_run.status == RunStatus.WARNING


async def test_already_deleted_job_counts_as_interrupted(
    test_session, shutdown_budget, batch_api
):
    """404 beim Löschen heisst: der TTL-Controller war schneller. Kein Fehler."""
    shutdown_budget(2)
    run = _running_run(test_session)
    batch_api.add_job(run.id)

    def _gone(name=None, namespace=None, propagation_policy=None, _request_timeout=None):
        raise ApiException(status=404, reason="Not Found")

    batch_api.delete_namespaced_job = _gone

    await asyncio.wait_for(k8s.graceful_shutdown(test_session), timeout=30)

    test_session.refresh(run)
    assert run.status == RunStatus.INTERRUPTED


async def test_shutdown_without_running_runs_is_a_noop(test_session, shutdown_budget, batch_api):
    shutdown_budget(2)
    await asyncio.wait_for(k8s.graceful_shutdown(test_session), timeout=10)
    assert batch_api.list_calls == 0


async def test_shutdown_does_not_wait_for_the_shared_volume(
    test_session, shutdown_budget, batch_api, monkeypatch
):
    """
    ``rmtree`` über ein RWX-Volume ist blockierende I/O ohne Obergrenze. Im
    Shutdown hat sie nichts verloren – der Startup-Cleanup erledigt das.
    """
    shutdown_budget(2)
    run = _running_run(test_session)
    batch_api.add_job(run.id)
    called = threading.Event()
    monkeypatch.setattr(
        k8s, "_cleanup_shared_pipeline_run", lambda run_id: called.set()
    )

    await asyncio.wait_for(k8s.graceful_shutdown(test_session), timeout=30)

    assert not called.is_set()


# --- Zombie-Reconciliation ---------------------------------------------------

async def test_reconcile_resolves_running_runs_without_job(test_session, batch_api):
    """
    Der Gegenpart zum Shutdown: ohne diesen Schritt bliebe ein Run, dessen Job
    weg ist, für immer auf RUNNING.
    """
    orphan = _running_run(test_session, "job-weg")

    await asyncio.wait_for(k8s.reconcile_zombie_jobs(test_session), timeout=10)

    test_session.refresh(orphan)
    assert orphan.status == RunStatus.INTERRUPTED
    assert orphan.finished_at is not None


async def test_reconcile_keeps_runs_whose_job_still_exists(test_session, batch_api):
    """Ein noch laufender Job heisst: der Run läuft. Nicht anfassen."""
    run = _running_run(test_session, "laeuft-noch")
    batch_api.add_job(run.id)

    await asyncio.wait_for(k8s.reconcile_zombie_jobs(test_session), timeout=10)

    test_session.refresh(run)
    assert run.status == RunStatus.RUNNING
    assert run.finished_at is None


async def test_reconcile_still_carries_over_finished_jobs(test_session, batch_api):
    """Der bestehende Pfad bleibt: existierender Job mit Ausgang schlägt raten."""
    success_run = _running_run(test_session, "erfolg")
    failed_run = _running_run(test_session, "fehler")
    batch_api.add_job(success_run.id, succeeded=1)
    batch_api.add_job(failed_run.id, failed=1)

    await asyncio.wait_for(k8s.reconcile_zombie_jobs(test_session), timeout=10)

    test_session.refresh(success_run)
    test_session.refresh(failed_run)
    assert success_run.status == RunStatus.SUCCESS
    assert failed_run.status == RunStatus.FAILED


async def test_reconcile_does_not_resolve_when_listing_fails(test_session, batch_api):
    """
    Ohne Job-Liste ist "kein Job vorhanden" nicht belegt – ein Fehler des
    API-Servers darf nicht alle laufenden Runs abräumen.
    """
    run = _running_run(test_session)

    def _boom(**kwargs):
        raise ApiException(status=500, reason="API-Server weg")

    batch_api.list_namespaced_job = _boom

    await asyncio.wait_for(k8s.reconcile_zombie_jobs(test_session), timeout=10)

    test_session.refresh(run)
    assert run.status == RunStatus.RUNNING


async def test_reconcile_does_not_resolve_on_a_partial_listing(test_session, batch_api):
    """Continue-Token: die fehlende Seite kann den Job des Runs enthalten."""
    run = _running_run(test_session)
    batch_api.continue_token = "naechste-seite"

    await asyncio.wait_for(k8s.reconcile_zombie_jobs(test_session), timeout=10)

    test_session.refresh(run)
    assert run.status == RunStatus.RUNNING


async def test_shutdown_and_reconcile_close_the_loop(
    test_session, shutdown_budget, batch_api
):
    """
    Der Vertrag zwischen beiden: was der Shutdown im Budget nicht schafft,
    bleibt RUNNING – und wird beim nächsten Start aufgelöst. Hier der harte
    Fall: der Job ist inzwischen weg (gelöscht oder vom TTL-Controller geholt),
    der Run steht noch auf RUNNING.
    """
    shutdown_budget(1)
    stuck_run = _running_run(test_session, "abgeschossen")
    batch_api.add_job(stuck_run.id)
    batch_api.block_for[stuck_run.id] = 30.0

    await asyncio.wait_for(k8s.graceful_shutdown(test_session), timeout=30)
    test_session.refresh(stuck_run)
    assert stuck_run.status == RunStatus.RUNNING

    # Nächster Start: der Job ist weg.
    batch_api.jobs.clear()
    await asyncio.wait_for(k8s.reconcile_zombie_jobs(test_session), timeout=10)

    test_session.refresh(stuck_run)
    assert stuck_run.status == RunStatus.INTERRUPTED
    assert stuck_run.finished_at is not None
