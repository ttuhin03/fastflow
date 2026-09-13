"""
Tests für die Validierung von `python_version` aus pipeline.json.

Hintergrund: der Wert landet als `uv --python <wert>` in Subprozessen. uv
akzeptiert dort auch Pfade und *führt die angegebene Datei aus*, um sie als
Interpreter zu inspizieren. Da das Pipeline-Repository im Orchestrator gemountet
ist und Git das Execute-Bit erhält, wäre ein Pfad dort eine Codeausführung
ausserhalb der Container-Isolation.
"""

import json

import pytest

from app.core.python_version import (
    UnsafePythonVersionError,
    ensure_safe_python_version,
    is_valid_python_version,
    sanitize_python_version,
)
from app.services.pipeline_discovery import PipelineMetadata, _load_pipeline_metadata


@pytest.mark.parametrize(
    "value",
    ["3.11", "3.12", "3.12.1", "3.9", "cpython@3.12", "cpython-3.12", "pypy@3.10", "graalpy@3.11"],
)
def test_accepts_plausible_versions(value):
    assert is_valid_python_version(value) is True


@pytest.mark.parametrize(
    "value",
    [
        # Pfade: uv würde die Datei ausführen, um sie zu inspizieren.
        "/app/pipelines/demo/payload.sh",
        "./payload.sh",
        "../../usr/bin/env",
        "/usr/bin/python3",
        # Argument-Injection in die uv-Kommandozeile.
        "--python-preference=only-system",
        "-3.11",
        # Shell-/Trennzeichen, falls der Wert je in einer Shell landet.
        "3.11; touch /tmp/x",
        "3.11 && id",
        "$(id)",
        "3.11\n--offline",
        # Unsinn und falsche Typen.
        "",
        "   ",
        "latest",
        "python3.11",
        "3",
        None,
        3.11,
        ["3.11"],
    ],
)
def test_rejects_unsafe_or_malformed_versions(value):
    assert is_valid_python_version(value) is False


def test_version_pattern_is_anchored_at_both_ends():
    """Ein gültiges Präfix oder Suffix darf nicht ausreichen."""
    assert is_valid_python_version("3.11/../../bin/sh") is False
    assert is_valid_python_version("/opt/3.11") is False
    assert is_valid_python_version("cpython@3.12; id") is False


def test_sanitize_returns_trimmed_value_for_valid_input():
    assert sanitize_python_version("  3.12  ", source="test") == "3.12"


def test_sanitize_drops_invalid_value_without_raising(caplog):
    """Discovery darf an einer kaputten pipeline.json nicht scheitern."""
    with caplog.at_level("WARNING"):
        assert sanitize_python_version("/app/pipelines/x/payload.sh", source="pipeline 'x'") is None
    assert "payload.sh" in caplog.text


def test_sanitize_treats_missing_and_empty_as_absent(caplog):
    """Kein Wert ist kein Fehler — es gilt schlicht DEFAULT_PYTHON_VERSION."""
    with caplog.at_level("WARNING"):
        assert sanitize_python_version(None, source="test") is None
        assert sanitize_python_version("   ", source="test") is None
    assert caplog.text == ""


def test_ensure_safe_raises_for_path_like_value():
    with pytest.raises(UnsafePythonVersionError):
        ensure_safe_python_version("/app/pipelines/demo/payload.sh")


def test_ensure_safe_returns_trimmed_value():
    assert ensure_safe_python_version(" 3.11 ") == "3.11"


def test_metadata_constructor_drops_unsafe_version():
    """Auch die direkte Konstruktion (ohne JSON) muss abgesichert sein."""
    meta = PipelineMetadata(python_version="/app/pipelines/demo/payload.sh")
    assert meta.python_version is None


def test_metadata_constructor_keeps_valid_version():
    assert PipelineMetadata(python_version="3.12").python_version == "3.12"


def test_pipeline_json_with_path_falls_back_to_default(tmp_path):
    """
    End-to-End über die Discovery: eine pipeline.json mit Interpreter-Pfad darf
    nie zu `uv --python <pfad>` führen.
    """
    pipeline_dir = tmp_path / "evil"
    pipeline_dir.mkdir()
    (pipeline_dir / "pipeline.json").write_text(
        json.dumps({"python_version": "/app/pipelines/evil/payload.sh"}), encoding="utf-8"
    )

    meta = _load_pipeline_metadata(pipeline_dir, "evil")

    assert meta is not None
    assert meta.python_version is None
    # get_python_version() fällt damit auf DEFAULT_PYTHON_VERSION zurück, das
    # seinerseits die Prüfung am Subprozess-Rand passieren muss.
    assert is_valid_python_version(
        PipelineMetadata(python_version=meta.python_version).python_version or "3.11"
    )
