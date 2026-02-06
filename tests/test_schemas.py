"""
Unit-Tests für Pydantic-Schemas (app.schemas.pipelines).

Testet Validierung und Defaults der Request/Response-Modelle.
"""

import pytest
from pydantic import ValidationError

from app.schemas.pipelines import (
    PipelineResponse,
    RunPipelineRequest,
    PipelineStatsResponse,
    DailyStat,
    DailyStatsResponse,
    PipelineSourceFilesResponse,
    DownstreamTriggerResponse,
    DownstreamTriggerCreate,
)


class TestRunPipelineRequest:
    """Tests für RunPipelineRequest."""

    def test_empty_valid(self):
        """Leeres Request ist valide (alle Felder optional)."""
        req = RunPipelineRequest()
        assert req.env_vars is None
        assert req.parameters is None

    def test_with_env_vars(self):
        """env_vars wird akzeptiert."""
        req = RunPipelineRequest(env_vars={"KEY": "value"})
        assert req.env_vars == {"KEY": "value"}

    def test_with_parameters(self):
        """parameters wird akzeptiert."""
        req = RunPipelineRequest(parameters={"param1": "x"})
        assert req.parameters == {"param1": "x"}

    def test_both_fields(self):
        """Beide Felder gesetzt."""
        req = RunPipelineRequest(env_vars={"A": "1"}, parameters={"B": "2"})
        assert req.env_vars == {"A": "1"}
        assert req.parameters == {"B": "2"}


class TestPipelineResponse:
    """Tests für PipelineResponse."""

    def test_valid_response(self):
        """Valide PipelineResponse."""
        resp = PipelineResponse(
            name="test_pipeline",
            has_requirements=True,
            last_cache_warmup=None,
            total_runs=10,
            successful_runs=8,
            failed_runs=2,
            enabled=True,
            metadata={},
        )
        assert resp.name == "test_pipeline"
        assert resp.total_runs == 10
        assert resp.metadata == {}

    def test_name_required(self):
        """name ist erforderlich."""
        with pytest.raises(ValidationError):
            PipelineResponse(
                has_requirements=False,
                last_cache_warmup=None,
                total_runs=0,
                successful_runs=0,
                failed_runs=0,
                enabled=True,
                metadata={},
            )


class TestPipelineStatsResponse:
    """Tests für PipelineStatsResponse."""

    def test_valid_stats(self):
        """Valide PipelineStatsResponse."""
        resp = PipelineStatsResponse(
            pipeline_name="test",
            total_runs=100,
            successful_runs=90,
            failed_runs=10,
            success_rate=90.0,
            webhook_runs=5,
        )
        assert resp.success_rate == 90.0
        assert resp.webhook_runs == 5


class TestDailyStat:
    """Tests für DailyStat."""

    def test_valid_daily_stat(self):
        """Valide DailyStat."""
        stat = DailyStat(
            date="2024-01-15",
            total_runs=5,
            successful_runs=4,
            failed_runs=1,
            success_rate=80.0,
        )
        assert stat.date == "2024-01-15"
        assert stat.run_ids is None

    def test_with_run_ids(self):
        """DailyStat mit run_ids."""
        stat = DailyStat(
            date="2024-01-15",
            total_runs=2,
            successful_runs=2,
            failed_runs=0,
            success_rate=100.0,
            run_ids=["uuid1", "uuid2"],
        )
        assert stat.run_ids == ["uuid1", "uuid2"]


class TestDailyStatsResponse:
    """Tests für DailyStatsResponse."""

    def test_valid_response(self):
        """Valide DailyStatsResponse."""
        resp = DailyStatsResponse(daily_stats=[])
        assert resp.daily_stats == []

    def test_with_stats(self):
        """DailyStatsResponse mit Statistiken."""
        stats = [
            DailyStat(
                date="2024-01-15",
                total_runs=5,
                successful_runs=4,
                failed_runs=1,
                success_rate=80.0,
            ),
        ]
        resp = DailyStatsResponse(daily_stats=stats)
        assert len(resp.daily_stats) == 1
        assert resp.daily_stats[0].date == "2024-01-15"


class TestPipelineSourceFilesResponse:
    """Tests für PipelineSourceFilesResponse."""

    def test_all_optional(self):
        """Alle Felder optional."""
        resp = PipelineSourceFilesResponse()
        assert resp.main_py is None
        assert resp.requirements_txt is None
        assert resp.pipeline_json is None

    def test_with_values(self):
        """Mit gesetzten Werten."""
        resp = PipelineSourceFilesResponse(
            main_py="print('x')",
            requirements_txt="requests",
            pipeline_json='{"description":"Test"}',
        )
        assert resp.main_py == "print('x')"
        assert resp.requirements_txt == "requests"
        assert resp.pipeline_json == '{"description":"Test"}'


class TestDownstreamTriggerResponse:
    """Tests für DownstreamTriggerResponse."""

    def test_with_id(self):
        """Trigger mit ID (DB)."""
        resp = DownstreamTriggerResponse(
            id="uuid-123",
            downstream_pipeline="p2",
            on_success=True,
            on_failure=False,
            source="api",
        )
        assert resp.id == "uuid-123"
        assert resp.source == "api"

    def test_without_id(self):
        """Trigger ohne ID (aus pipeline.json)."""
        resp = DownstreamTriggerResponse(
            id=None,
            downstream_pipeline="p2",
            on_success=True,
            on_failure=False,
            source="pipeline_json",
        )
        assert resp.id is None
        assert resp.source == "pipeline_json"


class TestDownstreamTriggerCreate:
    """Tests für DownstreamTriggerCreate."""

    def test_minimal(self):
        """Minimal: nur downstream_pipeline."""
        req = DownstreamTriggerCreate(downstream_pipeline="p2")
        assert req.downstream_pipeline == "p2"
        assert req.on_success is True
        assert req.on_failure is False

    def test_full(self):
        """Alle Felder gesetzt."""
        req = DownstreamTriggerCreate(
            downstream_pipeline="p2",
            on_success=False,
            on_failure=True,
        )
        assert req.on_success is False
        assert req.on_failure is True

    def test_downstream_pipeline_required(self):
        """downstream_pipeline ist erforderlich."""
        with pytest.raises(ValidationError):
            DownstreamTriggerCreate()
