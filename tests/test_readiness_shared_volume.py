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

import logging
from types import SimpleNamespace

import pytest

from app.core import readiness
from app.core.config import config


@pytest.fixture(autouse=True)
def _reset_alert_throttle(monkeypatch):
    """Der Drossel-Zustand lebt im Modul — sonst hinge ein Test am Vorgänger."""
    monkeypatch.setattr(readiness, "_shared_cache_last_logged", None)


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


def _patch_statvfs(monkeypatch, f_files, f_favail):
    """
    Überschreibt nur die Inode-Felder von os.statvfs.

    Die Block-Felder bleiben echt, weil ``shutil.disk_usage`` auf POSIX
    dasselbe ``os.statvfs`` benutzt — ein vollständig erfundener Rückgabewert
    risse den Disk-Check mit um.
    """
    real = readiness.os.statvfs

    def _statvfs(path):
        st = real(path)
        fields = {name: getattr(st, name) for name in dir(st) if name.startswith("f_")}
        fields.update(f_files=f_files, f_ffree=f_favail, f_favail=f_favail)
        return SimpleNamespace(**fields)

    monkeypatch.setattr(readiness.os, "statvfs", _statvfs)


def test_a_filesystem_without_inode_accounting_is_not_an_alarm(monkeypatch, shared_mount):
    """
    btrfs, ZFS und etliche NFS-Server vergeben Inodes dynamisch und melden 0.

    Genau diese Sorte Speicher trägt üblicherweise ein RWX-Volume. Gelesen als
    "0 Inodes frei" stünde der Check dort dauerhaft auf kritisch — ein
    Daueralarm, der dem echten Befund die Aufmerksamkeit nimmt.
    """
    _patch_disk_usage(monkeypatch, {shared_mount: 4.0})
    _patch_statvfs(monkeypatch, f_files=0, f_favail=0)
    checks = {}

    readiness._check_shared_cache(checks)

    assert checks["shared_cache"] == "ok"
    assert checks["shared_cache_inodes"].startswith("n/a")
    assert "shared_cache_inode_free" not in checks


def test_real_inode_exhaustion_is_still_reported(monkeypatch, shared_mount):
    """Die Gegenprobe: gemeldete Inode-Zahlen werden weiterhin ausgewertet."""
    _patch_disk_usage(monkeypatch, {shared_mount: 4.0})
    _patch_statvfs(monkeypatch, f_files=1_000_000, f_favail=12)
    checks = {}

    readiness._check_shared_cache(checks)

    assert checks["shared_cache"].startswith("kritisch")
    assert "12 Inodes frei" in checks["shared_cache"]


def test_data_dir_without_inode_accounting_keeps_the_pod_ready(monkeypatch):
    """
    Derselbe Fall auf DATA_DIR — dort wiegt er schwerer.

    Dieser Check gated: Ein aus f_files == 0 abgeleitetes "0 Inodes frei" nähme
    den Pod dauerhaft aus dem Service, ohne dass ihm etwas fehlt.
    """
    monkeypatch.setattr(config, "PIPELINE_EXECUTOR", "docker")
    monkeypatch.setattr(
        "app.executor._get_docker_client", lambda: None, raising=False
    )
    _patch_statvfs(monkeypatch, f_files=0, f_favail=0)

    checks, ok = readiness.run_readiness_checks()

    assert checks["inodes"].startswith("n/a")
    assert ok is True


def test_the_alarm_is_logged_once_per_interval_not_once_per_probe(
    monkeypatch, shared_mount, caplog
):
    """
    Die Probe läuft alle 10 Sekunden, der Zustand löst sich nicht von selbst.

    Ein ERROR je Probe wären über 8000 Zeilen am Tag — geschrieben ausgerechnet
    auf das Volume, das noch Platz hat. Der Zustand steht durchgehend in checks
    und in der Gauge; das Log bekommt nur die Erinnerung.
    """
    _patch_disk_usage(monkeypatch, {shared_mount: 0.0})

    with caplog.at_level(logging.ERROR, logger="app.core.readiness"):
        for _ in range(5):
            checks = {}
            readiness._check_shared_cache(checks)

    assert checks["shared_cache"].startswith("kritisch")
    assert len([r for r in caplog.records if "Shared-Volume" in r.getMessage()]) == 1


def test_the_alarm_returns_after_the_interval(monkeypatch, shared_mount, caplog):
    """Nach Ablauf des Intervalls erinnert der Check wieder."""
    _patch_disk_usage(monkeypatch, {shared_mount: 0.0})
    clock = [1000.0]
    monkeypatch.setattr(readiness.time, "monotonic", lambda: clock[0])

    with caplog.at_level(logging.ERROR, logger="app.core.readiness"):
        readiness._check_shared_cache({})
        clock[0] += readiness._SHARED_CACHE_LOG_INTERVAL_SECONDS + 1
        readiness._check_shared_cache({})

    assert len([r for r in caplog.records if "Shared-Volume" in r.getMessage()]) == 2

