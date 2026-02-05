"""
Downstream Triggers Service.

Verwaltet Pipeline-Chaining: Wenn Pipeline A fertig ist, wird Pipeline B gestartet.
Triggert aus zwei Quellen: pipeline.json (downstream_triggers) und DB (DownstreamTrigger).
"""

import logging
from typing import List, Set

from sqlmodel import Session, select

from app.models import DownstreamTrigger
from app.services.pipeline_discovery import get_pipeline

logger = logging.getLogger(__name__)


def get_downstream_pipelines_to_trigger(
    upstream_pipeline_name: str,
    on_success: bool,
    session: Session,
) -> List[str]:
    """
    Gibt die Namen der Pipelines zurück, die getriggert werden sollen.

    Kombiniert Triggert aus pipeline.json und aus der DB. Dedupliziert nach Pipeline-Namen.

    Args:
        upstream_pipeline_name: Name der Upstream-Pipeline (die gerade fertig wurde)
        on_success: True wenn Upstream erfolgreich war, False bei Fehlschlag
        session: SQLModel Session

    Returns:
        Liste von Pipeline-Namen (ohne Duplikate)
    """
    pipelines_to_trigger: Set[str] = set()

    # 1. Aus pipeline.json (Upstream-Pipeline-Metadaten)
    upstream = get_pipeline(upstream_pipeline_name)
    if upstream and getattr(upstream.metadata, "downstream_triggers", None):
        for t in upstream.metadata.downstream_triggers:
            trigger_on_success = t.get("on_success", True)
            trigger_on_failure = t.get("on_failure", False)
            if on_success and trigger_on_success:
                pipelines_to_trigger.add(t["pipeline"])
            elif not on_success and trigger_on_failure:
                pipelines_to_trigger.add(t["pipeline"])

    # 2. Aus DB (DownstreamTrigger)
    stmt = (
        select(DownstreamTrigger)
        .where(DownstreamTrigger.upstream_pipeline == upstream_pipeline_name)
        .where(DownstreamTrigger.enabled == True)
    )
    for trigger in session.exec(stmt).all():
        if on_success and trigger.on_success:
            pipelines_to_trigger.add(trigger.downstream_pipeline)
        elif not on_success and trigger.on_failure:
            pipelines_to_trigger.add(trigger.downstream_pipeline)

    return sorted(pipelines_to_trigger)
