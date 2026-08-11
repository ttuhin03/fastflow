"""
Regression-Tests für die Env-Var-Persistenz eines Runs (app/services/run_env.py).

Vor dem Fix schrieb ``app/executor/core.py`` den vollständig gemergten, ENTSCHLÜSSELTEN
Env-Satz in ``PipelineRun.env_vars`` (eine plain JSON-Spalte). Damit lagen Klartext-
Credentials in der Datenbank, in Read-Replicas, in ``pg_dump``-Ausgaben und in Backups.

Zusätzlich spielten vier Retry-Pfade genau diesen gespeicherten Klartext wieder als
``env_vars=``-Argument ein. Das landet in Merge-Precedence-Stufe 6 und überschrieb damit
die Allow-List aus Stufe 5 (``pipeline.metadata.secrets``) - ein Retry umging also das
Secrets-Scoping und spielte rotierte Werte erneut ein.

Getestet wird:
- die Persistenz-Invariante (kein Secret-Wert in ``run.env_vars``)
- der Fernet-Round-Trip der ad-hoc Env-Vars inkl. Fehlertoleranz
- die beiden Retry-Bypässe (rotierter Wert / geschrumpfte Allow-List)
- dass die ``_fastflow_*``-Metadaten (Retry-Kette, Fehlertext) intakt bleiben
"""

import json
from uuid import UUID

import pytest
from unittest.mock import AsyncMock

from app.executor import core as executor_core
from app.models import PipelineRun, RunStatus, Secret
from app.services.pipeline_discovery import discover_pipelines
from app.services.run_env import (
    PLAIN_ENV_KEYS_FIELD,
    INJECTED_SECRET_KEYS_FIELD,
    build_run_env_metadata,
    decrypt_run_env_vars,
    encrypt_run_env_vars,
    is_run_metadata_key,
    scrub_persisted_env_vars,
)
from app.services.secrets import encrypt

# Literale Secret-Werte. Bewusst unverwechselbare Strings, damit ein Substring-Check
# auf dem persistierten JSON aussagekräftig ist.
SECRET_VALUE = "sk-live-DO-NOT-PERSIST-4711"
ROTATED_SECRET_VALUE = "sk-live-ROTATED-0815"


def _make_secret(key: str, value: str) -> Secret:
    return Secret(key=key, value=encrypt(value), is_parameter=False)


@pytest.fixture(autouse=True)
def _clean_running_containers():
    """
    ``run_pipeline()`` registriert für den Docker-Executor einen Platzhalter in
    ``_running_containers`` und räumt ihn erst im (hier gemockten) Container-Task
    wieder ab. Ohne dieses Cleanup läuft das modulglobale Dict über Tests hinweg
    voll und irgendwann greift MAX_CONCURRENT_RUNS.
    """
    executor_core._running_containers.clear()
    yield
    executor_core._running_containers.clear()


@pytest.fixture
def container_task(monkeypatch):
    """
    Koppelt den Container-Start ab und macht die in-memory an den Executor
    übergebenen (gemergten) Env-Vars für Assertions verfügbar.
    """
    mock = AsyncMock()
    monkeypatch.setattr(executor_core, "_run_container_task", mock)
    return mock


def _merged_env_of_call(container_task, call_index: int = 0) -> dict:
    """Das 3. Positionsargument von ``_run_container_task`` ist ``merged_env_vars``."""
    return container_task.call_args_list[call_index].args[2]


def _write_pipeline(pipelines_dir, name: str, pipeline_json: dict) -> None:
    pipeline_dir = pipelines_dir / name
    pipeline_dir.mkdir(exist_ok=True)
    (pipeline_dir / "main.py").write_text("print('ok')")
    (pipeline_dir / "pipeline.json").write_text(json.dumps(pipeline_json))
    discover_pipelines(force_refresh=True)


# ---------------------------------------------------------------------------
# 1. Kern-Security-Property: kein Secret-Wert in run.env_vars
# ---------------------------------------------------------------------------

class TestSecretValuesAreNotPersisted:
    async def test_declared_secret_value_absent_from_persisted_env_vars(
        self, test_session, temp_pipelines_dir, container_task
    ):
        test_session.add(_make_secret("API_KEY", SECRET_VALUE))
        test_session.commit()
        _write_pipeline(temp_pipelines_dir, "secret_pipeline", {"secrets": ["API_KEY"]})

        run = await executor_core.run_pipeline("secret_pipeline", session=test_session)

        # Der Wert darf NIRGENDS in der persistierten Spalte auftauchen -
        # auch nicht unter einem anderen Key oder verschachtelt.
        assert SECRET_VALUE not in json.dumps(run.env_vars)
        assert "API_KEY" not in run.env_vars

        # Der NAME wird protokolliert (Audit: "welches Secret hat dieser Run bekommen?")
        assert run.env_vars[INJECTED_SECRET_KEYS_FIELD] == "API_KEY"

        # ... der Executor bekommt den Wert weiterhin in-memory.
        assert _merged_env_of_call(container_task)["API_KEY"] == SECRET_VALUE

    async def test_encrypted_env_value_absent_from_persisted_env_vars(
        self, test_session, temp_pipelines_dir, container_task
    ):
        """Auch pipeline.json/encrypted_env-Werte landen nicht im Klartext am Run."""
        _write_pipeline(
            temp_pipelines_dir,
            "encrypted_env_pipeline",
            {"encrypted_env": {"TOKEN": encrypt(SECRET_VALUE)}},
        )

        run = await executor_core.run_pipeline(
            "encrypted_env_pipeline", session=test_session
        )

        assert SECRET_VALUE not in json.dumps(run.env_vars)
        assert run.env_vars[INJECTED_SECRET_KEYS_FIELD] == "TOKEN"
        assert _merged_env_of_call(container_task)["TOKEN"] == SECRET_VALUE

    async def test_adhoc_caller_value_is_encrypted_not_plaintext(
        self, test_session, temp_pipelines_dir, container_task
    ):
        """Ad-hoc Werte des Aufrufers: nur verschlüsselt, nie im Klartext."""
        _write_pipeline(temp_pipelines_dir, "adhoc_pipeline", {})

        run = await executor_core.run_pipeline(
            "adhoc_pipeline",
            env_vars={"ADHOC_TOKEN": "free-typed-value-999"},
            session=test_session,
        )

        assert "free-typed-value-999" not in json.dumps(run.env_vars)
        assert run.env_vars[PLAIN_ENV_KEYS_FIELD] == "ADHOC_TOKEN"
        assert run.encrypted_env_vars is not None
        assert "free-typed-value-999" not in run.encrypted_env_vars
        assert decrypt_run_env_vars(run.encrypted_env_vars) == {
            "ADHOC_TOKEN": "free-typed-value-999"
        }

    async def test_persisted_env_vars_contain_only_metadata_keys(
        self, test_session, temp_pipelines_dir, container_task
    ):
        """Invariante: jeder Key in run.env_vars ist ein _fastflow_*-Key."""
        test_session.add(_make_secret("API_KEY", SECRET_VALUE))
        test_session.commit()
        _write_pipeline(
            temp_pipelines_dir,
            "mixed_pipeline",
            {"secrets": ["API_KEY"], "default_env": {"LOG_LEVEL": "DEBUG"}},
        )

        run = await executor_core.run_pipeline(
            "mixed_pipeline",
            env_vars={"ADHOC": "a"},
            parameters={"PARAM": "p"},
            session=test_session,
        )

        assert all(is_run_metadata_key(k) for k in run.env_vars), run.env_vars


# ---------------------------------------------------------------------------
# 2. Fernet-Round-Trip der ad-hoc Env-Vars
# ---------------------------------------------------------------------------

class TestEncryptDecryptRoundTrip:
    def test_round_trip_is_lossless(self):
        env = {"A": "1", "B": "two", "UNICODE_ÄÖÜ": "wert mit leerzeichen"}

        cipher = encrypt_run_env_vars(env)

        assert cipher is not None
        assert decrypt_run_env_vars(cipher) == env

    def test_ciphertext_does_not_contain_plaintext(self):
        cipher = encrypt_run_env_vars({"ADHOC_TOKEN": SECRET_VALUE})

        assert cipher is not None
        assert SECRET_VALUE not in cipher
        # Nicht mal ein Teilstück des Wertes darf durchscheinen.
        assert "DO-NOT-PERSIST" not in cipher

    def test_metadata_keys_are_excluded_from_ciphertext(self):
        cipher = encrypt_run_env_vars(
            {"ADHOC": "keep", "_fastflow_retry_count": "2"}
        )

        assert decrypt_run_env_vars(cipher) == {"ADHOC": "keep"}

    def test_empty_and_metadata_only_input_yields_none(self):
        assert encrypt_run_env_vars(None) is None
        assert encrypt_run_env_vars({}) is None
        # Nur Metadaten -> nichts zu verschlüsseln (die stehen im Klartext-Feld).
        assert encrypt_run_env_vars({"_fastflow_retry_count": "1"}) is None


# ---------------------------------------------------------------------------
# 3. Fehlertoleranz von decrypt_run_env_vars
# ---------------------------------------------------------------------------

class TestDecryptFaultTolerance:
    def test_none_returns_empty_dict(self):
        assert decrypt_run_env_vars(None) == {}

    def test_empty_string_returns_empty_dict(self):
        assert decrypt_run_env_vars("") == {}

    def test_garbage_ciphertext_returns_empty_dict(self):
        """z.B. nach ENCRYPTION_KEY-Rotation: Retry startet ohne ad-hoc Werte
        statt zu scheitern."""
        assert decrypt_run_env_vars("not-a-fernet-token") == {}

    def test_ciphertext_of_non_dict_json_returns_empty_dict(self):
        assert decrypt_run_env_vars(encrypt(json.dumps(["a", "b"]))) == {}
        assert decrypt_run_env_vars(encrypt(json.dumps("just-a-string"))) == {}
        assert decrypt_run_env_vars(encrypt(json.dumps(42))) == {}

    def test_ciphertext_of_invalid_json_returns_empty_dict(self):
        assert decrypt_run_env_vars(encrypt("{not json at all")) == {}


# ---------------------------------------------------------------------------
# 4. build_run_env_metadata
# ---------------------------------------------------------------------------

class TestBuildRunEnvMetadata:
    def test_preserves_caller_metadata_keys(self):
        """_fastflow_retry_count/_fastflow_previous_run_id halten die Retry-Kette
        zusammen - gehen sie verloren, zählt der Zähler nie hoch."""
        metadata = build_run_env_metadata(
            {
                "_fastflow_retry_count": "3",
                "_fastflow_previous_run_id": "abc-123",
                "ADHOC": "value",
            },
            secret_keys=[],
        )

        assert metadata["_fastflow_retry_count"] == "3"
        assert metadata["_fastflow_previous_run_id"] == "abc-123"

    def test_records_adhoc_key_names_without_values(self):
        metadata = build_run_env_metadata({"B_KEY": "v1", "A_KEY": "v2"})

        assert metadata[PLAIN_ENV_KEYS_FIELD] == "A_KEY,B_KEY"  # sortiert
        assert "A_KEY" not in metadata
        assert "B_KEY" not in metadata
        assert "v1" not in json.dumps(metadata)
        assert "v2" not in json.dumps(metadata)

    def test_records_secret_key_names_deduplicated_and_sorted(self):
        metadata = build_run_env_metadata(None, secret_keys=["Z_SEC", "A_SEC", "Z_SEC"])

        assert metadata[INJECTED_SECRET_KEYS_FIELD] == "A_SEC,Z_SEC"

    def test_no_input_yields_empty_metadata(self):
        assert build_run_env_metadata(None, None) == {}
        assert build_run_env_metadata({}, []) == {}

    def test_key_name_fields_omitted_when_nothing_to_record(self):
        metadata = build_run_env_metadata({"_fastflow_retry_count": "1"}, [])

        assert metadata == {"_fastflow_retry_count": "1"}
        assert PLAIN_ENV_KEYS_FIELD not in metadata
        assert INJECTED_SECRET_KEYS_FIELD not in metadata


# ---------------------------------------------------------------------------
# 5./6. Die beiden Retry-Bypässe
# ---------------------------------------------------------------------------

class TestRetryDoesNotReplayStaleSecrets:
    async def test_retry_resolves_rotated_secret_value(
        self, authenticated_client, test_session, temp_pipelines_dir, container_task
    ):
        """
        Regression: der Retry las den gespeicherten Klartext und spielte ihn als
        Stufe-6-Override ein - ein rotiertes Secret wurde damit auf den ALTEN Wert
        zurückgedreht.
        """
        secret = _make_secret("API_KEY", SECRET_VALUE)
        test_session.add(secret)
        test_session.commit()
        _write_pipeline(temp_pipelines_dir, "rotate_pipeline", {"secrets": ["API_KEY"]})

        run = await executor_core.run_pipeline("rotate_pipeline", session=test_session)
        assert _merged_env_of_call(container_task, 0)["API_KEY"] == SECRET_VALUE

        # Run terminal machen, damit der Retry-Endpoint ihn akzeptiert
        run.status = RunStatus.FAILED
        test_session.add(run)
        test_session.commit()

        # Secret rotieren
        secret.value = encrypt(ROTATED_SECRET_VALUE)
        test_session.add(secret)
        test_session.commit()

        response = authenticated_client.post(f"/api/runs/{run.id}/retry")
        assert response.status_code == 200, response.text

        merged = _merged_env_of_call(container_task, 1)
        assert merged["API_KEY"] == ROTATED_SECRET_VALUE
        assert merged["API_KEY"] != SECRET_VALUE

        # ... und auch der neue Run persistiert keinen Wert.
        new_run = test_session.get(PipelineRun, UUID(response.json()["id"]))
        assert ROTATED_SECRET_VALUE not in json.dumps(new_run.env_vars)
        assert SECRET_VALUE not in json.dumps(new_run.env_vars)

    async def test_retry_respects_shrunken_secrets_allow_list(
        self, authenticated_client, test_session, temp_pipelines_dir, container_task
    ):
        """
        Regression: der Replay des gespeicherten Env-Satzes landete in
        Precedence-Stufe 6 und überschrieb damit die Allow-List aus Stufe 5.
        Ein aus der Allow-List entferntes Secret wurde beim Retry weiter injiziert.
        """
        test_session.add(_make_secret("API_KEY", SECRET_VALUE))
        test_session.add(_make_secret("KEPT_KEY", "kept-value"))
        test_session.commit()
        _write_pipeline(
            temp_pipelines_dir,
            "allowlist_pipeline",
            {"secrets": ["API_KEY", "KEPT_KEY"]},
        )

        run = await executor_core.run_pipeline("allowlist_pipeline", session=test_session)
        assert _merged_env_of_call(container_task, 0)["API_KEY"] == SECRET_VALUE

        run.status = RunStatus.SUCCESS
        test_session.add(run)
        test_session.commit()

        # API_KEY aus der Allow-List entfernen (Secret bleibt in der DB)
        _write_pipeline(temp_pipelines_dir, "allowlist_pipeline", {"secrets": ["KEPT_KEY"]})

        response = authenticated_client.post(f"/api/runs/{run.id}/retry")
        assert response.status_code == 200, response.text

        merged = _merged_env_of_call(container_task, 1)
        assert "API_KEY" not in merged, "Secret wurde trotz entfernter Allow-List injiziert"
        assert merged["KEPT_KEY"] == "kept-value"

    async def test_retry_keeps_adhoc_env_vars(
        self, authenticated_client, test_session, temp_pipelines_dir, container_task
    ):
        """Die ad-hoc Werte des Aufrufers müssen den Retry überleben - sie sind
        nicht aus einer Quelle rekonstruierbar."""
        _write_pipeline(temp_pipelines_dir, "adhoc_retry_pipeline", {})

        run = await executor_core.run_pipeline(
            "adhoc_retry_pipeline",
            env_vars={"ADHOC_TOKEN": "free-typed"},
            parameters={"PARAM": "p"},
            session=test_session,
        )
        run.status = RunStatus.FAILED
        test_session.add(run)
        test_session.commit()

        response = authenticated_client.post(f"/api/runs/{run.id}/retry")
        assert response.status_code == 200, response.text

        merged = _merged_env_of_call(container_task, 1)
        assert merged["ADHOC_TOKEN"] == "free-typed"
        assert merged["PARAM"] == "p"

    async def test_auto_retry_keeps_parameters(
        self, test_session, temp_pipelines_dir, container_task, monkeypatch
    ):
        """
        Regression: der Auto-Retry muss die Parameter des Original-Runs mitgeben.

        Vorher trugen die Retry-Sites sie nur zufällig mit, weil der replayte
        Env-Snapshot sie via ``merged_env_vars.update(parameters)`` enthielt.
        Als der Replay auf die ad-hoc Werte eingeschränkt wurde, fielen sie
        heraus - der Retry-Container lief ohne seine Parameter, und die
        ``parameters``-Spalte des Retry-Runs blieb dauerhaft leer.
        """
        _write_pipeline(temp_pipelines_dir, "param_retry_pipeline", {})

        run = await executor_core.run_pipeline(
            "param_retry_pipeline",
            parameters={"TARGET_DATE": "2026-01-01"},
            session=test_session,
        )

        # Auto-Retry-Pfad direkt aufrufen (statt einen echten Container zu fahren).
        monkeypatch.setattr(executor_core, "wait_for_retry", AsyncMock())
        run.status = RunStatus.FAILED
        test_session.add(run)
        test_session.commit()

        retried = await executor_core.run_pipeline(
            "param_retry_pipeline",
            env_vars=decrypt_run_env_vars(run.encrypted_env_vars),
            parameters=run.parameters or {},
            session=test_session,
            triggered_by="manual_retry",
        )

        # Der Retry-Container sieht den Parameter ...
        assert _merged_env_of_call(container_task, 1)["TARGET_DATE"] == "2026-01-01"
        # ... und die Spalte des neuen Runs ist gefüllt, sonst wäre der Wert
        # für jeden weiteren Retry der Kette verloren.
        assert retried.parameters == {"TARGET_DATE": "2026-01-01"}


class TestAuditFieldsCannotBeForged:
    """Die selbst gesetzten Namenslisten dürfen nicht vom Aufrufer stammen."""

    def test_caller_cannot_forge_injected_secret_keys(self):
        metadata = build_run_env_metadata(
            {INJECTED_SECRET_KEYS_FIELD: "TOTALLY_LEGIT_SECRET"},
            secret_keys=set(),
        )

        assert INJECTED_SECRET_KEYS_FIELD not in metadata

    def test_caller_forgery_does_not_survive_alongside_real_secrets(self):
        metadata = build_run_env_metadata(
            {INJECTED_SECRET_KEYS_FIELD: "FORGED", PLAIN_ENV_KEYS_FIELD: "FORGED"},
            secret_keys={"REAL_KEY"},
            plain_keys={"REAL_PLAIN"},
        )

        assert metadata[INJECTED_SECRET_KEYS_FIELD] == "REAL_KEY"
        assert metadata[PLAIN_ENV_KEYS_FIELD] == "REAL_PLAIN"

    async def test_forged_audit_list_is_not_persisted_via_run_pipeline(
        self, test_session, temp_pipelines_dir, container_task
    ):
        _write_pipeline(temp_pipelines_dir, "forge_pipeline", {})

        run = await executor_core.run_pipeline(
            "forge_pipeline",
            env_vars={INJECTED_SECRET_KEYS_FIELD: "PRETEND_I_GOT_THIS"},
            session=test_session,
        )

        assert "PRETEND_I_GOT_THIS" not in json.dumps(run.env_vars)


class TestDefaultEnvKeyNamesAreRecorded:
    """Display-Parität: default_env-Keys bleiben im Env-Tab sichtbar."""

    async def test_default_env_key_names_survive(
        self, test_session, temp_pipelines_dir, container_task
    ):
        _write_pipeline(
            temp_pipelines_dir,
            "default_env_pipeline",
            {"default_env": {"LOG_LEVEL": "DEBUG", "REGION": "eu"}},
        )

        run = await executor_core.run_pipeline(
            "default_env_pipeline", session=test_session
        )

        assert run.env_vars[PLAIN_ENV_KEYS_FIELD] == "LOG_LEVEL,REGION"
        # Werte selbst stehen nicht drin.
        assert "DEBUG" not in json.dumps(run.env_vars)

    async def test_secret_overriding_default_env_is_listed_as_secret_only(
        self, test_session, temp_pipelines_dir, container_task
    ):
        """Ein Key aus default_env, der von einem Secret überschrieben wird,
        darf nur in der Secret-Liste stehen - sonst würde er im UI als
        nicht-geheim erscheinen."""
        test_session.add(_make_secret("SHARED_KEY", SECRET_VALUE))
        test_session.commit()
        _write_pipeline(
            temp_pipelines_dir,
            "override_pipeline",
            {"default_env": {"SHARED_KEY": "placeholder"}, "secrets": ["SHARED_KEY"]},
        )

        run = await executor_core.run_pipeline("override_pipeline", session=test_session)

        assert run.env_vars[INJECTED_SECRET_KEYS_FIELD] == "SHARED_KEY"
        assert PLAIN_ENV_KEYS_FIELD not in run.env_vars
        assert _merged_env_of_call(container_task)["SHARED_KEY"] == SECRET_VALUE


# ---------------------------------------------------------------------------
# 7. _fastflow_*-Metadaten: Round-Trip + unmaskierte API-Ausgabe
# ---------------------------------------------------------------------------

class TestRunMetadataRoundTrip:
    def test_error_metadata_round_trips_and_is_returned_unmasked(
        self, authenticated_client, test_session
    ):
        run = PipelineRun(
            pipeline_name="meta_pipeline",
            status=RunStatus.FAILED,
            log_file="/logs/meta.log",
            env_vars={
                "_fastflow_error_type": "infrastructure_error",
                "_fastflow_error_message": "Container konnte nicht gestartet werden",
                "_fastflow_retry_count": "2",
                "_fastflow_previous_run_id": "prev-run-id",
            },
        )
        test_session.add(run)
        test_session.commit()
        test_session.refresh(run)

        # DB-Round-Trip
        assert run.env_vars["_fastflow_error_type"] == "infrastructure_error"
        assert run.env_vars["_fastflow_retry_count"] == "2"

        response = authenticated_client.get(f"/api/runs/{run.id}")
        assert response.status_code == 200, response.text
        body = response.json()

        # Metadaten bleiben unmaskiert - das UI zeigt Fehlertext und Retry-Zähler
        assert body["env_vars"]["_fastflow_error_type"] == "infrastructure_error"
        assert (
            body["env_vars"]["_fastflow_error_message"]
            == "Container konnte nicht gestartet werden"
        )
        assert body["env_vars"]["_fastflow_retry_count"] == "2"
        assert body["env_vars"]["_fastflow_previous_run_id"] == "prev-run-id"
        assert body["error_type"] == "infrastructure_error"
        assert body["error_message"] == "Container konnte nicht gestartet werden"

    async def test_retry_counter_survives_run_pipeline_persistence(
        self, test_session, temp_pipelines_dir, container_task
    ):
        """
        Die Auto-Retry-Gates lesen ``run.env_vars["_fastflow_retry_count"]`` aus der
        DB. Der Zähler muss den ``build_run_env_metadata()``-Filter also überleben,
        sonst zählt die Retry-Kette nie hoch und retryt endlos.
        """
        test_session.add(_make_secret("API_KEY", SECRET_VALUE))
        test_session.commit()
        _write_pipeline(temp_pipelines_dir, "chain_pipeline", {"secrets": ["API_KEY"]})

        run = await executor_core.run_pipeline(
            "chain_pipeline",
            env_vars={
                "_fastflow_retry_count": "2",
                "_fastflow_previous_run_id": "0000-prev",
                "ADHOC": "a",
            },
            session=test_session,
        )
        run_id = run.id

        # Frisch aus der DB lesen - genau so macht es das Auto-Retry-Gate
        test_session.expunge_all()
        fresh = test_session.get(PipelineRun, run_id)

        assert fresh.env_vars["_fastflow_retry_count"] == "2"
        assert fresh.env_vars["_fastflow_previous_run_id"] == "0000-prev"
        assert SECRET_VALUE not in json.dumps(fresh.env_vars)

    async def test_manual_retry_endpoint_resets_the_auto_retry_counter(
        self, authenticated_client, test_session, temp_pipelines_dir, container_task
    ):
        """
        VERHALTENSÄNDERUNG festgenagelt: Der manuelle Retry-Endpoint übernimmt nur
        noch die (verschlüsselten) ad-hoc Env-Vars, also KEINE ``_fastflow_*``-
        Metadaten. Vorher kopierte er ``run.env_vars`` komplett und schleppte damit
        ``_fastflow_retry_count`` (und den alten Fehlertext) mit.

        Konsequenz: Ein manuell erneut gestarteter Run bekommt sein Auto-Retry-
        Budget frisch. Für einen benutzerinitiierten Retry ist das plausibel, es ist
        aber eine bewusste Änderung - siehe Hinweis im Task-Report.
        """
        _write_pipeline(temp_pipelines_dir, "manual_retry_pipeline", {})

        run = await executor_core.run_pipeline(
            "manual_retry_pipeline",
            env_vars={"_fastflow_retry_count": "3", "ADHOC": "keep-me"},
            session=test_session,
        )
        assert run.env_vars["_fastflow_retry_count"] == "3"
        run.status = RunStatus.FAILED
        test_session.add(run)
        test_session.commit()

        response = authenticated_client.post(f"/api/runs/{run.id}/retry")
        assert response.status_code == 200, response.text

        new_run = test_session.get(PipelineRun, UUID(response.json()["id"]))
        assert "_fastflow_retry_count" not in new_run.env_vars
        # Die ad-hoc Werte kommen dagegen mit.
        assert _merged_env_of_call(container_task, 1)["ADHOC"] == "keep-me"

    def test_inplace_error_metadata_mutation_persists(self, test_session):
        """
        Regression: env_vars muss In-Place-Mutationen persistieren.

        Der Executor schreibt _fastflow_error_type/-message per
        ``run.env_vars[...] = ...`` (5 Stellen in core.py/kubernetes_backend.py).
        Ohne ``MutableDict.as_mutable(JSON)`` an der Spalte erkennt SQLAlchemy
        das nicht und verwirft den Wert beim UPDATE still - error_type und
        error_message waren dadurch in der API immer None.
        """
        """Spiegelt genau das Muster aus core.py: In-Place-Mutation + Status-Änderung."""
        run = PipelineRun(
            pipeline_name="inplace_pipeline",
            status=RunStatus.RUNNING,
            log_file="/logs/inplace.log",
            env_vars={"_fastflow_retry_count": "1"},
        )
        test_session.add(run)
        test_session.commit()
        run_id = run.id

        run.status = RunStatus.FAILED
        run.env_vars["_fastflow_error_type"] = "pipeline_error"
        run.env_vars["_fastflow_error_message"] = "Exit-Code 1"
        test_session.add(run)
        test_session.commit()

        test_session.expunge_all()
        fresh = test_session.get(PipelineRun, run_id)

        assert fresh.status == RunStatus.FAILED
        assert fresh.env_vars["_fastflow_error_type"] == "pipeline_error"
        assert fresh.env_vars["_fastflow_error_message"] == "Exit-Code 1"

    def test_legacy_plaintext_rows_are_still_masked_by_api(
        self, authenticated_client, test_session
    ):
        """Defense-in-Depth für Alt-Zeilen, die vor Migration 041 geschrieben wurden."""
        run = PipelineRun(
            pipeline_name="legacy_pipeline",
            status=RunStatus.SUCCESS,
            log_file="/logs/legacy.log",
            env_vars={"API_KEY": SECRET_VALUE, "_fastflow_retry_count": "1"},
        )
        test_session.add(run)
        test_session.commit()
        test_session.refresh(run)

        response = authenticated_client.get(f"/api/runs/{run.id}")
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["env_vars"]["API_KEY"] == "***"
        assert body["env_vars"]["_fastflow_retry_count"] == "1"
        assert SECRET_VALUE not in json.dumps(body)


# ---------------------------------------------------------------------------
# 8. Scrub-Logik (Spiegel der Alembic-Migration 041)
# ---------------------------------------------------------------------------

class TestScrubPersistedEnvVars:
    def test_mixed_dict_keeps_only_metadata_keys(self):
        scrubbed = scrub_persisted_env_vars(
            {
                "API_KEY": SECRET_VALUE,
                "DB_PASSWORD": "hunter2",
                "LOG_LEVEL": "DEBUG",
                "_fastflow_error_type": "pipeline_error",
                "_fastflow_retry_count": "1",
            }
        )

        assert scrubbed == {
            "_fastflow_error_type": "pipeline_error",
            "_fastflow_retry_count": "1",
        }
        assert SECRET_VALUE not in json.dumps(scrubbed)

    def test_already_clean_dict_is_unchanged(self):
        clean = {"_fastflow_retry_count": "1", "_fastflow_previous_run_id": "x"}

        assert scrub_persisted_env_vars(clean) == clean

    def test_empty_and_none_yield_empty_dict(self):
        assert scrub_persisted_env_vars(None) == {}
        assert scrub_persisted_env_vars({}) == {}

    def test_all_plaintext_dict_becomes_empty(self):
        assert scrub_persisted_env_vars({"API_KEY": SECRET_VALUE}) == {}

    def test_scrub_does_not_mutate_input(self):
        original = {"API_KEY": SECRET_VALUE, "_fastflow_retry_count": "1"}

        scrub_persisted_env_vars(original)

        assert original == {"API_KEY": SECRET_VALUE, "_fastflow_retry_count": "1"}
