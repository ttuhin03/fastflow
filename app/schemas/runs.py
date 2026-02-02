"""Request/Response-Schemas für Run-Endpoints."""

from typing import Any, Dict, List

from pydantic import BaseModel


class RunsResponse(BaseModel):
    """Response für Run-Liste (mit Pagination)."""
    runs: List[Dict[str, Any]]
    total: int
    page: int
    page_size: int
