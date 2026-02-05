"""Request/Response-Schemas für Pipeline-Endpoints."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class PipelineResponse(BaseModel):
    """Response-Model für Pipeline-Informationen."""
    name: str
    has_requirements: bool
    last_cache_warmup: Optional[str]
    total_runs: int
    successful_runs: int
    failed_runs: int
    enabled: bool
    metadata: Dict[str, Any]


class RunPipelineRequest(BaseModel):
    """Request-Model für Pipeline-Start."""
    env_vars: Optional[Dict[str, str]] = None
    parameters: Optional[Dict[str, str]] = None


class PipelineStatsResponse(BaseModel):
    """Response-Model für Pipeline-Statistiken."""
    pipeline_name: str
    total_runs: int
    successful_runs: int
    failed_runs: int
    success_rate: float
    webhook_runs: int


class DailyStat(BaseModel):
    """Response-Model für tägliche Pipeline-Statistiken."""
    date: str  # ISO format: YYYY-MM-DD
    total_runs: int
    successful_runs: int
    failed_runs: int
    success_rate: float
    run_ids: Optional[List[str]] = None


class DailyStatsResponse(BaseModel):
    """Response-Model für tägliche Pipeline-Statistiken."""
    daily_stats: List[DailyStat]


class PipelineSourceFilesResponse(BaseModel):
    """Response-Model für Pipeline-Quelldateien."""
    main_py: Optional[str] = None
    requirements_txt: Optional[str] = None
    pipeline_json: Optional[str] = None


class DownstreamTriggerResponse(BaseModel):
    """Response-Model für einen Downstream-Trigger."""
    id: Optional[str] = None  # None wenn aus pipeline.json (nur DB-Triggert haben ID)
    downstream_pipeline: str
    on_success: bool
    on_failure: bool
    source: str  # "pipeline_json" oder "api"


class DownstreamTriggerCreate(BaseModel):
    """Request-Model zum Anlegen eines Downstream-Triggers (DB)."""
    downstream_pipeline: str
    on_success: bool = True
    on_failure: bool = False
