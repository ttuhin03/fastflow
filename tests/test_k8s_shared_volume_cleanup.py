"""
Tests für den Waisen-Sweep auf dem shared Volume des Kubernetes-Executors.

``cleanup_orphaned_shared_pipeline_runs`` lief ursprünglich nur beim App-Start
und durfte deshalb grob sein: "alles ausser RUNNING wird gelöscht". Seit der
Sweep zusätzlich stündlich läuft, trifft er auf laufende Runs — und dabei auf
zwei Fenster, in denen ein Verzeichnis bereits existiert, ohne dass ein
RUNNING-Run dazu zu sehen ist:

1. ``run_container_task`` kopiert die Pipeline, bevor es den Run auf RUNNING
   setzt. Dazwischen steht der Run auf PENDING.
2. Der Statuswechsel kann in einer noch nicht committeten Transaktion stecken.
   Aus der Session des Sweeps ist der Run dann überhaupt nicht sichtbar.

Beides würde einem gerade startenden Run die Dateien unter den Füssen wegräumen.
Die Tests pinnen deshalb die beiden Schranken: Endzustand-Liste und Schonfrist.
"""

import os
import time
from uuid import uuid4

import pytest

from app.core.config import config
from app.executor import kubernetes_backend as k8s
from app.models import PipelineRun, RunStatus


@pytest.fixture
def pipeline_runs_dir(tmp_path, monkeypatch):
    """Leitet das shared Volume in ein tmp-Verzeichnis um und legt pipeline_runs an."""
    shared = tmp_path / "shared"
    monkeypatch.setattr(config, "KUBERNETES_SHARED_CACHE_MOUNT_PATH", str(shared))
    base = shared / "pipeline_runs"
    base.mkdir(parents=True)
    return base


def _run(session, status, run_id=None):
    run = PipelineRun(
        pipeline_name="demo",
        status=status,
        log_file=f"/tmp/{uuid4()}.log",
    )
    if run_id is not None:
        run.id = run_id
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def _run_dir(base, run_id, *, age_seconds):
    """Legt pipeline_runs/<run_id> mit Inhalt an und setzt die mtime auf age_seconds."""
    path = base / str(run_id)
    path.mkdir()
    (path / "pipeline.json").write_text("{}")
    stamp = time.time() - age_seconds
    os.utime(path, (stamp, stamp))
    return path


_OLD = k8s._ORPHAN_SWEEP_MIN_AGE_SECONDS + 60
_FRESH = 5


@pytest.mark.parametrize(
    "status",
    [RunStatus.SUCCESS, RunStatus.FAILED, RunStatus.INTERRUPTED, RunStatus.WARNING],
)
def test_finished_run_directory_is_deleted(test_session, pipeline_runs_dir, status):
    """Jeder Endzustand gibt sein Verzeichnis frei — darum geht es beim Sweep."""
    run = _run(test_session, status)
    path = _run_dir(pipeline_runs_dir, run.id, age_seconds=_OLD)

    assert k8s.cleanup_orphaned_shared_pipeline_runs(test_session) == 1
    assert not path.exists()


def test_directory_without_run_in_db_is_deleted(test_session, pipeline_runs_dir):
    """Ein Verzeichnis ohne DB-Eintrag ist eine echte Waise (Run längst gelöscht)."""
    path = _run_dir(pipeline_runs_dir, uuid4(), age_seconds=_OLD)

    assert k8s.cleanup_orphaned_shared_pipeline_runs(test_session) == 1
    assert not path.exists()


def test_running_run_keeps_its_directory(test_session, pipeline_runs_dir):
    run = _run(test_session, RunStatus.RUNNING)
    path = _run_dir(pipeline_runs_dir, run.id, age_seconds=_OLD)

    assert k8s.cleanup_orphaned_shared_pipeline_runs(test_session) == 0
    assert (path / "pipeline.json").exists()


def test_pending_run_keeps_its_directory(test_session, pipeline_runs_dir):
    """
    Das Fenster zwischen Kopie und Statuswechsel in run_container_task.

    Die alte Bedingung lautete ``status != RUNNING`` und hätte hier gelöscht —
    beim Start folgenlos, im stündlichen Lauf ein Run, dem mitten im Anlauf die
    Pipeline verschwindet.
    """
    run = _run(test_session, RunStatus.PENDING)
    path = _run_dir(pipeline_runs_dir, run.id, age_seconds=_OLD)

    assert k8s.cleanup_orphaned_shared_pipeline_runs(test_session) == 0
    assert (path / "pipeline.json").exists()


def test_fresh_directory_is_kept_even_without_a_run(test_session, pipeline_runs_dir):
    """
    Die Schonfrist deckt den Fall ab, dass der Run noch nicht committet ist.

    Aus der Session des Sweeps sieht das wie eine Waise aus; nur das Alter des
    Verzeichnisses unterscheidet den gerade startenden Run von der echten Waise.
    """
    path = _run_dir(pipeline_runs_dir, uuid4(), age_seconds=_FRESH)

    assert k8s.cleanup_orphaned_shared_pipeline_runs(test_session) == 0
    assert (path / "pipeline.json").exists()


def test_fresh_directory_of_finished_run_is_kept(test_session, pipeline_runs_dir):
    """Auch ein Endzustand wartet die Schonfrist ab — beide Schranken müssen greifen."""
    run = _run(test_session, RunStatus.SUCCESS)
    path = _run_dir(pipeline_runs_dir, run.id, age_seconds=_FRESH)

    assert k8s.cleanup_orphaned_shared_pipeline_runs(test_session) == 0
    assert (path / "pipeline.json").exists()


def test_non_uuid_directories_are_ignored(test_session, pipeline_runs_dir):
    """uv_cache & Co. liegen im selben Volume; der Sweep fasst nur run_id-Ordner an."""
    stray = pipeline_runs_dir / "nicht-eine-uuid"
    stray.mkdir()
    (stray / "datei").write_text("x")
    stamp = time.time() - _OLD
    os.utime(stray, (stamp, stamp))

    assert k8s.cleanup_orphaned_shared_pipeline_runs(test_session) == 0
    assert (stray / "datei").exists()


def test_missing_base_directory_is_not_an_error(test_session, tmp_path, monkeypatch):
    """Ohne gemountetes Volume (Docker-Pfad, frischer Pod) darf nichts knallen."""
    monkeypatch.setattr(
        config, "KUBERNETES_SHARED_CACHE_MOUNT_PATH", str(tmp_path / "gibt-es-nicht")
    )
    assert k8s.cleanup_orphaned_shared_pipeline_runs(test_session) == 0


def test_only_the_finished_run_is_swept(test_session, pipeline_runs_dir):
    """Gemischter Bestand: der Sweep trifft genau ein Verzeichnis."""
    finished = _run(test_session, RunStatus.SUCCESS)
    running = _run(test_session, RunStatus.RUNNING)
    finished_path = _run_dir(pipeline_runs_dir, finished.id, age_seconds=_OLD)
    running_path = _run_dir(pipeline_runs_dir, running.id, age_seconds=_OLD)
    fresh_path = _run_dir(pipeline_runs_dir, uuid4(), age_seconds=_FRESH)

    assert k8s.cleanup_orphaned_shared_pipeline_runs(test_session) == 1
    assert not finished_path.exists()
    assert running_path.exists()
    assert fresh_path.exists()
