"""
Regression-Tests für das Error-Mapping der drei Pipeline-Start-Pfade.

``POST /api/pipelines/{name}/run``, ``POST /api/runs/{id}/retry`` und
``POST /api/webhooks/{name}/{key}`` haben früher JEDEN ``RuntimeError`` aus
``run_pipeline()`` auf 429 TOO_MANY_REQUESTS abgebildet - mit dem Kommentar
"Concurrency-Limit erreicht". Das Concurrency-Limit ist aber nicht der einzige
``RuntimeError``, der dort herauskommt: ``app/services/secrets.py`` meldet einen
fehlenden oder ungültigen ``ENCRYPTION_KEY`` ebenfalls als ``RuntimeError``.

Auf einer Instanz ohne gültigen Key antwortete ein Pipeline-Start deshalb mit
"429 Too Many Requests" und einer ENCRYPTION_KEY-Meldung im Body. Wer den
Status-Code liest, sucht dann nach einem Rate-Limit, das nie erreicht war.

Der Fix trennt die Fälle über den Exception-Typ
(``app.executor.ConcurrencyLimitError``) statt über den Status-Code.

Getestet wird:
- das globale Concurrency-Limit und das pipeline-spezifische max_instances-Limit
  bilden weiterhin auf 429 ab (alle drei Pfade)
- ein fehlender oder ungültiger ENCRYPTION_KEY bildet auf 5xx ab, nicht auf 429
- ``run_pipeline()`` unterscheidet die beiden Fälle am Exception-Typ
- ``ConcurrencyLimitError`` bleibt ein ``RuntimeError`` (Aufrufer ausserhalb der
  API - Scheduler, daemon_watcher, Retry-/Downstream-Pfade - fangen breit)

Hinweis zum Test-Setup: Produktion kann diesen Zustand nicht erreichen, weil
``app/startup.py`` ohne gültigen Key den Boot verweigert, und ``conftest.py``
setzt für Tests immer einen Key. Ein kaputter Key muss deshalb explizit
simuliert werden - inklusive Reset des modulglobalen Fernet-Caches
(``app/services/secrets.py::_fernet``), sonst bleibt die einmal initialisierte
Instanz gültig und der Fehler tritt nie auf.
"""

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock

from app.core.config import config
from app.executor import ConcurrencyLimitError
from app.executor import core as executor_core
from app.models import PipelineRun, RunStatus, Secret
from app.services import secrets as secrets_module
from app.services.pipeline_discovery import discover_pipelines
from app.services.secrets import encrypt

WEBHOOK_KEY = "test-webhook-key-4711"


@pytest.fixture(autouse=True)
def _clean_running_containers():
    """
    ``run_pipeline()`` registriert für den Docker-Executor einen Platzhalter in
    ``_running_containers``. Diese Tests füllen das Dict absichtlich, um das
    Concurrency-Limit zu treffen - ohne Cleanup laufen Folgetests in dasselbe
    Limit.
    """
    executor_core._running_containers.clear()
    yield
    executor_core._running_containers.clear()


@pytest.fixture
def container_task(monkeypatch):
    """Koppelt den echten Container-Start ab (kein Docker in Tests)."""
    mock = AsyncMock()
    monkeypatch.setattr(executor_core, "_run_container_task", mock)
    return mock


@pytest.fixture
def at_concurrency_limit(monkeypatch):
    """Setzt das globale Concurrency-Limit auf "erreicht" (Docker-Executor)."""
    monkeypatch.setattr(config, "MAX_CONCURRENT_RUNS", 1)
    executor_core._running_containers[uuid4()] = None


@pytest.fixture
def break_encryption_key(monkeypatch):
    """
    Macht den ENCRYPTION_KEY unbenutzbar (fehlend oder ungültig).

    Der Reset von ``_fernet`` ist Pflicht: ``_get_fernet()`` cached die
    Fernet-Instanz modulglobal. Wer nur die Konfiguration ändert, arbeitet
    weiter mit der gültigen Instanz aus einem früheren Test und der Fehler
    tritt nie auf.

    Als Callable (statt direkt als Fixture), damit Tests erst ihre Fixtures mit
    dem gültigen Key aufbauen können - z.B. ein verschlüsseltes Secret anlegen -
    und den Key danach zerstören. ``monkeypatch`` stellt beides am Testende
    wieder her.
    """
    def _break(key=None):
        monkeypatch.setattr(config, "ENCRYPTION_KEY", key)
        monkeypatch.setattr(secrets_module, "_fernet", None)

    return _break


@pytest.fixture(params=[None, "kein-gueltiger-fernet-key"], ids=["missing", "invalid"])
def broken_encryption_key(request, break_encryption_key):
    """Instanz ohne benutzbaren ENCRYPTION_KEY - beide Varianten des Defekts."""
    break_encryption_key(request.param)
    return request.param


def _write_pipeline(pipelines_dir, name: str, pipeline_json: dict) -> None:
    pipeline_dir = pipelines_dir / name
    pipeline_dir.mkdir(exist_ok=True)
    (pipeline_dir / "main.py").write_text("print('ok')")
    (pipeline_dir / "pipeline.json").write_text(json.dumps(pipeline_json))
    discover_pipelines(force_refresh=True)


def _add_run(session, pipeline_name: str, status: RunStatus, **kwargs) -> PipelineRun:
    run = PipelineRun(
        pipeline_name=pipeline_name,
        status=status,
        log_file=f"logs/{pipeline_name}.log",
        started_at=datetime.now(timezone.utc),
        **kwargs,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


# ---------------------------------------------------------------------------
# 1. Das echte Rate-Limit bleibt 429
# ---------------------------------------------------------------------------

class TestConcurrencyLimitStillReturns429:
    def test_pipeline_run_returns_429(
        self, authenticated_client, temp_pipelines_dir, at_concurrency_limit, container_task
    ):
        _write_pipeline(temp_pipelines_dir, "limit_pipeline", {})

        response = authenticated_client.post(
            "/api/pipelines/limit_pipeline/run", json={"env_vars": {"FOO": "bar"}}
        )

        assert response.status_code == 429
        assert "Concurrency-Limit" in response.json()["detail"]

    def test_max_instances_limit_returns_429(
        self, authenticated_client, temp_pipelines_dir, test_session, container_task
    ):
        """Das pipeline-spezifische max_instances-Limit ist ebenfalls ein Rate-Limit."""
        _write_pipeline(temp_pipelines_dir, "instances_pipeline", {"max_instances": 1})
        _add_run(test_session, "instances_pipeline", RunStatus.RUNNING)

        response = authenticated_client.post(
            "/api/pipelines/instances_pipeline/run", json={}
        )

        assert response.status_code == 429
        assert "Max-Instanzen-Limit" in response.json()["detail"]

    def test_retry_returns_429(
        self, authenticated_client, temp_pipelines_dir, test_session,
        at_concurrency_limit, container_task
    ):
        _write_pipeline(temp_pipelines_dir, "retry_limit_pipeline", {})
        run = _add_run(test_session, "retry_limit_pipeline", RunStatus.SUCCESS)

        response = authenticated_client.post(f"/api/runs/{run.id}/retry")

        assert response.status_code == 429
        assert "Concurrency-Limit" in response.json()["detail"]

    def test_webhook_returns_429(
        self, client, temp_pipelines_dir, at_concurrency_limit, container_task
    ):
        _write_pipeline(
            temp_pipelines_dir, "webhook_limit_pipeline", {"webhook_key": WEBHOOK_KEY}
        )

        response = client.post(f"/api/webhooks/webhook_limit_pipeline/{WEBHOOK_KEY}")

        assert response.status_code == 429
        assert "Concurrency-Limit" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 2. Ein kaputter ENCRYPTION_KEY ist kein Rate-Limit
# ---------------------------------------------------------------------------

class TestBrokenEncryptionKeyReturns5xx:
    def test_pipeline_run_returns_500_not_429(
        self, authenticated_client, temp_pipelines_dir, broken_encryption_key, container_task
    ):
        """
        Der ursprünglich gemeldete Fall: ad-hoc Env-Vars werden verschlüsselt am
        Run abgelegt, das braucht einen gültigen Key.
        """
        _write_pipeline(temp_pipelines_dir, "broken_key_pipeline", {})

        response = authenticated_client.post(
            "/api/pipelines/broken_key_pipeline/run", json={"env_vars": {"FOO": "bar"}}
        )

        assert response.status_code == 500, (
            f"Konfigurationsfehler darf nicht als Rate-Limit erscheinen "
            f"(bekommen: {response.status_code} {response.text})"
        )

    def test_pipeline_run_with_declared_secrets_returns_500_not_429(
        self, authenticated_client, temp_pipelines_dir, test_session,
        break_encryption_key, container_task
    ):
        """
        Reproduziert auch ohne ad-hoc Env-Vars: eine Pipeline, die in
        pipeline.json ``secrets`` deklariert, muss diese entschlüsseln.

        Der Key wird hier erst NACH dem Anlegen des Secrets zerstört - sonst
        liesse sich der verschlüsselte Wert nicht erzeugen.
        """
        test_session.add(
            Secret(key="API_KEY", value=encrypt("s3cr3t"), is_parameter=False)
        )
        test_session.commit()
        _write_pipeline(
            temp_pipelines_dir, "secret_key_pipeline", {"secrets": ["API_KEY"]}
        )
        break_encryption_key()

        response = authenticated_client.post(
            "/api/pipelines/secret_key_pipeline/run", json={}
        )

        assert response.status_code == 500, (
            f"Konfigurationsfehler darf nicht als Rate-Limit erscheinen "
            f"(bekommen: {response.status_code} {response.text})"
        )

    def test_retry_returns_500_not_429(
        self, authenticated_client, temp_pipelines_dir, test_session,
        break_encryption_key, container_task
    ):
        """
        Der Retry entschlüsselt die ad-hoc Env-Vars des Original-Runs. Ohne
        gültigen Key fiel dieser RuntimeError früher sogar ungemappt aus dem
        Endpoint (die Entschlüsselung lag vor dem try-Block).
        """
        _write_pipeline(temp_pipelines_dir, "retry_key_pipeline", {})
        run = _add_run(
            test_session,
            "retry_key_pipeline",
            RunStatus.SUCCESS,
            encrypted_env_vars=encrypt(json.dumps({"FOO": "bar"})),
        )
        break_encryption_key()

        response = authenticated_client.post(f"/api/runs/{run.id}/retry")

        assert response.status_code == 500, (
            f"Konfigurationsfehler darf nicht als Rate-Limit erscheinen "
            f"(bekommen: {response.status_code} {response.text})"
        )

    def test_webhook_returns_500_not_429(
        self, client, temp_pipelines_dir, broken_encryption_key, container_task
    ):
        _write_pipeline(
            temp_pipelines_dir, "webhook_key_pipeline", {"webhook_key": WEBHOOK_KEY}
        )

        response = client.post(
            f"/api/webhooks/webhook_key_pipeline/{WEBHOOK_KEY}",
            json={"env_vars": {"FOO": "bar"}},
        )

        assert response.status_code == 500, (
            f"Konfigurationsfehler darf nicht als Rate-Limit erscheinen "
            f"(bekommen: {response.status_code} {response.text})"
        )

    def test_run_without_env_vars_still_succeeds_with_broken_key(
        self, authenticated_client, temp_pipelines_dir, broken_encryption_key, container_task
    ):
        """
        Dokumentiert die Asymmetrie des Bugs: ohne zu ver-/entschlüsselnde Werte
        wird der Key nie angefasst, der Start gelingt. Genau deshalb fiel der
        falsche Status-Code lange nicht auf - er trat nur mit Env-Vars oder
        deklarierten Secrets auf.
        """
        _write_pipeline(temp_pipelines_dir, "no_env_pipeline", {})

        response = authenticated_client.post(
            "/api/pipelines/no_env_pipeline/run", json={"env_vars": {}}
        )

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# 3. run_pipeline() unterscheidet die Fälle am Exception-Typ
# ---------------------------------------------------------------------------

class TestRunPipelineExceptionTypes:
    def test_concurrency_limit_error_is_a_runtime_error(self):
        """
        Aufrufer ausserhalb der API (Scheduler, daemon_watcher, Retry- und
        Downstream-Pfade) fangen breit auf Exception/RuntimeError. Die
        Vererbung hält ihr Verhalten unverändert - nur die API-Layer
        unterscheiden feiner.
        """
        assert issubclass(ConcurrencyLimitError, RuntimeError)

    async def test_concurrency_limit_raises_concurrency_limit_error(
        self, test_session, temp_pipelines_dir, at_concurrency_limit, container_task
    ):
        _write_pipeline(temp_pipelines_dir, "direct_limit_pipeline", {})

        with pytest.raises(ConcurrencyLimitError):
            await executor_core.run_pipeline(
                "direct_limit_pipeline", session=test_session
            )

    async def test_max_instances_raises_concurrency_limit_error(
        self, test_session, temp_pipelines_dir, container_task
    ):
        _write_pipeline(
            temp_pipelines_dir, "direct_instances_pipeline", {"max_instances": 1}
        )
        _add_run(test_session, "direct_instances_pipeline", RunStatus.PENDING)

        with pytest.raises(ConcurrencyLimitError):
            await executor_core.run_pipeline(
                "direct_instances_pipeline", session=test_session
            )

    async def test_broken_key_raises_plain_runtime_error(
        self, test_session, temp_pipelines_dir, broken_encryption_key, container_task
    ):
        """
        Der Konfigurationsfehler bleibt ein RuntimeError - aber eben KEIN
        ConcurrencyLimitError. Genau daran hängt das korrekte Status-Mapping.
        """
        _write_pipeline(temp_pipelines_dir, "direct_key_pipeline", {})

        with pytest.raises(RuntimeError) as exc_info:
            await executor_core.run_pipeline(
                "direct_key_pipeline",
                env_vars={"FOO": "bar"},
                session=test_session,
            )

        assert not isinstance(exc_info.value, ConcurrencyLimitError)
        assert "ENCRYPTION_KEY" in str(exc_info.value)

    async def test_failed_start_releases_concurrency_placeholder(
        self, test_session, temp_pipelines_dir, broken_encryption_key, container_task
    ):
        """
        Ein gescheiterter Start darf den Platzhalter aus ``_running_containers``
        nicht liegen lassen - sonst erzeugt ein Konfigurationsfehler nach
        MAX_CONCURRENT_RUNS Versuchen ein echtes Concurrency-Limit und damit
        doch noch 429.
        """
        _write_pipeline(temp_pipelines_dir, "placeholder_pipeline", {})

        with pytest.raises(RuntimeError):
            await executor_core.run_pipeline(
                "placeholder_pipeline",
                env_vars={"FOO": "bar"},
                session=test_session,
            )

        assert executor_core._running_containers == {}
