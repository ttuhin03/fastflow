"""
Downstream Triggers Service.

Verwaltet Pipeline-Chaining: Wenn Pipeline A fertig ist, wird Pipeline B gestartet.
Triggert aus zwei Quellen: pipeline.json (downstream_triggers) und DB (DownstreamTrigger).
"""

import logging
from typing import List, Optional, Set, Tuple

from sqlmodel import Session, select

from app.models import DownstreamTrigger
from app.services.pipeline_discovery import get_pipeline

logger = logging.getLogger(__name__)


def get_downstream_pipelines_to_trigger(
    upstream_pipeline_name: str,
    on_success: bool,
    session: Session,
) -> List[Tuple[str, Optional[str]]]:
    """
    Gibt die Pipelines zurück, die getriggert werden sollen (Name, run_config_id).

    Kombiniert Triggert aus pipeline.json und aus der DB.
    Dedupliziert nach (pipeline_name, run_config_id).

    Args:
        upstream_pipeline_name: Name der Upstream-Pipeline (die gerade fertig wurde)
        on_success: True wenn Upstream erfolgreich war, False bei Fehlschlag
        session: SQLModel Session

    Returns:
        Liste von (pipeline_name, run_config_id) ohne Duplikate
    """
    seen: Set[Tuple[str, Optional[str]]] = set()
    pipelines_to_trigger: List[Tuple[str, Optional[str]]] = []

    def add(pipeline_name: str, run_config_id: Optional[str]) -> None:
        key = (pipeline_name, run_config_id or None)
        if key not in seen:
            seen.add(key)
            pipelines_to_trigger.append((pipeline_name, run_config_id or None))

    # 1. Aus pipeline.json (Upstream-Pipeline-Metadaten)
    upstream = get_pipeline(upstream_pipeline_name)
    if upstream and getattr(upstream.metadata, "downstream_triggers", None):
        for t in upstream.metadata.downstream_triggers:
            trigger_on_success = t.get("on_success", True)
            trigger_on_failure = t.get("on_failure", False)
            if on_success and trigger_on_success:
                add(t["pipeline"], t.get("run_config_id"))
            elif not on_success and trigger_on_failure:
                add(t["pipeline"], t.get("run_config_id"))

    # 2. Aus DB (DownstreamTrigger)
    stmt = (
        select(DownstreamTrigger)
        .where(DownstreamTrigger.upstream_pipeline == upstream_pipeline_name)
        .where(DownstreamTrigger.enabled == True)
    )
    for trigger in session.exec(stmt).all():
        if on_success and trigger.on_success:
            add(trigger.downstream_pipeline, trigger.run_config_id)
        elif not on_success and trigger.on_failure:
            add(trigger.downstream_pipeline, trigger.run_config_id)

    return sorted(pipelines_to_trigger, key=lambda x: (x[0], x[1] or ""))
