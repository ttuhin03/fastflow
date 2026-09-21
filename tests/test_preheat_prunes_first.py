"""
Tests dafür, dass das Pre-Heating den UV-Cache vorher räumt.

Der Cache wuchs unbegrenzt, weil jede je aufgelöste Paketversion liegenblieb —
in Prod 14,32 GB in 431.528 Dateien, bis nichts mehr lief. Die Notfallschwelle
(räumen unter UV_CACHE_PRUNE_MIN_FREE_GB) fängt das auf, aber erst am Abgrund,
und ein Durchlauf dort dauert dann Viertelstunden.

Vor dem Pre-Heating zu räumen dreht das um: Das Pre-Heating lädt anschliessend
genau den aktuellen Satz nach, der Cache enthält danach nichts anderes, und es
sammelt sich gar nicht erst etwas an. Bezahlbar ist es, weil das Räumen eines
sauberen Caches nichts kostet — gemessen 0,5 s für 5.486 Dateien gegenüber 15
Minuten für die aufgelaufenen 431.528.

Die Reihenfolge ist der Punkt: *vorher*, nicht nachher und nicht daneben.
Nachher würde --ci wegwerfen, was gerade geladen wurde. Daneben war der bisherige
Zustand — Räumen und Pre-Heating liefen als zwei Hintergrund-Aufgaben gleichzeitig
und behinderten sich ("Could not acquire lock", abgebrochene Downloads).
"""

import pytest

from app.core.config import config
from app.git_sync import sync as git_sync


@pytest.fixture
def preheat_ohne_pipelines(monkeypatch):
    """Schneidet das eigentliche Pre-Heating ab; hier geht es nur um das Räumen."""
    monkeypatch.setattr(git_sync, "get_required_python_versions", lambda: [])
    monkeypatch.setattr(git_sync, "discover_pipelines", lambda force_refresh=False: [])
    monkeypatch.setattr(config, "UV_CACHE_PRUNE", True)
    monkeypatch.setattr(config, "UV_CACHE_PRUNE_BEFORE_PREHEAT", True)


async def test_preheat_prunes_before_loading(test_session, preheat_ohne_pipelines, monkeypatch):
    gerufen = []
    monkeypatch.setattr(
        "app.services.uv_cache_maintenance.prune_uv_cache",
        lambda: gerufen.append("prune") or {"status": "pruned"},
    )

    await git_sync._run_python_preheat(test_session)

    assert gerufen == ["prune"]


async def test_prune_runs_before_the_pipelines(test_session, monkeypatch):
    """
    Die Reihenfolge, nicht nur das Vorkommen.

    Andersherum würde `--ci` genau die Pakete wegwerfen, die das Pre-Heating
    gerade geladen hat.
    """
    reihenfolge = []
    monkeypatch.setattr(git_sync, "get_required_python_versions", lambda: [])
    monkeypatch.setattr(config, "UV_CACHE_PRUNE", True)
    monkeypatch.setattr(config, "UV_CACHE_PRUNE_BEFORE_PREHEAT", True)
    monkeypatch.setattr(
        "app.services.uv_cache_maintenance.prune_uv_cache",
        lambda: reihenfolge.append("prune") or {"status": "pruned"},
    )
    monkeypatch.setattr(
        git_sync,
        "discover_pipelines",
        lambda force_refresh=False: reihenfolge.append("pipelines") or [],
    )

    await git_sync._run_python_preheat(test_session)

    assert reihenfolge == ["prune", "pipelines"]


async def test_no_prune_when_switched_off(test_session, preheat_ohne_pipelines, monkeypatch):
    """Wer im Minutentakt synchronisiert, schaltet das ab und verlässt sich auf die Schwelle."""
    monkeypatch.setattr(config, "UV_CACHE_PRUNE_BEFORE_PREHEAT", False)
    monkeypatch.setattr(
        "app.services.uv_cache_maintenance.prune_uv_cache",
        lambda: pytest.fail("darf nicht räumen"),
    )

    await git_sync._run_python_preheat(test_session)


async def test_no_prune_when_maintenance_is_off(test_session, preheat_ohne_pipelines, monkeypatch):
    """UV_CACHE_PRUNE=false schaltet jedes Räumen ab, auch dieses."""
    monkeypatch.setattr(config, "UV_CACHE_PRUNE", False)
    monkeypatch.setattr(
        "app.services.uv_cache_maintenance.prune_uv_cache",
        lambda: pytest.fail("darf nicht räumen"),
    )

    await git_sync._run_python_preheat(test_session)
