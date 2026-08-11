"""Security and K8s alignment tests for hardened worker/orchestrator runtimes."""

import json
import os
from pathlib import Path
from uuid import UUID

import pytest
import yaml
from kubernetes import client

from app.core.config import config as app_config
from app.executor import kubernetes_backend as k8s
from app.executor.worker_runtime import (
    K8S_ORCHESTRATOR_UV_CACHE_DIR,
    K8S_ORCHESTRATOR_UV_PYTHON_DIR,
    K8S_WORKER_AUTOMOUNT_SERVICE_ACCOUNT_TOKEN,
    WORKER_BASE_ENV,
    WORKER_ROUTE_FILE,
    WORKER_SECCOMP_PROFILE_TYPE,
    WORKER_UID,
    WORKER_UV_CACHE_DIR,
    WORKER_UV_PYTHON_DIR,
    build_k8s_container_security_context,
    build_k8s_pod_security_context,
    k8s_worker_volume_mount_specs,
    orchestrator_uv_cache_matches_worker_pvc,
    worker_base_env,
    worker_container_user,
    worker_security_spec,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
K8S_DEPLOYMENT = REPO_ROOT / "k8s" / "deployment.yaml"
K8S_RBAC = REPO_ROOT / "k8s" / "rbac-kubernetes-executor.yaml"

RUNNER_SERVICE_ACCOUNT = "fastflow-runner"
EXECUTOR_SERVICE_ACCOUNT = "fastflow-executor"


def _build_pipeline_job(**overrides):
    """A pipeline job spec exactly as run_container_task builds it."""
    run_id = UUID("11111111-2222-3333-4444-555555555555")
    kwargs = {
        "job_name": "ff-demo-11111111",
        "run_id": run_id,
        "pipeline_name": "demo",
        "command": ["sh", "-c", "true"],
        "container_env": [],
        "sub_path_run": f"pipeline_runs/{run_id}",
        "pvc_name": "fastflow-cache-pvc",
        "resources": {},
        "ttl_seconds_after_finished": 300,
        "active_deadline_seconds": None,
    }
    kwargs.update(overrides)
    return k8s.build_pipeline_job(**kwargs)


def _rbac_docs():
    return [d for d in yaml.safe_load_all(K8S_RBAC.read_text(encoding="utf-8")) if d]


def _rbac_doc(kind: str, name: str) -> dict:
    matches = [
        d for d in _rbac_docs() if d.get("kind") == kind and d["metadata"].get("name") == name
    ]
    assert len(matches) == 1, f"Expected exactly one {kind}/{name} in {K8S_RBAC.name}"
    return matches[0]


def test_worker_paths_do_not_use_root():
    assert "/root" not in WORKER_UV_CACHE_DIR
    assert "/root" not in WORKER_ROUTE_FILE


def test_worker_base_env_includes_home_and_route_file():
    env = worker_base_env({"PIPELINE": "demo"})
    assert env["FASTFLOW_ROUTE_FILE"] == WORKER_ROUTE_FILE
    assert env["HOME"] == "/tmp"
    assert env["TMPDIR"] == "/tmp"
    assert env["PIPELINE"] == "demo"
    assert env["UV_CACHE_DIR"] == WORKER_BASE_ENV["UV_CACHE_DIR"]


def test_worker_container_user_matches_uid():
    assert worker_container_user() == f"{WORKER_UID}:{WORKER_UID}"


def test_worker_security_spec_hardened():
    spec = worker_security_spec()
    assert spec["run_as_non_root"] is True
    assert spec["read_only_root_filesystem"] is True
    assert spec["allow_privilege_escalation"] is False
    assert spec["capabilities_drop"] == ["ALL"]
    assert spec["seccomp_profile_type"] == WORKER_SECCOMP_PROFILE_TYPE


def test_k8s_worker_mounts_cover_writable_paths():
    mounts = k8s_worker_volume_mount_specs("pipeline_runs/00000000-0000-0000-0000-000000000001")
    paths = {m["mount_path"] for m in mounts}
    assert paths == {"/app", "/cache/uv", "/cache/uv_python", "/tmp"}
    assert all(m["read_only"] is False for m in mounts)


def test_orchestrator_and_worker_share_uv_cache_pvc_subdirs():
    assert orchestrator_uv_cache_matches_worker_pvc()
    assert K8S_ORCHESTRATOR_UV_CACHE_DIR == "/shared/uv_cache"
    assert K8S_ORCHESTRATOR_UV_PYTHON_DIR == "/shared/uv_python"
    assert WORKER_UV_CACHE_DIR == "/cache/uv"
    assert WORKER_UV_PYTHON_DIR == "/cache/uv_python"


def test_k8s_deployment_manifest_aligns_uv_cache_with_workers():
    content = K8S_DEPLOYMENT.read_text(encoding="utf-8")
    assert "value: /shared/uv_cache" in content
    assert "value: /shared/uv_python" in content
    assert "readOnlyRootFilesystem: true" in content
    assert "type: RuntimeDefault" in content
    assert "runAsNonRoot: true" in content


def test_k8s_security_context_builders_set_seccomp():
    container_ctx = build_k8s_container_security_context(client)
    pod_ctx = build_k8s_pod_security_context(client)
    assert container_ctx.read_only_root_filesystem is True
    assert container_ctx.seccomp_profile.type == "RuntimeDefault"
    assert pod_ctx.seccomp_profile.type == "RuntimeDefault"
    assert pod_ctx.fs_group == WORKER_UID


def test_docker_worker_config_expectations():
    """Document Docker executor hardening flags checked in core.py."""
    from app.executor import core as executor_core

    source = Path(executor_core.__file__).read_text(encoding="utf-8")
    assert '"read_only": True' in source
    assert '"user": worker_container_user()' in source
    assert '"/tmp": "size=64m"' in source


# ---------------------------------------------------------------------------
# Pipeline pods must never carry a ServiceAccount token
# ---------------------------------------------------------------------------

def test_pipeline_pod_never_automounts_a_service_account_token():
    """
    The pod runs arbitrary user pipeline code. Without this flag the kubelet mounts
    the namespace's `default` SA token at /var/run/secrets/kubernetes.io/serviceaccount,
    handing that code an ambient cluster credential — and wherever roles are bound to
    `system:serviceaccounts`, it reads other runs' env Secrets and `fastflow-secrets`
    (master Fernet key, JWT secret).
    """
    pod_spec = _build_pipeline_job().spec.template.spec

    assert pod_spec.automount_service_account_token is False
    assert K8S_WORKER_AUTOMOUNT_SERVICE_ACCOUNT_TOKEN is False


def test_serialized_job_disables_the_token_mount():
    """`false` must survive serialization — a dropped/None field means "mount it"."""
    job_json = json.loads(
        json.dumps(client.ApiClient().sanitize_for_serialization(_build_pipeline_job()))
    )

    assert job_json["spec"]["template"]["spec"]["automountServiceAccountToken"] is False


@pytest.mark.parametrize(
    "configured,expected",
    [(None, None), ("", None), ("   ", None), (RUNNER_SERVICE_ACCOUNT, RUNNER_SERVICE_ACCOUNT)],
)
def test_service_account_name_is_only_set_when_configured(configured, expected):
    """
    Unset means "inherit the namespace `default` SA" (still tokenless). A name that
    does not exist in the namespace makes the SA admission plugin refuse the pod: the
    Job would never get one, and _wait_for_job_completion polls without a deadline
    when CONTAINER_TIMEOUT is unset — the run would hang in RUNNING forever.
    """
    pod_spec = _build_pipeline_job(service_account_name=configured).spec.template.spec

    assert pod_spec.service_account_name == expected
    # Token stays off either way — the SA choice is defense in depth, not the fix.
    assert pod_spec.automount_service_account_token is False


@pytest.mark.skipif(
    "KUBERNETES_JOB_SERVICE_ACCOUNT" in os.environ,
    reason="explicitly configured in this environment",
)
def test_job_service_account_is_opt_in():
    """Defaulting to fastflow-runner would break installs that never applied it."""
    assert app_config.KUBERNETES_JOB_SERVICE_ACCOUNT == ""


def test_run_container_task_passes_the_configured_service_account():
    """The builder is only reachable through this one call site."""
    source = Path(k8s.__file__).read_text(encoding="utf-8")

    assert "service_account_name=app_config.KUBERNETES_JOB_SERVICE_ACCOUNT," in source
    assert (
        "automount_service_account_token=K8S_WORKER_AUTOMOUNT_SERVICE_ACCOUNT_TOKEN," in source
    )


def test_runner_service_account_manifest_grants_nothing():
    runner = _rbac_doc("ServiceAccount", RUNNER_SERVICE_ACCOUNT)

    assert runner.get("automountServiceAccountToken") is False
    bound = {
        (s.get("kind"), s.get("name"))
        for doc in _rbac_docs()
        if doc.get("kind") in ("RoleBinding", "ClusterRoleBinding")
        for s in doc.get("subjects") or []
    }
    assert ("ServiceAccount", RUNNER_SERVICE_ACCOUNT) not in bound


# ---------------------------------------------------------------------------
# RoleBinding: subject namespace is the trap in `kubectl apply -n <other>`
# ---------------------------------------------------------------------------

def test_rolebinding_subject_matches_the_service_account_and_role_it_binds():
    """
    A typo in either reference is silent: the binding resolves to nothing and every
    Job/Secret create returns 403 (runs end as `infrastructure_error`).
    """
    binding = _rbac_doc("RoleBinding", "fastflow-executor-rolebinding")
    role = _rbac_doc("Role", "fastflow-executor-role")
    _rbac_doc("ServiceAccount", EXECUTOR_SERVICE_ACCOUNT)

    assert binding["roleRef"] == {
        "apiGroup": "rbac.authorization.k8s.io",
        "kind": "Role",
        "name": role["metadata"]["name"],
    }
    assert binding["subjects"] == [
        {
            "kind": "ServiceAccount",
            "name": EXECUTOR_SERVICE_ACCOUNT,
            # Stays `default` on purpose: changing it would break every existing
            # install. RBAC requires an explicit namespace for ServiceAccount
            # subjects, so a non-default namespace has to rewrite it before apply.
            "namespace": "default",
        }
    ]


def test_rbac_manifest_documents_the_namespace_rewrite():
    """
    Tripwire for the failure mode `.trivyignore` (KSV-0110) used to wave through:
    `kubectl apply -n <ns>` moves SA/Role/RoleBinding but leaves the subject on
    `default`, so nothing is bound and every run fails with 403.
    """
    content = K8S_RBAC.read_text(encoding="utf-8")

    assert "kubectl apply -n" in content
    assert "sed" in content and "kustomize" in content
    assert "auth can-i" in content


def test_trivyignore_ksv0110_no_longer_claims_apply_n_is_enough():
    content = (REPO_ROOT / ".trivyignore").read_text(encoding="utf-8")
    # The commented justification, i.e. everything between "# KSV-0110" and the
    # bare "KSV-0110" line that actually waives the check.
    justification = content.split("# KSV-0110")[1].split("\nKSV-0110")[0]

    assert "RoleBinding" in justification
    assert "403" in justification
