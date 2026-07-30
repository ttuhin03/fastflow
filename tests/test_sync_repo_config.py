"""
Regression-Tests für die Sync-Repo-Config-API.

TE-21: pipelines_subdir mit ".."-Segmenten muss an der API-Grenze (422)
abgelehnt werden, statt unsanitisiert in der DB gespeichert zu werden und
später einen Path-Traversal aus dem PIPELINES_DIR-Sandbox zu ermöglichen
(CWE-22, siehe app/services/pipeline_discovery.py discover_pipelines()).
"""

import pytest

from app.core.config import config


@pytest.mark.parametrize(
    "subdir",
    [
        "../../etc",
        "../../../../",
        "pipelines/../../etc",
        "..",
    ],
)
def test_repo_config_rejects_pipelines_subdir_traversal(authenticated_client, subdir):
    """
    Ein require_write-User (nicht zwingend Admin) darf pipelines_subdir NICHT
    auf einen Wert mit ".."-Segmenten setzen: die API muss mit 422 antworten,
    statt den Wert unsanitisiert zu persistieren.
    """
    response = authenticated_client.post(
        "/api/sync/repo-config",
        json={
            "repo_url": "https://github.com/example/repo.git",
            "pipelines_subdir": subdir,
        },
    )
    assert response.status_code == 422


def test_repo_config_accepts_plain_pipelines_subdir(authenticated_client):
    """Ein normaler Unterordnername (ohne "..") wird weiterhin akzeptiert."""
    original_subdir = config.PIPELINES_SUBDIR
    try:
        response = authenticated_client.post(
            "/api/sync/repo-config",
            json={
                "repo_url": "https://github.com/example/repo.git",
                "pipelines_subdir": "pipelines",
            },
        )
        assert response.status_code == 200
        assert response.json()["pipelines_subdir"] == "pipelines"
    finally:
        # save_repo_config appliziert pipelines_subdir global auf config
        # (apply_orchestrator_settings_to_config); für andere Tests zurücksetzen.
        config.PIPELINES_SUBDIR = original_subdir


def test_generate_deploy_key_rejects_pipelines_subdir_traversal(authenticated_client):
    """Derselbe Schutz gilt für den Deploy-Key-Erzeugungs-Endpoint."""
    response = authenticated_client.post(
        "/api/sync/repo-config/generate-deploy-key",
        json={
            "repo_url": "git@github.com:example/repo.git",
            "pipelines_subdir": "../../etc",
        },
    )
    assert response.status_code == 422
