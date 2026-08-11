"""
Regression-Tests für die Env-Injektion des Kubernetes-Executors.

Vor dem Fix schrieb ``app/executor/kubernetes_backend.py`` den vollständig gemergten,
ENTSCHLÜSSELTEN Env-Satz als Literale in die Job-Spec::

    container_env = [client.V1EnvVar(name=k, value=str(v)) for k, v in base_env.items()]

Damit lagen Klartext-Credentials im etcd, in ``kubectl describe job`` UND im
API-Audit-Log. Die eingebaute ``view``-ClusterRole erlaubt get/list auf Jobs und Pods,
aber NICHT auf Secrets, und Encryption-at-Rest (EncryptionConfiguration) deckt
typischerweise nur ``secrets`` ab: Klartext in der Job-Spec hebelt also genau die
Kontrollen aus, die der Cluster-Betreiber für aktiv hält. Jeder mit ``view`` konnte
live Kunden-API-Keys lesen.

Getestet wird:
- die Invariante (kein Env-Wert im serialisierten Job, nur ``secretKeyRef``)
- explizites ``env``/``secretKeyRef`` statt ``envFrom`` (Präzedenz + kein stilles Drop)
- die Secret-Namensableitung aus der vollen run_id (nicht aus dem gekürzten job_name)
- Key-Validierung, die VOR jedem API-Aufruf und ohne Werte in der Meldung scheitert
- die Reihenfolge Secret-vor-Job und das Aufräumen, wenn der Job-Create scheitert
- die Verb-Menge der Role (positiv UND negativ, als Tripwire gegen Aufweiten)

``kubernetes_backend`` hatte bisher keine Testabdeckung; die Mocks setzen deshalb an
den modulglobalen API-Handles an (nicht an ``_get_apis`` selbst), damit dessen
Initialisierungs-Guard mitgetestet wird.
"""

import asyncio
import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
import yaml
from kubernetes import client
from kubernetes.client.rest import ApiException

from app.core.config import config as app_config
from app.executor import core as executor_core
from app.executor import kubernetes_backend as k8s
from app.models import PipelineRun, RunStatus

REPO_ROOT = Path(__file__).resolve().parents[1]
RBAC_MANIFEST = REPO_ROOT / "k8s" / "rbac-kubernetes-executor.yaml"
TRIVYIGNORE = REPO_ROOT / ".trivyignore"

# Unverwechselbarer Literal-Wert: macht den Substring-Check auf dem serialisierten
# Job aussagekräftig.
SECRET_VALUE = "sk-live-DO-NOT-PUT-ME-IN-A-JOB-SPEC-4711"
RUN_ID = UUID("11111111-2222-3333-4444-555555555555")


def _serialize(obj) -> str:
    """Serialisiert ein K8s-Objekt genau so, wie es an den API-Server geht."""
    return json.dumps(client.ApiClient().sanitize_for_serialization(obj))


def _build_job(container_env) -> object:
    return k8s.build_pipeline_job(
        job_name="ff-demo-11111111",
        run_id=RUN_ID,
        pipeline_name="demo",
        command=["sh", "-c", "true"],
        container_env=container_env,
        sub_path_run=f"pipeline_runs/{RUN_ID}",
        pvc_name="fastflow-cache-pvc",
        resources={},
        ttl_seconds_after_finished=300,
        active_deadline_seconds=None,
    )


@pytest.fixture
def k8s_apis(monkeypatch):
    """
    Mockt die modulglobalen API-Handles.

    Ein gemeinsames Parent-Mock, damit ``mock_calls`` die Aufrufe von Batch- und
    Core-API in ihrer tatsächlichen Reihenfolge enthält (Secret vor Job).
    """
    api = MagicMock()
    monkeypatch.setattr(k8s, "_batch_api", api.batch)
    monkeypatch.setattr(k8s, "_core_api", api.core)
    monkeypatch.setattr(k8s, "_initialized", True)
    monkeypatch.setattr(app_config, "KUBERNETES_NAMESPACE", "fastflow-test")
    return api


# ---------------------------------------------------------------------------
# Die Kern-Invariante: keine Env-Werte in der Job-Spec
# ---------------------------------------------------------------------------

def test_job_spec_contains_no_literal_env_value():
    env = {"API_KEY": SECRET_VALUE, "HOME": "/tmp"}
    secret_name = k8s.run_env_secret_name(RUN_ID)

    job_json = _serialize(_build_job(k8s.build_container_env(env, secret_name)))

    assert SECRET_VALUE not in job_json
    assert secret_name in job_json
    assert "secretKeyRef" in job_json


def test_job_spec_references_every_key_explicitly_and_never_uses_env_from():
    env = {"API_KEY": SECRET_VALUE, "HOME": "/tmp", "UV_LINK_MODE": "copy"}
    secret_name = k8s.run_env_secret_name(RUN_ID)

    job = _build_job(k8s.build_container_env(env, secret_name))
    container = job.spec.template.spec.containers[0]

    # envFrom würde (a) die Präzedenz invertieren (env gewinnt in K8s über envFrom,
    # während worker_base_env() den Aufrufer gewinnen lässt) und (b) Keys mit
    # ungültigem Env-Var-Namen im Kubelet still fallen lassen.
    assert getattr(container, "env_from", None) is None
    assert [e.name for e in container.env] == list(env)
    for entry in container.env:
        assert entry.value is None
        assert entry.value_from.secret_key_ref.name == secret_name
        assert entry.value_from.secret_key_ref.key == entry.name


def test_container_env_keeps_caller_override_of_base_env():
    """
    Präzedenz-Regression: ``worker_base_env()`` macht ``env.update(extra)``, der
    Aufrufer überschreibt also HOME/TMPDIR/UV_*. Mit ``envFrom`` hätte der
    statische ``env``-Eintrag gewonnen und die Pipeline still wieder /tmp bekommen.
    """
    from app.executor.worker_runtime import worker_base_env

    env = worker_base_env({"HOME": "/app/custom-home"})
    secret = k8s.build_run_env_secret(RUN_ID, "demo", env)

    assert secret.string_data["HOME"] == "/app/custom-home"
    names = [e.name for e in k8s.build_container_env(env, "ff-run-env-x")]
    assert names.count("HOME") == 1


def test_secret_carries_the_values_and_coerces_non_strings():
    """default_env/encrypted_env sind unschema'tes JSON – Werte können int/None sein."""
    env = {"API_KEY": SECRET_VALUE, "RETRIES": 3, "UNSET": None}

    secret = k8s.build_run_env_secret(RUN_ID, "demo", env)

    assert secret.string_data == {
        "API_KEY": SECRET_VALUE,
        "RETRIES": "3",
        "UNSET": "None",
    }
    assert secret.type == "Opaque"
    assert secret.metadata.labels[k8s.JOB_LABEL_RUN_ID] == str(RUN_ID)


def test_flag_off_falls_back_to_literal_env():
    """Notausstieg KUBERNETES_ENV_VIA_SECRET=false: altes Verhalten, unverändert."""
    env = {"API_KEY": SECRET_VALUE}

    container_env = k8s.build_container_env(env, None)

    assert container_env[0].name == "API_KEY"
    assert container_env[0].value == SECRET_VALUE
    assert container_env[0].value_from is None
    # Bewusste Gegenprobe: so sah der Befund aus, den dieser Pfad reproduziert.
    assert SECRET_VALUE in _serialize(_build_job(container_env))


# ---------------------------------------------------------------------------
# Secret-Name: aus der vollen run_id, nicht aus dem gekürzten job_name
# ---------------------------------------------------------------------------

def test_secret_name_is_derived_from_full_run_id():
    name = k8s.run_env_secret_name(RUN_ID)

    assert name == f"ff-run-env-{RUN_ID}"
    assert len(name) <= 253
    # DNS-Subdomain: nur Kleinbuchstaben, Ziffern, '-' und '.'
    assert re.match(r"^[a-z0-9]([-a-z0-9.]*[a-z0-9])?$", name)


def test_secret_names_stay_distinct_where_job_names_collide():
    """
    ``f"ff-{slug}-{run_id_short}"[:63]`` kürzt bei langen Pipeline-Slugs die run_id
    weg. Für einen Job ist das ein hässlicher Name – für ein Secret hieße es, dass
    ein Run die Credentials eines anderen überschreibt.
    """
    long_slug = "a" * 70
    run_a, run_b = uuid4(), uuid4()
    job_a = f"ff-{long_slug}-{str(run_a).replace('-', '')[:8]}"[:63]
    job_b = f"ff-{long_slug}-{str(run_b).replace('-', '')[:8]}"[:63]

    assert job_a == job_b, "Vorbedingung: job_name kollidiert bei langen Slugs"
    assert k8s.run_env_secret_name(run_a) != k8s.run_env_secret_name(run_b)


# ---------------------------------------------------------------------------
# Key-Validierung: vor jedem API-Aufruf, ohne Werte in der Meldung
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_key", ["WITH SPACE", "ÄÖÜ", "A=B", "WITH/SLASH", "", ".", ".."])
def test_key_that_no_secret_can_hold_raises(bad_key):
    with pytest.raises(ValueError) as exc:
        k8s.build_run_env_secret(RUN_ID, "demo", {bad_key: SECRET_VALUE})

    assert bad_key in str(exc.value) or bad_key == ""


@pytest.mark.parametrize("key", ["MY-VAR", "MY.VAR", "1ST_VAR", "lower_case", "A1"])
def test_keys_that_are_valid_secret_keys_are_not_rejected_here(key):
    """
    Kein strengerer Filter als die Secret-Regeln: Ob "MY-VAR" als Env-Var-Name
    durchgeht, entscheidet die Cluster-Version – genau wie vor der Umstellung beim
    Job-Create. Eine Prüfung gegen C_IDENTIFIER würde hier Pipelines brechen, die
    heute laufen. Weil das Secret VOR dem Job entsteht, scheitert so ein Key
    sauber am Job-Create und hinterlässt keinen Pod in CreateContainerConfigError.
    """
    secret = k8s.build_run_env_secret(RUN_ID, "demo", {key: SECRET_VALUE})

    assert secret.string_data[key] == SECRET_VALUE


def test_validation_runs_before_any_api_call(k8s_apis):
    with pytest.raises(ValueError):
        k8s.build_run_env_secret(RUN_ID, "demo", {"BAD KEY": SECRET_VALUE})

    assert k8s_apis.mock_calls == []


def test_validation_error_names_keys_but_never_values():
    with pytest.raises(ValueError) as exc:
        k8s.build_run_env_secret(RUN_ID, "demo", {"BAD KEY": SECRET_VALUE, "OK": "x"})

    message = str(exc.value)
    assert "BAD KEY" in message
    # _fastflow_error_message wird von der API unmaskiert ausgeliefert.
    assert SECRET_VALUE not in message


def test_oversized_env_reports_byte_counts_without_values():
    env = {"BIG": SECRET_VALUE + "x" * (1024 * 1024)}

    with pytest.raises(ValueError) as exc:
        k8s.validate_env_keys_for_secret(env)

    message = str(exc.value)
    assert str(1024 * 1024) in message
    assert SECRET_VALUE not in message


def test_overlong_key_reports_length_without_values():
    env = {"K" * 300: SECRET_VALUE}

    with pytest.raises(ValueError) as exc:
        k8s.validate_env_keys_for_secret(env)

    assert "300 Zeichen" in str(exc.value)
    assert SECRET_VALUE not in str(exc.value)


def test_worker_base_env_keys_are_valid_secret_keys():
    """Die statische Basis darf die Validierung nie selbst reißen."""
    from app.executor.worker_runtime import worker_base_env

    k8s.validate_env_keys_for_secret(worker_base_env())


# ---------------------------------------------------------------------------
# Secret-Lebenszyklus gegen die gemockte API
# ---------------------------------------------------------------------------

def test_create_replaces_leftover_secret_on_conflict(k8s_apis):
    secret = k8s.build_run_env_secret(RUN_ID, "demo", {"API_KEY": SECRET_VALUE})
    k8s_apis.core.create_namespaced_secret.side_effect = [
        ApiException(status=409, reason="AlreadyExists"),
        None,
    ]

    k8s._create_run_env_secret("fastflow-test", secret)

    # Delete + Create, kein Patch: ein Merge-Patch würde veraltete Keys stehen lassen.
    k8s_apis.core.delete_namespaced_secret.assert_called_once_with(
        name=secret.metadata.name, namespace="fastflow-test"
    )
    assert k8s_apis.core.create_namespaced_secret.call_count == 2


def test_create_propagates_forbidden(k8s_apis):
    """403 (RBAC nicht ausgerollt) muss hart scheitern – vor dem Job-Create."""
    secret = k8s.build_run_env_secret(RUN_ID, "demo", {"API_KEY": SECRET_VALUE})
    k8s_apis.core.create_namespaced_secret.side_effect = ApiException(
        status=403, reason="Forbidden"
    )

    with pytest.raises(ApiException):
        k8s._create_run_env_secret("fastflow-test", secret)


def test_owner_reference_is_never_patched_without_a_real_uid(k8s_apis):
    """
    Eine erfundene UID liest der Garbage Collector als gelöschten Owner und löscht
    das Secret sofort – der Pod hinge dann in CreateContainerConfigError.
    """
    k8s._patch_run_env_secret_owner("fastflow-test", "ff-run-env-x", "ff-demo", None)

    k8s_apis.core.patch_namespaced_secret.assert_not_called()


def test_owner_reference_patch_sets_job_as_owner(k8s_apis):
    k8s._patch_run_env_secret_owner("fastflow-test", "ff-run-env-x", "ff-demo", "uid-42")

    body = k8s_apis.core.patch_namespaced_secret.call_args.kwargs["body"]
    ref = body["metadata"]["ownerReferences"][0]
    assert ref["kind"] == "Job"
    assert ref["uid"] == "uid-42"
    # blockOwnerDeletion bräuchte `update` auf jobs/finalizers – haben wir nicht.
    assert ref["blockOwnerDeletion"] is False


def test_owner_reference_patch_failure_is_swallowed(k8s_apis):
    """Der ownerRef ist nur ein Backstop – ein Fehler darf keinen Run scheitern lassen."""
    k8s_apis.core.patch_namespaced_secret.side_effect = ApiException(status=403)

    k8s._patch_run_env_secret_owner("fastflow-test", "ff-run-env-x", "ff-demo", "uid-42")


def test_delete_run_env_secret_is_idempotent(k8s_apis, monkeypatch):
    monkeypatch.setattr(app_config, "KUBERNETES_ENV_VIA_SECRET", True)
    k8s_apis.core.delete_namespaced_secret.side_effect = ApiException(status=404)

    assert k8s._delete_run_env_secret(RUN_ID) is False


def test_delete_run_env_secret_uses_deterministic_name(k8s_apis, monkeypatch):
    monkeypatch.setattr(app_config, "KUBERNETES_ENV_VIA_SECRET", True)

    assert k8s._delete_run_env_secret(RUN_ID) is True
    k8s_apis.core.delete_namespaced_secret.assert_called_once_with(
        name=k8s.run_env_secret_name(RUN_ID), namespace="fastflow-test"
    )


def test_startup_sweep_skips_runs_that_still_have_a_job(k8s_apis, monkeypatch, test_session):
    """
    Gate auf Job-Existenz: Ein Pod, dessen Container noch nicht gestartet ist,
    landet ohne sein Secret in CreateContainerConfigError – und weil
    CONTAINER_TIMEOUT per Default None ist, pollt _wait_for_job_completion ohne
    Deadline endlos (Run für immer RUNNING, MAX_CONCURRENT_RUNS-Slot blockiert).
    """
    monkeypatch.setattr(app_config, "KUBERNETES_ENV_VIA_SECRET", True)
    live_run, orphan_run, finished_run = uuid4(), uuid4(), uuid4()
    for run_id, status in (
        (live_run, RunStatus.RUNNING),
        (orphan_run, RunStatus.RUNNING),
        (finished_run, RunStatus.SUCCESS),
    ):
        test_session.add(
            PipelineRun(id=run_id, pipeline_name="demo", status=status, log_file="x.log")
        )
    test_session.commit()

    job = MagicMock()
    job.metadata.labels = {k8s.JOB_LABEL_RUN_ID: str(live_run)}
    k8s_apis.batch.list_namespaced_job.return_value = MagicMock(items=[job])

    deleted = k8s.cleanup_orphaned_run_env_secrets(test_session)

    assert deleted == 1
    deleted_names = {
        call.kwargs["name"] for call in k8s_apis.core.delete_namespaced_secret.call_args_list
    }
    assert deleted_names == {k8s.run_env_secret_name(orphan_run)}


def test_startup_sweep_is_a_noop_when_flag_is_off(k8s_apis, monkeypatch, test_session):
    monkeypatch.setattr(app_config, "KUBERNETES_ENV_VIA_SECRET", False)

    assert k8s.cleanup_orphaned_run_env_secrets(test_session) == 0
    assert k8s_apis.mock_calls == []


# ---------------------------------------------------------------------------
# Reihenfolge im Run-Lebenszyklus: Secret VOR Job, Cleanup bei Job-Fehler
# ---------------------------------------------------------------------------

class _StubMetadata:
    schedules = None
    cpu_hard_limit = None
    mem_hard_limit = None
    retry_attempts = 0
    retry_strategy = None
    secrets = None


class _StubPipeline:
    """Minimal-Ersatz für DiscoveredPipeline (echte Attribute statt Mock-Magie:
    getattr auf einem MagicMock liefert truthy Mocks und verfälscht die Limits)."""

    def __init__(self, path: Path):
        self.name = "demo"
        self.path = path
        self.metadata = _StubMetadata()

    def get_timeout(self):
        return 0

    def get_python_version(self):
        return "3.11"

    def get_entry_type(self):
        return "script"


@pytest.fixture
def run_task_env(monkeypatch, tmp_path, test_session, k8s_apis):
    """Verdrahtet run_container_task so weit, dass nur der Cluster-Teil echt bleibt."""
    monkeypatch.setattr(app_config, "KUBERNETES_ENV_VIA_SECRET", True)
    monkeypatch.setattr(app_config, "KUBERNETES_SHARED_CACHE_MOUNT_PATH", str(tmp_path / "shared"))
    monkeypatch.setattr(app_config, "UV_PRE_HEAT", False)

    run_id = uuid4()
    run = PipelineRun(
        id=run_id,
        pipeline_name="demo",
        status=RunStatus.PENDING,
        log_file=str(tmp_path / "run.log"),
    )
    test_session.add(run)
    test_session.commit()

    def _session_gen():
        yield test_session
    monkeypatch.setattr(k8s, "get_session", _session_gen)

    monkeypatch.setattr(k8s, "_copy_pipeline_to_shared", lambda pipeline, rid: tmp_path)
    monkeypatch.setattr(k8s, "_cleanup_shared_pipeline_run", lambda rid: None)
    monkeypatch.setattr(
        executor_core, "_build_container_command", lambda pipeline: ["sh", "-c", "true"]
    )
    monkeypatch.setattr(executor_core, "_update_pipeline_stats", AsyncMock())
    monkeypatch.setattr(executor_core, "_trigger_downstream_pipelines", AsyncMock())

    import app.git_sync.sync as git_sync
    monkeypatch.setattr(git_sync, "ensure_python_version", lambda v: None)

    async def _fake_stream(rid, ns, job_name, log_path, log_queue, first_log_event, **kwargs):
        first_log_event.set()
        await asyncio.sleep(30)
    monkeypatch.setattr(k8s, "_stream_pod_logs", _fake_stream)

    async def _fake_metrics(*args, **kwargs):
        await asyncio.sleep(30)
    monkeypatch.setattr(k8s, "_emit_placeholder_metrics", _fake_metrics)
    monkeypatch.setattr(k8s, "_wait_for_job_completion", AsyncMock(return_value=(0, False)))

    return {
        "run_id": run_id,
        "pipeline": _StubPipeline(tmp_path),
        "api": k8s_apis,
        "session": test_session,
    }


async def test_secret_is_created_before_the_job(run_task_env):
    """
    Reihenfolge-Invariante. Umgekehrt (Job zuerst, um ownerReferences direkt zu
    setzen) hinge der Pod bei einem 403 auf dem Secret in
    CreateContainerConfigError, und _wait_for_job_completion pollt mit
    deadline=None endlos – der Run bliebe für immer RUNNING.
    """
    env = run_task_env
    await k8s.run_container_task(
        env["run_id"], env["pipeline"], {"API_KEY": SECRET_VALUE}, asyncio.Lock()
    )

    names = [c[0] for c in env["api"].mock_calls]
    assert "core.create_namespaced_secret" in names
    assert "batch.create_namespaced_job" in names
    assert names.index("core.create_namespaced_secret") < names.index(
        "batch.create_namespaced_job"
    )

    job_body = env["api"].batch.create_namespaced_job.call_args.kwargs["body"]
    assert SECRET_VALUE not in _serialize(job_body)
    secret_body = env["api"].core.create_namespaced_secret.call_args.kwargs["body"]
    assert secret_body.string_data["API_KEY"] == SECRET_VALUE


async def test_flag_off_creates_no_secret_and_keeps_the_old_job_spec(run_task_env, monkeypatch):
    """
    Notausstieg für Cluster ohne die neue RBAC. Gleichzeitig die Gegenprobe zum Test
    darüber: Ohne das Flag stünde der Klartext wieder in der Job-Spec.
    """
    monkeypatch.setattr(app_config, "KUBERNETES_ENV_VIA_SECRET", False)
    env = run_task_env

    await k8s.run_container_task(
        env["run_id"], env["pipeline"], {"API_KEY": SECRET_VALUE}, asyncio.Lock()
    )

    env["api"].core.create_namespaced_secret.assert_not_called()
    env["api"].core.delete_namespaced_secret.assert_not_called()
    job_body = env["api"].batch.create_namespaced_job.call_args.kwargs["body"]
    assert SECRET_VALUE in _serialize(job_body)


async def test_secret_is_deleted_when_the_job_create_fails(run_task_env):
    """403 auf dem Job: Der Run scheitert sauber und lässt kein Secret zurück."""
    env = run_task_env
    env["api"].batch.create_namespaced_job.side_effect = ApiException(
        status=403, reason="Forbidden"
    )

    await k8s.run_container_task(
        env["run_id"], env["pipeline"], {"API_KEY": SECRET_VALUE}, asyncio.Lock()
    )

    env["api"].core.delete_namespaced_secret.assert_called_with(
        name=k8s.run_env_secret_name(env["run_id"]), namespace="fastflow-test"
    )
    run = env["session"].get(PipelineRun, env["run_id"])
    assert run.status == RunStatus.FAILED
    assert run.env_vars["_fastflow_error_type"] == "infrastructure_error"
    assert SECRET_VALUE not in run.env_vars["_fastflow_error_message"]


async def test_secret_is_deleted_on_the_success_path(run_task_env):
    """
    Explizites Delete ist der primäre GC-Mechanismus: Auf dem Erfolgspfad wird der
    Job nicht gelöscht, und KUBERNETES_JOB_TTL_SECONDS_AFTER_FINISHED=0 schaltet
    die TTL ganz ab – ein "owned" Secret könnte sonst beliebig lange leben.
    """
    env = run_task_env
    await k8s.run_container_task(
        env["run_id"], env["pipeline"], {"API_KEY": SECRET_VALUE}, asyncio.Lock()
    )

    # Vorbedingung: Der Run ist wirklich durchgelaufen (nicht über den except-Pfad).
    assert env["session"].get(PipelineRun, env["run_id"]).status == RunStatus.SUCCESS
    env["api"].batch.delete_namespaced_job.assert_not_called()
    env["api"].core.delete_namespaced_secret.assert_called_with(
        name=k8s.run_env_secret_name(env["run_id"]), namespace="fastflow-test"
    )


# ---------------------------------------------------------------------------
# Manifest / CI-Konfiguration
# ---------------------------------------------------------------------------

def _rbac_docs():
    return [d for d in yaml.safe_load_all(RBAC_MANIFEST.read_text(encoding="utf-8")) if d]


def _executor_role_rules():
    roles = [d for d in _rbac_docs() if d.get("kind") == "Role"]
    assert len(roles) == 1, "Erwartet genau eine Role im Executor-RBAC-Manifest"
    return roles[0]["rules"]


def test_rbac_role_grants_write_only_access_to_secrets():
    """
    Tripwire: Die Role darf Secrets schreiben, aber nie lesen. Mit get/list käme der
    Orchestrator an `fastflow-secrets` (Master-Fernet-Key) und das Postgres-Secret.
    """
    verbs = set()
    for rule in _executor_role_rules():
        if "secrets" in (rule.get("resources") or []):
            assert rule.get("apiGroups") == [""]
            verbs.update(rule.get("verbs") or [])

    assert verbs == {"create", "patch", "delete"}
    assert not verbs & {"get", "list", "watch", "update", "deletecollection", "*"}


def test_rbac_role_has_no_wildcards():
    for rule in _executor_role_rules():
        assert "*" not in (rule.get("verbs") or [])
        assert "*" not in (rule.get("resources") or [])
        assert "*" not in (rule.get("apiGroups") or [])


def test_secret_rights_stay_namespaced_and_never_become_a_clusterrole():
    """
    Die Verbindung zwischen Manifest und .trivyignore: Für eine namespaced Role
    meldet Trivy KSV-0113 (MEDIUM, eingetragen); dasselbe Recht in einer
    ClusterRole ist KSV-0041 (CRITICAL, absichtlich NICHT eingetragen, damit der
    Config-Scan mit exit-code 1 hart failt).
    """
    kinds = {d.get("kind") for d in _rbac_docs()}

    assert "Role" in kinds
    assert "ClusterRole" not in kinds
    assert "ClusterRoleBinding" not in kinds


def test_trivyignore_justifies_the_secret_management_finding():
    content = TRIVYIGNORE.read_text(encoding="utf-8")

    assert re.search(r"^KSV-0113\s*$", content, re.MULTILINE)
    assert "KUBERNETES_ENV_VIA_SECRET" in content
    # KSV-0041 (ClusterRole, CRITICAL) darf NICHT stummgeschaltet werden – siehe
    # test_secret_rights_stay_namespaced_and_never_become_a_clusterrole.
    assert not re.search(r"^KSV-0041\s*$", content, re.MULTILINE)
    # Die alte KSV-0048-Begründung behauptete "kein exec/secrets" – das stimmt nicht mehr.
    assert "kein exec/secrets" not in content
