"""Tests für Speicher-Statistik und UV-Cache-Hilfsfunktionen."""

import pytest

from app.api.settings import (
    _directory_size_bytes,
    _share_of_own_volume,
    _sync_build_storage_stats_payload,
    _volume_stats,
)
from app.core.config import config


def test_directory_size_bytes_missing_dir(tmp_path):
    assert _directory_size_bytes(tmp_path / "does_not_exist") == 0


def test_directory_size_bytes_empty_dir(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    assert _directory_size_bytes(d) == 0


def test_directory_size_bytes_sums_files(tmp_path):
    d = tmp_path / "cache"
    d.mkdir()
    (d / "a.txt").write_bytes(b"hello")
    sub = d / "sub"
    sub.mkdir()
    (sub / "b.txt").write_bytes(b"xx")
    assert _directory_size_bytes(d) == 5 + 2


# --- Shared Volume ------------------------------------------------------------
#
# "total_disk_space_*" stammt aus shutil.disk_usage(LOGS_DIR), also vom
# fastflow-storage-PVC. Das shared PVC des Kubernetes-Backends ist ein eigenes
# Volume und kam in diesen Statistiken nicht vor — obwohl dort die Pipeline-
# Kopien, der uv-Cache und die Python-Installationen liegen und jeder Run
# scheitert, sobald es volläuft. Die Seite sah dabei gesund aus.


@pytest.fixture
def kubernetes_shared_volume(tmp_path, monkeypatch):
    """Kubernetes-Backend mit einem echten Verzeichnis als shared Volume."""
    mount = tmp_path / "shared"
    mount.mkdir()
    monkeypatch.setattr(config, "PIPELINE_EXECUTOR", "kubernetes")
    monkeypatch.setattr(config, "KUBERNETES_SHARED_CACHE_MOUNT_PATH", str(mount))
    return mount


def test_volume_stats_reports_total_used_and_free(tmp_path):
    stats = _volume_stats(tmp_path)

    assert stats is not None
    assert stats["total_bytes"] > 0
    assert stats["used_bytes"] + stats["free_bytes"] <= stats["total_bytes"]
    assert 0.0 <= stats["used_percent"] <= 100.0


def test_volume_stats_returns_none_for_a_missing_mount(tmp_path):
    """Kein gemountetes Volume darf die ganze Statistik nicht kippen."""
    assert _volume_stats(tmp_path / "nicht-gemountet") is None


def test_payload_contains_the_shared_volume(kubernetes_shared_volume):
    payload = _sync_build_storage_stats_payload(0)

    assert payload["shared_volume_dir"] == str(kubernetes_shared_volume)
    assert payload["shared_volume_total_gb"] > 0
    assert "shared_volume_free_gb" in payload
    assert "shared_volume_used_percent" in payload


def test_payload_omits_the_shared_volume_without_kubernetes(tmp_path, monkeypatch):
    """Im Docker-Betrieb gibt es kein shared Volume, über das zu berichten wäre."""
    monkeypatch.setattr(config, "PIPELINE_EXECUTOR", "docker")
    monkeypatch.setattr(config, "KUBERNETES_SHARED_CACHE_MOUNT_PATH", str(tmp_path))

    payload = _sync_build_storage_stats_payload(0)

    assert not [key for key in payload if key.startswith("shared_volume")]


def test_payload_omits_the_shared_volume_when_not_mounted(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PIPELINE_EXECUTOR", "kubernetes")
    monkeypatch.setattr(
        config, "KUBERNETES_SHARED_CACHE_MOUNT_PATH", str(tmp_path / "nicht-gemountet")
    )

    payload = _sync_build_storage_stats_payload(0)

    assert not [key for key in payload if key.startswith("shared_volume")]


def test_share_is_measured_against_the_own_volume(tmp_path):
    """
    Der uv-Anteil lief gegen den Gesamtspeicher des Log-Volumes.

    Im Kubernetes-Betrieb liegt UV_CACHE_DIR auf dem shared PVC, also auf einem
    anderen Volume — gegen den falschen Nenner gerechnet konnte ein voller Cache
    als harmlose Prozentzahl erscheinen. Der Anteil muss sich auf das Volume
    beziehen, auf dem das Verzeichnis liegt.
    """
    volume = _volume_stats(tmp_path)
    assert volume is not None
    groesse = volume["total_bytes"] // 4

    anteil = _share_of_own_volume(tmp_path, groesse)

    assert anteil == pytest.approx(25.0, abs=0.5)


def test_share_is_zero_for_an_empty_directory(tmp_path):
    assert _share_of_own_volume(tmp_path, 0) == 0.0
