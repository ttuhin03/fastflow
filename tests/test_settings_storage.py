"""Tests für Speicher-Statistik und UV-Cache-Hilfsfunktionen."""

import pytest

from app.api.settings import (
    _directory_size_bytes,
    _share_of_own_volume,
    _sync_build_storage_stats_payload,
    _sync_shared_volume_breakdown,
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


# --- Aufschlüsselung des shared Volumes ---------------------------------------
#
# GET /storage sagt, dass das Volume voll ist, aber nicht wovon. Die Antwort
# darauf lag bisher nur in einem `du -xsh /shared/*` im Pod — also hinter
# Cluster-Zugriff, und der fehlt ausgerechnet dann, wenn das Volume vollläuft und
# niemand mit kubectl greifbar ist. Deshalb ein eigener Endpoint: teuer genug, um
# nicht ins 30-Sekunden-Polling von /storage zu gehören, aber auf Abruf da.


def _fuelle(mount, pfade: dict):
    """Legt Dateien mit definierter Grösse an: {'uv_cache/archive-v0/a': 100, …}."""
    for rel, groesse in pfade.items():
        ziel = mount / rel
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(b"x" * groesse)


def test_breakdown_sorts_by_size_and_nests_one_level(kubernetes_shared_volume):
    _fuelle(kubernetes_shared_volume, {
        "uv_cache/archive-v0/gross": 5000,
        "uv_cache/simple-v18/klein": 100,
        "pipeline_runs/abc/datei": 700,
    })

    result = _sync_shared_volume_breakdown()

    assert result["available"] is True
    assert [e["path"] for e in result["entries"]] == ["uv_cache", "pipeline_runs"]
    uv_cache = result["entries"][0]
    assert uv_cache["size_bytes"] == 5100
    assert uv_cache["file_count"] == 2
    assert [c["path"] for c in uv_cache["children"]] == [
        "uv_cache/archive-v0",
        "uv_cache/simple-v18",
    ]


def test_breakdown_counts_every_file_once(kubernetes_shared_volume):
    """
    Ein Durchlauf, auf Präfixe verteilt — die Ebenen dürfen sich nicht doppeln.

    Die Summe über die erste Ebene muss der Gesamtsumme entsprechen, sonst zählt
    die Aggregation tiefere Dateien mehrfach.
    """
    _fuelle(kubernetes_shared_volume, {
        "a/b/c/tief": 300,
        "a/flach": 200,
        "b/x": 100,
    })

    result = _sync_shared_volume_breakdown()

    assert result["total_bytes"] == 600
    assert result["file_count"] == 3
    assert sum(e["size_bytes"] for e in result["entries"]) == 600


def test_breakdown_includes_loose_files_at_the_top(kubernetes_shared_volume):
    """`du -sh /shared/*` listet lose Dateien einzeln — hier genauso."""
    _fuelle(kubernetes_shared_volume, {"CACHEDIR.TAG": 42})

    result = _sync_shared_volume_breakdown()

    assert [e["path"] for e in result["entries"]] == ["CACHEDIR.TAG"]
    assert result["entries"][0]["size_bytes"] == 42


def test_breakdown_caps_the_children_and_reports_the_rest(kubernetes_shared_volume):
    """pipeline_runs kann dreistellig viele Verzeichnisse haben."""
    from app.api.settings import _SHARED_BREAKDOWN_MAX_CHILDREN

    anzahl = _SHARED_BREAKDOWN_MAX_CHILDREN + 5
    _fuelle(kubernetes_shared_volume, {
        f"pipeline_runs/run{i:03d}/datei": 100 + i for i in range(anzahl)
    })

    entry = _sync_shared_volume_breakdown()["entries"][0]

    assert len(entry["children"]) == _SHARED_BREAKDOWN_MAX_CHILDREN
    assert entry["children_omitted"] == 5
    assert entry["children_omitted_bytes"] > 0
    # Die Sammelzeile plus die gezeigten Kinder ergeben wieder das Ganze.
    gezeigt = sum(c["size_bytes"] for c in entry["children"])
    assert gezeigt + entry["children_omitted_bytes"] == entry["size_bytes"]


def test_breakdown_reports_an_unmounted_volume(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PIPELINE_EXECUTOR", "kubernetes")
    monkeypatch.setattr(
        config, "KUBERNETES_SHARED_CACHE_MOUNT_PATH", str(tmp_path / "nicht-gemountet")
    )

    result = _sync_shared_volume_breakdown()

    assert result["available"] is False
    assert result["entries"] == []


def test_breakdown_endpoint_returns_the_entries(
    authenticated_client, kubernetes_shared_volume
):
    _fuelle(kubernetes_shared_volume, {"uv_cache/archive-v0/gross": 4096})

    response = authenticated_client.get("/api/settings/storage/shared-breakdown")

    assert response.status_code == 200
    body = response.json()
    assert body["entries"][0]["path"] == "uv_cache"
    assert body["file_count"] == 1
    assert "duration_seconds" in body


def test_breakdown_endpoint_needs_authentication(client, kubernetes_shared_volume):
    """Pfade und Grössen des Volumes gehören nicht in eine offene Antwort."""
    assert client.get("/api/settings/storage/shared-breakdown").status_code in (401, 403)


def test_breakdown_endpoint_is_404_without_kubernetes(authenticated_client, monkeypatch):
    monkeypatch.setattr(config, "PIPELINE_EXECUTOR", "docker")

    response = authenticated_client.get("/api/settings/storage/shared-breakdown")

    assert response.status_code == 404
