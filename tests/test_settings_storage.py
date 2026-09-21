"""Tests für Speicher-Statistik und UV-Cache-Hilfsfunktionen."""

import threading
import time

import pytest

from app.api import settings as settings_api

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


@pytest.fixture(autouse=True)
def _reset_breakdown_state():
    """
    Der Zustand der Aufschlüsselung liegt auf Modulebene.

    Ohne Reset trägt ein Test das Ergebnis des vorherigen mit sich — der
    "noch nie gerechnet"-Test sieht dann ein fertiges Resultat.
    """
    settings_api._shared_breakdown_state = {"status": "never"}
    yield
    settings_api._shared_breakdown_state = {"status": "never"}


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


def _warte_auf_ergebnis(client, versuche=100):
    """Pollt GET, bis die Hintergrund-Rechnung durch ist."""
    for _ in range(versuche):
        body = client.get("/api/settings/storage/shared-breakdown").json()
        if body["status"] != "running":
            return body
        time.sleep(0.02)
    raise AssertionError(f"Rechnung nicht fertig geworden: {body}")


def test_breakdown_runs_in_the_background_and_reports_the_result(
    authenticated_client, kubernetes_shared_volume
):
    """
    Zweistufig, weil der Durchlauf länger dauern kann als das Client-Timeout.

    Synchron in der Anfrage gerechnet lief er ins 30-Sekunden-Timeout von
    apiClient: der Aufrufer sah einen Fehler, der Server harkte weiter, und das
    Ergebnis landete nirgends.
    """
    _fuelle(kubernetes_shared_volume, {"uv_cache/archive-v0/gross": 4096})

    gestartet = authenticated_client.post("/api/settings/storage/shared-breakdown")
    assert gestartet.status_code == 200
    assert gestartet.json()["status"] in ("running", "done")

    body = _warte_auf_ergebnis(authenticated_client)

    assert body["status"] == "done"
    assert body["result"]["entries"][0]["path"] == "uv_cache"
    assert body["result"]["file_count"] == 1
    assert body["started_at"] and body["finished_at"]


def test_breakdown_is_never_computed_before_the_first_trigger(
    authenticated_client, kubernetes_shared_volume
):
    """Ein GET allein darf das Volume nicht durchharken."""
    body = authenticated_client.get("/api/settings/storage/shared-breakdown").json()

    assert body["status"] == "never"
    assert "result" not in body or body["result"] is None


def test_second_trigger_does_not_start_a_second_walk(
    authenticated_client, kubernetes_shared_volume, monkeypatch
):
    """Ein zweiter Klick während des Durchlaufs würde sonst einen Thread nachlegen."""
    laeuft = threading.Event()
    weiter = threading.Event()
    aufrufe = []

    def _langsam(_on_progress=None):
        aufrufe.append(1)
        laeuft.set()
        weiter.wait(timeout=5)
        return {"dir": "/shared", "available": True, "entries": []}

    monkeypatch.setattr(settings_api, "_sync_shared_volume_breakdown", _langsam)

    authenticated_client.post("/api/settings/storage/shared-breakdown")
    assert laeuft.wait(timeout=5)
    zweiter = authenticated_client.post("/api/settings/storage/shared-breakdown")

    assert zweiter.json()["status"] == "running"
    weiter.set()
    _warte_auf_ergebnis(authenticated_client)
    assert len(aufrufe) == 1


def test_running_state_reports_the_elapsed_time(
    authenticated_client, kubernetes_shared_volume, monkeypatch
):
    """Damit die UI beim Warten etwas anzeigen kann — und nicht nur 'läuft'."""
    weiter = threading.Event()
    monkeypatch.setattr(
        settings_api,
        "_sync_shared_volume_breakdown",
        lambda _on_progress=None: (
            weiter.wait(timeout=5),
            {"dir": "/shared", "available": True, "entries": []},
        )[1],
    )

    authenticated_client.post("/api/settings/storage/shared-breakdown")
    body = authenticated_client.get("/api/settings/storage/shared-breakdown").json()

    assert body["status"] == "running"
    assert body["elapsed_seconds"] >= 0
    # Die monotone Startzeit ist Interna und gehört nicht in die Antwort.
    assert "started_monotonic" not in body
    weiter.set()
    _warte_auf_ergebnis(authenticated_client)


def test_breakdown_failure_is_reported_not_swallowed(
    authenticated_client, kubernetes_shared_volume, monkeypatch
):
    def _kaputt(_on_progress=None):
        raise OSError("Volume weg")

    monkeypatch.setattr(settings_api, "_sync_shared_volume_breakdown", _kaputt)

    authenticated_client.post("/api/settings/storage/shared-breakdown")
    body = _warte_auf_ergebnis(authenticated_client)

    assert body["status"] == "failed"
    assert "Volume weg" in body["error"]


def test_breakdown_endpoints_need_authentication(client, kubernetes_shared_volume):
    """Pfade und Grössen des Volumes gehören nicht in eine offene Antwort."""
    assert client.get("/api/settings/storage/shared-breakdown").status_code in (401, 403)
    assert client.post("/api/settings/storage/shared-breakdown").status_code in (401, 403)


def test_breakdown_endpoints_are_404_without_kubernetes(authenticated_client, monkeypatch):
    monkeypatch.setattr(config, "PIPELINE_EXECUTOR", "docker")

    assert authenticated_client.get(
        "/api/settings/storage/shared-breakdown"
    ).status_code == 404
    assert authenticated_client.post(
        "/api/settings/storage/shared-breakdown"
    ).status_code == 404


# --- Fortschritt --------------------------------------------------------------
#
# Der Durchlauf war eine Blackbox: 218 s ohne jedes Lebenszeichen. Der Aufrufer
# sah eine Uhr laufen, im Log stand bis zum Abschluss nichts. "Arbeitet" liess
# sich nicht von "klemmt" unterscheiden.


def test_walk_reports_progress_while_running(kubernetes_shared_volume, monkeypatch):
    monkeypatch.setattr(settings_api, "_SHARED_BREAKDOWN_PROGRESS_FILES", 2)
    _fuelle(kubernetes_shared_volume, {f"uv_cache/datei{i}": 10 for i in range(6)})
    meldungen = []

    settings_api._walk_sizes(
        kubernetes_shared_volume, lambda files, size: meldungen.append((files, size))
    )

    assert meldungen, "kein Fortschritt gemeldet"
    # Monoton steigend, und die letzte Meldung liegt nicht über dem Endstand.
    assert [m[0] for m in meldungen] == sorted(m[0] for m in meldungen)
    assert meldungen[-1][0] <= 6


def test_running_state_exposes_files_and_bytes_seen(
    authenticated_client, kubernetes_shared_volume, monkeypatch
):
    """Damit die UI echten Fortschritt zeigen kann statt nur einer Uhr."""
    weiter = threading.Event()
    gemeldet = threading.Event()

    def _langsam(on_progress=None):
        if on_progress is not None:
            on_progress(1234, 5678)
        gemeldet.set()
        weiter.wait(timeout=5)
        return {"dir": "/shared", "available": True, "entries": []}

    monkeypatch.setattr(settings_api, "_sync_shared_volume_breakdown", _langsam)

    authenticated_client.post("/api/settings/storage/shared-breakdown")
    assert gemeldet.wait(timeout=5)
    body = authenticated_client.get("/api/settings/storage/shared-breakdown").json()

    assert body["files_seen"] == 1234
    assert body["bytes_seen"] == 5678
    # Die monotonen Zeitstempel sind Interna.
    assert "last_logged_monotonic" not in body
    assert "started_monotonic" not in body
    weiter.set()
    _warte_auf_ergebnis(authenticated_client)
