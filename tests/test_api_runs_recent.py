"""
Tests für GET /api/runs/recent-per-pipeline (Window-Function-Query).
"""

from datetime import datetime, timedelta, timezone

from app.models import PipelineRun, RunStatus


def _make_run(name: str, minutes_ago: int, status: RunStatus = RunStatus.SUCCESS) -> PipelineRun:
    return PipelineRun(
        pipeline_name=name,
        status=status,
        log_file=f"/logs/{name}.log",
        started_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )


def test_recent_per_pipeline_limits_and_orders(authenticated_client, test_session):
    # Pipeline a: 7 Runs, Pipeline b: 2 Runs
    for i in range(7):
        test_session.add(_make_run("a", minutes_ago=i, status=RunStatus.SUCCESS if i % 2 == 0 else RunStatus.FAILED))
    for i in range(2):
        test_session.add(_make_run("b", minutes_ago=i, status=RunStatus.RUNNING))
    test_session.commit()

    response = authenticated_client.get("/api/runs/recent-per-pipeline?limit_per_pipeline=5")
    assert response.status_code == 200
    pipelines = response.json()["pipelines"]

    assert set(pipelines.keys()) == {"a", "b"}
    assert len(pipelines["a"]) == 5
    assert len(pipelines["b"]) == 2

    # Neueste zuerst
    started = [r["started_at"] for r in pipelines["a"]]
    assert started == sorted(started, reverse=True)

    # Statuswerte sind serialisierte Enum-Werte
    assert pipelines["b"][0]["status"] == "RUNNING"
    assert all(r["status"] in {"SUCCESS", "FAILED"} for r in pipelines["a"])


def test_recent_per_pipeline_empty(authenticated_client):
    response = authenticated_client.get("/api/runs/recent-per-pipeline")
    assert response.status_code == 200
    assert response.json() == {"pipelines": {}}
