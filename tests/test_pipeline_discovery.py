"""
Integration Tests für Pipeline-Discovery.

Testet die Pipeline-Erkennung und Validierung:
- Pipeline-Erkennung
- Requirements.txt-Erkennung
- Pipeline-Metadaten-Laden
"""

import pytest
from pathlib import Path

from app.pipeline_discovery import discover_pipelines, get_pipeline


def test_pipeline_discovery_simple_pipeline(temp_pipelines_dir):
    """
    Testet die Erkennung einer einfachen Pipeline ohne requirements.txt.
    """
    # Pipeline-Verzeichnis erstellen
    pipeline_dir = temp_pipelines_dir / "test_simple"
    pipeline_dir.mkdir()
    
    # main.py erstellen
    main_py = pipeline_dir / "main.py"
    main_py.write_text("print('Hello')")
    
    # Pipeline-Discovery ausführen
    pipelines = discover_pipelines(force_refresh=True)
    
    # Pipeline sollte gefunden werden
    assert len(pipelines) == 1
    assert pipelines[0].name == "test_simple"
    assert not pipelines[0].has_requirements


def test_pipeline_discovery_with_requirements(temp_pipelines_dir):
    """
    Testet die Erkennung einer Pipeline mit requirements.txt.
    """
    # Pipeline-Verzeichnis erstellen
    pipeline_dir = temp_pipelines_dir / "test_with_requirements"
    pipeline_dir.mkdir()
    
    # main.py erstellen
    main_py = pipeline_dir / "main.py"
    main_py.write_text("import requests\nprint('Hello')")
    
    # requirements.txt erstellen
    requirements_txt = pipeline_dir / "requirements.txt"
    requirements_txt.write_text("requests>=2.31.0")
    
    # Pipeline-Discovery ausführen
    pipelines = discover_pipelines(force_refresh=True)
    
    # Pipeline sollte gefunden werden
    assert len(pipelines) == 1
    assert pipelines[0].name == "test_with_requirements"
    assert pipelines[0].has_requirements


def test_pipeline_discovery_ignores_missing_main_py(temp_pipelines_dir):
    """
    Testet dass Pipelines ohne main.py ignoriert werden.
    """
    # Verzeichnis ohne main.py erstellen
    pipeline_dir = temp_pipelines_dir / "invalid_pipeline"
    pipeline_dir.mkdir()
    
    # requirements.txt erstellen (aber keine main.py)
    requirements_txt = pipeline_dir / "requirements.txt"
    requirements_txt.write_text("requests>=2.31.0")
    
    # Pipeline-Discovery ausführen
    pipelines = discover_pipelines(force_refresh=True)
    
    # Pipeline sollte NICHT gefunden werden
    assert len(pipelines) == 0


def test_get_pipeline_existing(temp_pipelines_dir):
    """
    Testet das Abrufen einer existierenden Pipeline.
    """
    # Pipeline-Verzeichnis erstellen
    pipeline_dir = temp_pipelines_dir / "test_pipeline"
    pipeline_dir.mkdir()
    
    # main.py erstellen
    main_py = pipeline_dir / "main.py"
    main_py.write_text("print('Hello')")
    
    # Pipeline-Discovery ausführen
    discover_pipelines(force_refresh=True)
    
    # Pipeline abrufen
    pipeline = get_pipeline("test_pipeline")
    
    # Pipeline sollte gefunden werden
    assert pipeline is not None
    assert pipeline.name == "test_pipeline"


def test_get_pipeline_nonexistent(temp_pipelines_dir):
    """
    Testet das Abrufen einer nicht-existierenden Pipeline.
    """
    # Pipeline-Discovery ausführen
    discover_pipelines(force_refresh=True)
    
    # Pipeline abrufen
    pipeline = get_pipeline("nonexistent_pipeline")
    
    # Pipeline sollte NICHT gefunden werden
    assert pipeline is None
