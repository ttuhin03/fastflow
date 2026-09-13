"""
Tests für das UV-Pre-Heating im Orchestrator.

Pre-Heating verarbeitet die requirements.txt aus dem Pipeline-Repository — im
Orchestrator-Prozess, nicht im isolierten Worker-Container. Die Aufrufe müssen
deshalb so eingeschnürt sein, dass kein Paket-Code ausgeführt werden kann:

* --no-build      keine sdist-Builds (setup.py / PEP-517-Backend)
* --no-project    kein Bauen eines pyproject.toml aus dem Arbeitsverzeichnis
* UV_NO_CONFIG    keine uv.toml / [tool.uv] aus dem Repository
* neutrales cwd   uv sucht Konfiguration ab dem Arbeitsverzeichnis aufwärts
"""

import subprocess

import pytest

from app.core.config import config
from app.git_sync import sync as sync_module


class _RecordingRun:
    """Ersetzt subprocess.run und merkt sich alle uv-Aufrufe."""

    def __init__(self, returncode: int = 0, stderr: str = ""):
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[dict] = []

    def __call__(self, args, **kwargs):
        self.calls.append({"args": list(args), **kwargs})
        return subprocess.CompletedProcess(args, self.returncode, "", self.stderr)


@pytest.fixture
def pipeline_dir(tmp_path):
    directory = tmp_path / "demo"
    directory.mkdir()
    (directory / "requirements.txt").write_text("requests==2.32.3\n", encoding="utf-8")
    # Von einem Angreifer platzierte uv-Konfiguration und ein Projekt-Manifest:
    # beides darf keine Wirkung entfalten.
    (directory / "uv.toml").write_text('index-url = "https://attacker.example"\n', encoding="utf-8")
    (directory / "pyproject.toml").write_text("[project]\nname = 'evil'\n", encoding="utf-8")
    return directory


@pytest.fixture
def recorded_preheat(pipeline_dir, monkeypatch):
    """Führt ein Pre-Heating mit abgefangenem subprocess.run aus."""

    def run(python_version: str = "3.11", recorder: _RecordingRun | None = None):
        import asyncio

        recorder = recorder or _RecordingRun()
        monkeypatch.setattr(sync_module.subprocess, "run", recorder)

        class _Session:
            def get(self, *_args, **_kwargs):
                return None

            def add(self, *_args, **_kwargs):
                return None

            def commit(self):
                return None

        ok, message = asyncio.run(
            sync_module._pre_heat_pipeline(
                "demo", pipeline_dir / "requirements.txt", python_version, _Session()
            )
        )
        return recorder, ok, message

    return run


def test_source_builds_are_refused_by_default(recorded_preheat):
    recorder, ok, _ = recorded_preheat()

    assert ok is True
    assert len(recorder.calls) == 2, "erwartet: uv pip compile + uv run"
    for call in recorder.calls:
        assert "--no-build" in call["args"], (
            "ohne --no-build baut uv sdists aus dem Pipeline-Repo im Orchestrator"
        )


def test_uv_run_does_not_build_the_pipeline_as_a_project(recorded_preheat):
    recorder, _, _ = recorded_preheat()

    install_args = recorder.calls[1]["args"]
    assert install_args[:2] == ["uv", "run"]
    assert "--no-project" in install_args
    assert "--no-config" in install_args


def test_repository_uv_config_is_ignored(recorded_preheat):
    recorder, _, _ = recorded_preheat()

    for call in recorder.calls:
        assert call["env"]["UV_NO_CONFIG"] == "1"


def test_working_directory_is_outside_the_pipeline(recorded_preheat, pipeline_dir):
    """
    uv liest uv.toml/pyproject.toml ab dem Arbeitsverzeichnis aufwärts. Läuft der
    Prozess im Pipeline-Verzeichnis, wäre das eine vom Repo kontrollierte Datei.
    """
    recorder, _, _ = recorded_preheat()

    from pathlib import Path

    for call in recorder.calls:
        cwd = Path(call["cwd"]).resolve()
        assert cwd != pipeline_dir.resolve()
        assert pipeline_dir.resolve() not in cwd.parents


def test_paths_are_passed_absolute(recorded_preheat, pipeline_dir):
    """Bei neutralem cwd müssen Requirements- und Lock-Pfad absolut sein."""
    recorder, _, _ = recorded_preheat()

    from pathlib import Path

    compile_args = recorder.calls[0]["args"]
    assert str(pipeline_dir.resolve() / "requirements.txt") in compile_args
    lock_arg = compile_args[compile_args.index("-o") + 1]
    assert Path(lock_arg).is_absolute()
    assert Path(lock_arg).name == "requirements.txt.lock"


def test_unsafe_python_version_aborts_before_any_subprocess(recorded_preheat):
    """
    `uv --python <pfad>` führt die angegebene Datei aus. Eine pipeline.json mit
    Interpreter-Pfad darf deshalb gar keinen uv-Prozess starten.
    """
    recorder, ok, message = recorded_preheat(python_version="/app/pipelines/demo/payload.sh")

    assert ok is False
    assert recorder.calls == []
    assert "payload.sh" in message


def test_opt_in_allows_source_builds(recorded_preheat, monkeypatch):
    """UV_ALLOW_SOURCE_BUILDS ist die bewusste, dokumentierte Ausnahme."""
    monkeypatch.setattr(config, "UV_ALLOW_SOURCE_BUILDS", True)

    recorder, _, _ = recorded_preheat()

    for call in recorder.calls:
        assert "--no-build" not in call["args"]


def test_failure_message_explains_the_no_build_restriction(recorded_preheat):
    recorder = _RecordingRun(returncode=1, stderr="Distribution requires building from source")

    _, ok, message = recorded_preheat(recorder=recorder)

    assert ok is False
    assert "UV_ALLOW_SOURCE_BUILDS" in message, "Betreiber muss die Ursache einordnen können"


def test_python_install_skips_unsafe_versions(monkeypatch):
    """Auch `uv python install` bekommt nie einen Pfad zu sehen."""
    recorder = _RecordingRun()
    monkeypatch.setattr(sync_module.subprocess, "run", recorder)
    monkeypatch.setattr(sync_module, "is_python_version_installed", lambda _v: False)

    sync_module._ensure_python_versions({"3.12", "/app/pipelines/demo/payload.sh"})

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["args"] == ["uv", "python", "install", "3.12"]
