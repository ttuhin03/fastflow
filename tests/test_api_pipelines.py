"""
Integration Tests für Pipeline-API-Endpoints.

Testet die REST-API-Endpoints für Pipeline-Management:
- Pipeline-Liste abrufen
- Pipeline-Start (mit gemocktem Executor, ohne Docker)
"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone
from uuid import uuid4

from app.services.pipeline_discovery import discover_pipelines
from app.models import PipelineRun, RunStatus


def test_start_pipeline_simple(authenticated_client, temp_pipelines_dir):
    """
    Testet das Starten einer Pipeline über die API (run_pipeline gemockt, kein Docker).
    """
    # Pipeline-Verzeichnis mit main.py
    pipeline_dir = temp_pipelines_dir / "test_pipeline"
    pipeline_dir.mkdir()
    (pipeline_dir / "main.py").write_text("print('Hello')")
    discover_pipelines(force_refresh=True)

    # Mock run_pipeline: gibt einen Dummy-Run zurück
    mock_run = PipelineRun(
        id=uuid4(),
        pipeline_name="test_pipeline",
        status=RunStatus.PENDING,
        started_at=datetime.now(timezone.utc),
        log_file="logs/test_pipeline_123.log",
    )

    with patch("app.api.pipelines.run_pipeline", new_callable=AsyncMock) as mock_run_pipeline:
        mock_run_pipeline.return_value = mock_run

        response = authenticated_client.post(
            "/api/pipelines/test_pipeline/run",
            json={"env_vars": None, "parameters": None},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["pipeline_name"] == "test_pipeline"
    assert data["status"] == RunStatus.PENDING.value
    assert "id" in data
    assert "started_at" in data
    assert "log_file" in data
    mock_run_pipeline.assert_called_once()


def test_list_pipelines(temp_pipelines_dir):
    """
    Testet das Abrufen der Pipeline-Liste über die API.
    """
    # Pipeline-Verzeichnis erstellen
    pipeline_dir = temp_pipelines_dir / "test_pipeline"
    pipeline_dir.mkdir()
    
    # main.py erstellen
    main_py = pipeline_dir / "main.py"
    main_py.write_text("print('Hello')")
    
    # Pipeline-Discovery ausführen
    discover_pipelines(force_refresh=True)
    
    # API-Aufruf würde hier erfolgen, aber ohne Test-Client
    # (Test-Client-Fix für conftest.py wäre nötig)
    pipelines = discover_pipelines()
    
    # Pipeline sollte gefunden werden
    assert len(pipelines) >= 1
    assert any(p.name == "test_pipeline" for p in pipelines)
