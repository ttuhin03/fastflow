"""
Tests für die Pflege des UV-Paketcaches.

uv räumt seinen Cache nicht von selbst auf. In Prod standen 14,32 GB in
uv_cache/archive-v0 — 431.528 Dateien, 98,9 % des Volumes — bis kein Byte mehr
frei war und jeder Pipeline-Run mit ENOSPC scheiterte.

Der wichtigste Test hier ist der auf ``--ci``. Gemessen an einem frischen Cache
mit requests+pandas:

    uv cache prune        "No unused entries found"        70 MB -> 70 MB
    uv cache prune --ci   "Removed 2735 files (59.1MiB)"   70 MB -> 4,9 MB

Ohne ``--ci`` wäre das Ganze ein No-Op gewesen — der Job hätte stündlich gemeldet,
er habe geräumt, und das Volume wäre weiter volgelaufen.
"""

import subprocess
from uuid import uuid4

import pytest

from app.core.config import config
from app.models import PipelineRun, RunStatus
from app.services import uv_cache_maintenance as uvm

GIB = 1024 ** 3


@pytest.fixture(autouse=True)
def _reset_prune_state():
    """
    Die Notiz über einen abgebrochenen Prune liegt auf Modulebene.

    Ohne Reset trägt ein Test sie ins nächste und die Schwellen-Tests sehen eine
    Fortsetzung, wo sie ein Überspringen erwarten.
    """
    uvm._letzter_prune_unvollstaendig = False
    yield
    uvm._letzter_prune_unvollstaendig = False


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    d = tmp_path / "uv_cache"
    d.mkdir()
    monkeypatch.setattr(config, "UV_CACHE_DIR", d)
    monkeypatch.setattr(config, "UV_CACHE_PRUNE", True)
    monkeypatch.setattr(config, "UV_CACHE_PRUNE_MIN_FREE_GB", 2.0)
    return d


def _freier_platz(monkeypatch, *werte_gb):
    """Lässt uv_cache_free_bytes die Werte der Reihe nach melden."""
    rest = list(werte_gb)

    def _free():
        return int((rest.pop(0) if len(rest) > 1 else rest[0]) * GIB)

    monkeypatch.setattr(uvm, "uv_cache_free_bytes", _free)


def _run(session, status):
    run = PipelineRun(
        pipeline_name="demo", status=status, log_file=f"/tmp/{uuid4()}.log"
    )
    session.add(run)
    session.commit()
    return run


# --- Politik ------------------------------------------------------------------
#
# Ein erster Entwurf hatte ein Gate auf laufende Runs. In Prod bewirkte es das
# Gegenteil: dort läuft im Minutentakt eine Pipeline, es gibt also kein
# Leerlauffenster. Das Gate verklemmte sich selbst — Volume voll, Runs hängen,
# sehen aktiv aus, es wird nicht geräumt, Volume bleibt voll. Im Boot-Log stand
# "UV-Cache: räumen verschoben, es laufen Runs (0.00 GB frei)", während jeder Run
# an genau diesem fehlenden Platz scheiterte.
#
# Geschützt wird jetzt von uv selbst: `prune` ohne `--force` respektiert Einträge
# in Benutzung — eine Prüfung an der Wirklichkeit statt an der DB-Buchhaltung.


def test_prunes_even_while_runs_are_active(test_session, cache_dir, monkeypatch):
    """
    Der Regressionstest zur Verklemmung.

    Laufende Runs dürfen das Räumen nicht verhindern. Die Abwägung ist
    asymmetrisch: ohne Gate scheitert im schlimmsten Fall ein einzelner Run und
    wird wiederholt, mit Gate scheitern alle dauerhaft.
    """
    _run(test_session, RunStatus.RUNNING)
    _run(test_session, RunStatus.PENDING)
    _freier_platz(monkeypatch, 0.0)
    gerufen = []
    monkeypatch.setattr(uvm, "prune_uv_cache", lambda: gerufen.append(1) or {"status": "pruned"})

    result = uvm.maintain_uv_cache()

    assert result["status"] == "pruned"
    assert gerufen == [1]


def test_prunes_when_space_is_short(cache_dir, monkeypatch):
    _freier_platz(monkeypatch, 0.1)
    gerufen = []
    monkeypatch.setattr(uvm, "prune_uv_cache", lambda: gerufen.append(1) or {"status": "pruned"})

    assert uvm.maintain_uv_cache()["status"] == "pruned"
    assert gerufen == [1]


def test_keeps_the_cache_warm_above_the_threshold(cache_dir, monkeypatch):
    """
    Oberhalb der Schwelle wird nicht geräumt.

    --ci wirft den Cache fast komplett weg; das ist nur dann der bessere Zustand,
    wenn ohne Platz sonst *jeder* Run scheitert.
    """
    _freier_platz(monkeypatch, 9.0)
    monkeypatch.setattr(uvm, "prune_uv_cache", lambda: pytest.fail("darf nicht räumen"))

    result = uvm.maintain_uv_cache()

    assert result["status"] == "skipped"
    assert result["reason"] == "genug Platz"


def test_does_nothing_when_disabled(cache_dir, monkeypatch):
    monkeypatch.setattr(config, "UV_CACHE_PRUNE", False)
    monkeypatch.setattr(uvm, "prune_uv_cache", lambda: pytest.fail("darf nicht räumen"))

    assert uvm.maintain_uv_cache()["status"] == "disabled"


def test_unmeasurable_volume_does_not_prune(cache_dir, monkeypatch):
    """Ohne Messwert wird nicht geraten."""
    monkeypatch.setattr(uvm, "uv_cache_free_bytes", lambda: None)
    monkeypatch.setattr(uvm, "prune_uv_cache", lambda: pytest.fail("darf nicht räumen"))

    assert uvm.maintain_uv_cache()["status"] == "unmeasurable"


# --- Der Aufruf selbst --------------------------------------------------------

def _fake_subprocess(monkeypatch, returncode=0, raises=None):
    aufrufe = []

    def _run_cmd(cmd, **kwargs):
        aufrufe.append((cmd, kwargs))
        if raises is not None:
            raise raises
        return subprocess.CompletedProcess(cmd, returncode, stdout="", stderr="kaputt")

    monkeypatch.setattr(uvm.subprocess, "run", _run_cmd)
    return aufrufe


def test_prune_uses_ci_and_the_configured_cache_dir(cache_dir, monkeypatch):
    """
    Der Test, an dem alles hängt.

    Ohne --ci meldet uv "No unused entries found" und gibt kein Byte frei; die
    entpackten Wheels in archive-v0 bleiben liegen. --force fehlt bewusst: uv
    prüft selbst auf Einträge in Benutzung, und das ist die innere Schranke.
    """
    aufrufe = _fake_subprocess(monkeypatch)
    _freier_platz(monkeypatch, 0.1, 9.0)

    uvm.prune_uv_cache()

    cmd = aufrufe[0][0]
    assert cmd[:4] == ["uv", "cache", "prune", "--ci"]
    assert cmd[4:] == ["--cache-dir", str(cache_dir)]
    assert "--force" not in cmd


def test_prune_reports_the_space_the_filesystem_gained(cache_dir, monkeypatch):
    """Gemessen wird am Volume, nicht aus uvs Ausgabe gelesen."""
    _fake_subprocess(monkeypatch)
    _freier_platz(monkeypatch, 0.1, 8.1)

    result = uvm.prune_uv_cache()

    assert result["status"] == "pruned"
    assert result["freed_bytes"] == pytest.approx(8.0 * GIB, rel=0.01)


def test_prune_passes_the_configured_timeout(cache_dir, monkeypatch):
    """Ohne Grenze könnte ein hängender Mount den Job dauerhaft blockieren."""
    monkeypatch.setattr(config, "UV_CACHE_PRUNE_TIMEOUT", 123)
    aufrufe = _fake_subprocess(monkeypatch)
    _freier_platz(monkeypatch, 0.1, 9.0)

    uvm.prune_uv_cache()

    assert aufrufe[0][1]["timeout"] == 123


def test_prune_timeout_is_reported_not_raised(cache_dir, monkeypatch):
    _fake_subprocess(monkeypatch, raises=subprocess.TimeoutExpired("uv", 1))
    _freier_platz(monkeypatch, 0.1)

    result = uvm.prune_uv_cache()

    assert result["status"] == "timeout"
    assert result["freed_bytes"] == 0


def test_prune_nonzero_exit_is_reported(cache_dir, monkeypatch):
    _fake_subprocess(monkeypatch, returncode=2)
    _freier_platz(monkeypatch, 0.1)

    result = uvm.prune_uv_cache()

    assert result["status"] == "failed"
    assert result["returncode"] == 2


def test_prune_missing_binary_is_reported(cache_dir, monkeypatch):
    """Kein uv im Image darf den Job nicht mit einer Exception beenden."""
    _fake_subprocess(monkeypatch, raises=OSError("uv nicht gefunden"))
    _freier_platz(monkeypatch, 0.1)

    assert uvm.prune_uv_cache()["status"] == "failed"


# --- Notbremse ----------------------------------------------------------------

def test_wipe_removes_the_cache_and_recreates_the_directory(cache_dir, monkeypatch):
    (cache_dir / "archive-v0").mkdir()
    (cache_dir / "archive-v0" / "datei").write_bytes(b"x" * 100)
    _freier_platz(monkeypatch, 0.1, 9.0)

    result = uvm.wipe_uv_cache()

    assert result["status"] == "wiped"
    assert cache_dir.is_dir()
    assert not (cache_dir / "archive-v0").exists()


# --- Scheduler-Einstieg -------------------------------------------------------

def test_scheduler_callable_has_an_importable_reference():
    """
    Sonst lehnt der SQLAlchemyJobStore den Job ab und er läuft still nie —
    zweimal in diesem Projekt passiert (Waisen-Sweep, Session-Cleanup).
    """
    from apscheduler.util import obj_to_ref

    assert obj_to_ref(uvm.run_uv_cache_maintenance_job) == (
        "app.services.uv_cache_maintenance:run_uv_cache_maintenance_job"
    )


# --- Fortsetzung nach Timeout -------------------------------------------------
#
# Beim ersten Aufräumen eines gewachsenen Caches ist ein Abbruch der
# wahrscheinliche Verlauf: in Prod wurden rund 0,17 GB pro Minute frei, für ~13 GB
# also gut 75 Minuten. Ein abgeschnittener Prune hat Platz gemacht, aber nicht
# aufgeräumt — würde der nächste Lauf dann an der Schwelle abbiegen, bliebe der
# Rest für immer liegen.


def test_timeout_is_remembered_and_continued_above_the_threshold(cache_dir, monkeypatch):
    _fake_subprocess(monkeypatch, raises=subprocess.TimeoutExpired("uv", 1))
    _freier_platz(monkeypatch, 0.1)
    uvm.prune_uv_cache()
    assert uvm._letzter_prune_unvollstaendig is True

    # Jetzt ist wieder Platz — ohne die Notiz würde hier übersprungen.
    _freier_platz(monkeypatch, 9.0)
    gerufen = []
    monkeypatch.setattr(uvm, "prune_uv_cache", lambda: gerufen.append(1) or {"status": "pruned"})

    assert uvm.maintain_uv_cache()["status"] == "pruned"
    assert gerufen == [1]


def test_completed_prune_clears_the_note(cache_dir, monkeypatch):
    uvm._letzter_prune_unvollstaendig = True
    _fake_subprocess(monkeypatch)
    _freier_platz(monkeypatch, 0.1, 9.0)

    uvm.prune_uv_cache()

    assert uvm._letzter_prune_unvollstaendig is False


def test_timeout_reports_the_partial_gain(cache_dir, monkeypatch):
    """Was bis zum Abbruch frei wurde, bleibt frei — und soll auch so gemeldet werden."""
    _fake_subprocess(monkeypatch, raises=subprocess.TimeoutExpired("uv", 1))
    _freier_platz(monkeypatch, 0.1, 2.6)

    result = uvm.prune_uv_cache()

    assert result["status"] == "timeout"
    assert result["freed_bytes"] == pytest.approx(2.5 * GIB, rel=0.01)
