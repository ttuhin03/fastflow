"""
Tests für die Hermetik der Test-Suite.

Ein `pytest tests/` darf keine Dateien im Repository verändern. Regression für den
Fall, dass das UV-Pre-Heating beim App-Start (`uv pip compile -o <pipeline>/
requirements.txt.lock`) gegen das echte pipelines/-Verzeichnis lief und die
eingecheckten Lock-Files mit Host-Pfaden/Host-Paketen überschrieben hat.
"""

from pathlib import Path

import pytest

from app.core.config import config
from app.git_sync.sync import run_pre_heat_at_startup

REPO_ROOT = Path(__file__).resolve().parents[1]


def _is_inside_repo(path: Path) -> bool:
    return REPO_ROOT == path or REPO_ROOT in path.resolve().parents


def test_testing_mode_is_active():
    """Ohne TESTING=1 greifen die Guards für Docker/Scheduler/Pre-Heating nicht."""
    assert config.TESTING is True


@pytest.mark.parametrize("dir_name", ["PIPELINES_DIR", "DATA_DIR", "LOGS_DIR", "UV_CACHE_DIR"])
def test_writable_dirs_point_outside_the_repo(dir_name):
    """Alle beschreibbaren Verzeichnisse zeigen im Test in ein tmp-Verzeichnis."""
    path = getattr(config, dir_name)
    assert not _is_inside_repo(path), f"{dir_name} zeigt ins Repo: {path}"


async def test_pre_heat_at_startup_is_skipped_in_testing_mode(monkeypatch):
    """run_pre_heat_at_startup() darf im Testbetrieb kein `uv pip compile` auslösen."""
    called = False

    async def fail_preheat(session):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr("app.git_sync.sync._run_python_preheat", fail_preheat)

    await run_pre_heat_at_startup()

    assert called is False


def test_committed_lock_files_are_container_paths():
    """Die eingecheckten Lock-Files enthalten Container-Pfade, keine Host-Pfade."""
    lock_files = sorted((REPO_ROOT / "pipelines").glob("*/requirements.txt.lock"))
    assert lock_files, "keine requirements.txt.lock in pipelines/ gefunden"

    for lock_file in lock_files:
        header = lock_file.read_text().splitlines()[1]
        assert str(REPO_ROOT) not in header, f"Host-Pfad im Header von {lock_file}: {header}"
