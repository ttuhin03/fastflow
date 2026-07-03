"""Security and K8s alignment tests for hardened worker/orchestrator runtimes."""

from pathlib import Path

from kubernetes import client

from app.executor.worker_runtime import (
    K8S_ORCHESTRATOR_UV_CACHE_DIR,
    K8S_ORCHESTRATOR_UV_PYTHON_DIR,
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
