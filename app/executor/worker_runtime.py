"""
Shared runtime paths and security settings for pipeline worker containers.

Used by Docker and Kubernetes executors so worker env, mounts, and UID/GID
stay aligned with readOnlyRootFilesystem + non-root policies.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

WORKER_UID = 1001
WORKER_GID = 1001

WORKER_APP_MOUNT = "/app"
WORKER_UV_CACHE_DIR = "/cache/uv"
WORKER_UV_PYTHON_DIR = "/cache/uv_python"
WORKER_TMP_DIR = "/tmp"
WORKER_ROUTE_FILE = f"{WORKER_TMP_DIR}/.fastflow_route"

# Orchestrator on K8s: cache-PVC mounted at /shared (same PVC subdirs as worker jobs).
K8S_SHARED_CACHE_MOUNT = "/shared"
K8S_ORCHESTRATOR_UV_CACHE_DIR = f"{K8S_SHARED_CACHE_MOUNT}/uv_cache"
K8S_ORCHESTRATOR_UV_PYTHON_DIR = f"{K8S_SHARED_CACHE_MOUNT}/uv_python"

WORKER_SECCOMP_PROFILE_TYPE = "RuntimeDefault"

WORKER_BASE_ENV: Dict[str, str] = {
    "UV_CACHE_DIR": WORKER_UV_CACHE_DIR,
    "UV_PYTHON_INSTALL_DIR": WORKER_UV_PYTHON_DIR,
    "UV_LINK_MODE": "copy",
    "PYTHONUNBUFFERED": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
    "HOME": WORKER_TMP_DIR,
    "TMPDIR": WORKER_TMP_DIR,
}


class WorkerSecuritySpec(TypedDict):
    run_as_non_root: bool
    run_as_user: int
    run_as_group: int
    read_only_root_filesystem: bool
    allow_privilege_escalation: bool
    capabilities_drop: List[str]
    seccomp_profile_type: str


class WorkerVolumeMountSpec(TypedDict):
    name: str
    mount_path: str
    sub_path: Optional[str]
    read_only: bool


def worker_container_user() -> str:
    return f"{WORKER_UID}:{WORKER_GID}"


def worker_base_env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env = {
        **WORKER_BASE_ENV,
        "FASTFLOW_ROUTE_FILE": WORKER_ROUTE_FILE,
    }
    if extra:
        env.update(extra)
    return env


def worker_security_spec() -> WorkerSecuritySpec:
    return {
        "run_as_non_root": True,
        "run_as_user": WORKER_UID,
        "run_as_group": WORKER_GID,
        "read_only_root_filesystem": True,
        "allow_privilege_escalation": False,
        "capabilities_drop": ["ALL"],
        "seccomp_profile_type": WORKER_SECCOMP_PROFILE_TYPE,
    }


def k8s_worker_volume_mount_specs(sub_path_run: str) -> List[WorkerVolumeMountSpec]:
    """Writable mounts required when the container root filesystem is read-only."""
    return [
        {
            "name": "cache",
            "mount_path": WORKER_APP_MOUNT,
            "sub_path": sub_path_run,
            "read_only": False,
        },
        {
            "name": "cache",
            "mount_path": WORKER_UV_CACHE_DIR,
            "sub_path": "uv_cache",
            "read_only": False,
        },
        {
            "name": "cache",
            "mount_path": WORKER_UV_PYTHON_DIR,
            "sub_path": "uv_python",
            "read_only": False,
        },
        {
            "name": "tmp",
            "mount_path": WORKER_TMP_DIR,
            "sub_path": None,
            "read_only": False,
        },
    ]


def k8s_cache_subpath_for_orchestrator_path(path: str) -> str:
    """
    Maps orchestrator paths under /shared to the PVC subPath used by worker jobs.

    Example: /shared/uv_cache -> uv_cache (worker mount /cache/uv).
    """
    prefix = f"{K8S_SHARED_CACHE_MOUNT}/"
    if not path.startswith(prefix):
        raise ValueError(f"Expected path under {K8S_SHARED_CACHE_MOUNT}: {path}")
    sub = path[len(prefix) :]
    worker_mounts = k8s_worker_volume_mount_specs("pipeline_runs/example")
    for mount in worker_mounts:
        if mount["sub_path"] == sub:
            return sub
    raise ValueError(f"No worker mount for orchestrator cache path: {path}")


def orchestrator_uv_cache_matches_worker_pvc() -> bool:
    """True when K8s orchestrator UV dirs use the same PVC subdirs as worker jobs."""
    return (
        k8s_cache_subpath_for_orchestrator_path(K8S_ORCHESTRATOR_UV_CACHE_DIR) == "uv_cache"
        and k8s_cache_subpath_for_orchestrator_path(K8S_ORCHESTRATOR_UV_PYTHON_DIR)
        == "uv_python"
    )


def build_k8s_container_security_context(client: Any) -> Any:
    """Build kubernetes.client.V1SecurityContext for hardened worker containers."""
    spec = worker_security_spec()
    return client.V1SecurityContext(
        run_as_non_root=spec["run_as_non_root"],
        run_as_user=spec["run_as_user"],
        run_as_group=spec["run_as_group"],
        read_only_root_filesystem=spec["read_only_root_filesystem"],
        allow_privilege_escalation=spec["allow_privilege_escalation"],
        capabilities=client.V1Capabilities(drop=spec["capabilities_drop"]),
        seccomp_profile=client.V1SeccompProfile(type=spec["seccomp_profile_type"]),
    )


def build_k8s_pod_security_context(client: Any) -> Any:
    """Build kubernetes.client.V1PodSecurityContext for hardened worker pods."""
    spec = worker_security_spec()
    return client.V1PodSecurityContext(
        run_as_non_root=spec["run_as_non_root"],
        run_as_user=spec["run_as_user"],
        run_as_group=spec["run_as_group"],
        fs_group=spec["run_as_group"],
        seccomp_profile=client.V1SeccompProfile(type=spec["seccomp_profile_type"]),
    )
