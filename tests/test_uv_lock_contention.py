"""
Tests gegen die Ursachen von "Could not acquire lock for `/cache/uv_python`".

Zwei Bereiche:
1. Mount-Auflösung: Worker müssen dieselben uv-Verzeichnisse sehen wie der
   Orchestrator, sonst installiert jeder Worker Python selbst und nimmt dabei
   das uv-Lock.
2. ensure_python_version: darf im Hot-Path (ein Aufruf pro Run) keinen
   uv-Prozess starten, wenn die Version bereits installiert ist.
"""

from pathlib import Path
from unittest.mock import patch

from app.executor.core import _resolve_mount_source
from app.git_sync.sync import _ensure_python_versions, is_python_version_installed


# --- Mount-Auflösung ---------------------------------------------------------

# Reihenfolge wie in docker-compose.yaml: /app/data steht VOR /app/data/uv_python
OVERLAPPING_MOUNTS = [
    {"Destination": "/app/pipelines", "Source": "/srv/fastflow/pipelines"},
    {"Destination": "/app/data", "Source": "/srv/fastflow/data"},
    {"Destination": "/app/data/uv_cache", "Source": "/srv/fastflow/data/uv_cache"},
    {"Destination": "/app/data/uv_python", "Source": "/srv/fastflow/data/uv_python"},
]


def test_overlapping_mount_resolves_to_longest_match():
    """Der spezifischere Mount gewinnt, auch wenn der Parent zuerst gelistet ist."""
    assert (
        _resolve_mount_source(OVERLAPPING_MOUNTS, "/app/data/uv_python")
        == "/srv/fastflow/data/uv_python"
    )
    assert (
        _resolve_mount_source(OVERLAPPING_MOUNTS, "/app/data/uv_cache")
        == "/srv/fastflow/data/uv_cache"
    )


def test_exact_match_returns_source_unchanged():
    assert _resolve_mount_source(OVERLAPPING_MOUNTS, "/app/data") == "/srv/fastflow/data"


def test_subpath_without_own_mount_is_appended_to_parent_source():
    """Ohne eigenen Mount wird der Restpfad an den Parent-Host-Pfad gehängt."""
    assert (
        _resolve_mount_source(OVERLAPPING_MOUNTS, "/app/data/logs/routes")
        == "/srv/fastflow/data/logs/routes"
    )
    assert (
        _resolve_mount_source(OVERLAPPING_MOUNTS, "/app/pipelines/demo")
        == "/srv/fastflow/pipelines/demo"
    )


def test_sibling_prefix_does_not_match():
    """/app/database darf nicht über den /app/data-Mount aufgelöst werden."""
    assert _resolve_mount_source(OVERLAPPING_MOUNTS, "/app/database") is None


def test_trailing_slash_in_destination_is_normalized():
    mounts = [{"Destination": "/app/data/", "Source": "/srv/data"}]
    assert _resolve_mount_source(mounts, "/app/data/uv_python") == "/srv/data/uv_python"


def test_relative_or_missing_source_is_ignored():
    mounts = [
        {"Destination": "/app/data", "Source": "relative/path"},
        {"Destination": "/app/data", "Source": ""},
        {"Destination": "/app/data"},
    ]
    assert _resolve_mount_source(mounts, "/app/data/uv_python") is None


def test_no_matching_mount_returns_none():
    assert _resolve_mount_source([], "/app/data/uv_python") is None


# --- Python-Install-Erkennung ------------------------------------------------


def _make_managed_install(root: Path, name: str, complete: bool = True) -> None:
    install = root / name
    install.mkdir(parents=True)
    if complete:
        (install / "bin").mkdir()
        (install / "bin" / "python3").touch()


def test_installed_version_detected_by_prefix(tmp_path):
    _make_managed_install(tmp_path, "cpython-3.11.9-linux-x86_64-gnu")
    with patch("app.git_sync.sync.config.UV_PYTHON_INSTALL_DIR", tmp_path):
        assert is_python_version_installed("3.11") is True
        assert is_python_version_installed("3.11.9") is True
        assert is_python_version_installed("3.12") is False


def test_shorter_version_does_not_match_longer_minor(tmp_path):
    """"3.1" darf nicht auf cpython-3.11.x matchen."""
    _make_managed_install(tmp_path, "cpython-3.11.9-linux-x86_64-gnu")
    with patch("app.git_sync.sync.config.UV_PYTHON_INSTALL_DIR", tmp_path):
        assert is_python_version_installed("3.1") is False


def test_incomplete_install_is_not_counted(tmp_path):
    """Abgebrochener Download (kein bin/python3) gilt als nicht installiert."""
    _make_managed_install(tmp_path, "cpython-3.11.9-linux-x86_64-gnu", complete=False)
    with patch("app.git_sync.sync.config.UV_PYTHON_INSTALL_DIR", tmp_path):
        assert is_python_version_installed("3.11") is False


def test_missing_install_dir_is_not_installed(tmp_path):
    with patch("app.git_sync.sync.config.UV_PYTHON_INSTALL_DIR", tmp_path / "gibtsnicht"):
        assert is_python_version_installed("3.11") is False


# --- Hot-Path: kein uv-Subprozess bei vorhandener Version ---------------------


def test_ensure_skips_subprocess_when_already_installed(tmp_path):
    _make_managed_install(tmp_path, "cpython-3.11.9-linux-x86_64-gnu")
    with patch("app.git_sync.sync.config.UV_PYTHON_INSTALL_DIR", tmp_path), \
            patch("app.git_sync.sync.subprocess.run") as run_mock:
        _ensure_python_versions({"3.11"})
    run_mock.assert_not_called()


def test_ensure_installs_only_missing_versions(tmp_path):
    _make_managed_install(tmp_path, "cpython-3.11.9-linux-x86_64-gnu")
    with patch("app.git_sync.sync.config.UV_PYTHON_INSTALL_DIR", tmp_path), \
            patch("app.git_sync.sync.subprocess.run") as run_mock:
        run_mock.return_value.returncode = 0
        _ensure_python_versions({"3.11", "3.12"})

    installed_versions = [call.args[0][-1] for call in run_mock.call_args_list]
    assert installed_versions == ["3.12"]
