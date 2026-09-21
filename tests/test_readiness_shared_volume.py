"""
Tests für den Shared-Volume-Check der Readiness.

Das shared Volume des Kubernetes-Backends liegt auf einem eigenen PVC
(k8s/deployment.yaml: cache-pvc auf /shared), nicht auf dem Volume von DATA_DIR.
Der Disk-Check der Readiness sah nur DATA_DIR — lief /shared voll, scheiterte
jeder Run in ``_copy_pipeline_to_shared`` mit ENOSPC, während ``/ready`` und
``/health`` durchgehend 200 lieferten — rote Runs hinter grünen Probes, ohne
dass eine Probe oder ein Alert davon wusste.

Der Check meldet deshalb, gated aber nicht: Bei ``replicas: 1`` nähme ein
NotReady den einzigen Pod aus dem Service und schaltete die UI ab, über die man
den Zustand sieht — ohne dass der Pod davon heilt. Dass ``ok`` unberührt bleibt,
ist damit Teil des Vertrags und steht hier als Test.
"""

from types import SimpleNamespace

import pytest

from app.core import readiness
from app.core.config import config


@pytest.fixture
def shared_mount(tmp_path, monkeypatch):
    """Ein echtes Verzeichnis als shared Volume (statvfs braucht einen gültigen Pfad)."""
    mount = tmp_path / "shared"
    mount.mkdir()
    monkeypatch.setattr(config, "KUBERNETES_SHARED_CACHE_MOUNT_PATH", str(mount))
    return mount


def _patch_disk_usage(monkeypatch, free_by_path):
    """Lässt shutil.disk_usage für bestimmte Pfade einen festen Wert melden."""
    real = readiness.shutil.disk_usage

    def _usage(path):
        for prefix, free_gb in free_by_path.items():
            if str(path) == str(prefix):
                total = 10 * 1024 ** 3
                free = int(free_gb * 1024 ** 3)
                return SimpleNamespace(total=total, used=total - free, free=free)
        return real(path)

    monkeypatch.setattr(readiness.shutil, "disk_usage", _usage)


def test_full_shared_volume_is_reported(monkeypatch, shared_mount):
    checks = {}
    _patch_disk_usage(monkeypatch, {shared_mount: 0.02})

    readiness._check_shared_cache(checks)

    assert checks["shared_cache"].startswith("kritisch")
    assert checks["shared_cache_free_gb"] == 0.02


def test_shared_volume_with_headroom_is_ok(monkeypatch, shared_mount):
    checks = {}
    _patch_disk_usage(monkeypatch, {shared_mount: 4.0})

    readiness._check_shared_cache(checks)

    assert checks["shared_cache"] == "ok"
    assert checks["shared_cache_free_gb"] == 4.0


def test_unreadable_shared_volume_is_reported(tmp_path, monkeypatch):
    """Nicht gemountetes Volume: Meldung statt Exception aus run_readiness_checks."""
    monkeypatch.setattr(
        config, "KUBERNETES_SHARED_CACHE_MOUNT_PATH", str(tmp_path / "nicht-gemountet")
    )
    checks = {}

    readiness._check_shared_cache(checks)

    assert checks["shared_cache"] != "ok"
    assert "shared_cache_free_gb" not in checks


def test_full_shared_volume_keeps_the_probe_ready(monkeypatch, shared_mount):
    """
    Der Kern der Entscheidung: gemeldet wird, gegated nicht.

    Alles andere ist hier gesund; allein das volle shared Volume darf ``ok``
    nicht kippen, sonst nimmt Kubernetes den einzigen Pod aus dem Service.
    """
    monkeypatch.setattr(config, "PIPELINE_EXECUTOR", "kubernetes")
    monkeypatch.setattr(
        "app.executor.kubernetes_backend._get_apis", lambda: (object(), object())
    )
    _patch_disk_usage(monkeypatch, {shared_mount: 0.0})

    checks, ok = readiness.run_readiness_checks()

    assert checks["shared_cache"].startswith("kritisch")
    assert ok is True
    # Der DATA_DIR-Check bleibt unberührt — er beschreibt ein anderes Volume.
    assert checks["disk"] == "ok"


def test_docker_executor_skips_the_shared_volume_check(monkeypatch, shared_mount):
    """Ohne Kubernetes-Backend gibt es kein shared Volume, über das zu reden wäre."""
    monkeypatch.setattr(config, "PIPELINE_EXECUTOR", "docker")
    _patch_disk_usage(monkeypatch, {shared_mount: 0.0})

    checks, _ = readiness.run_readiness_checks()

    assert "shared_cache" not in checks
