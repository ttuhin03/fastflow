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


def _matches(
    on_success_flag: bool,
    on_failure_flag: bool,
    on_route: Optional[str],
    is_success: bool,
    route: Optional[str],
) -> bool:
    """
    OR-Logik: Trigger feuert wenn irgendeine Bedingung zutrifft.

    on_route hat Sonderverhalten: Wenn gesetzt, matcht es nur bei SUCCESS und
    wenn die Route übereinstimmt. Ein on_route-Trigger feuert NICHT als
    Fallback via on_success wenn die Route nicht matcht.
    """
    if on_route is not None:
        # on_route ist gesetzt → nur feuern wenn SUCCESS + Route stimmt überein
        return is_success and route is not None and route == on_route
    if is_success and on_success_flag:
        return True
    if not is_success and on_failure_flag:
        return True
    return False


def get_downstream_pipelines_to_trigger(
    upstream_pipeline_name: str,
    on_success: bool,
    session: Session,
    route: Optional[str] = None,
) -> List[Tuple[str, Optional[str]]]:
    """
    Gibt die Pipelines zurück, die getriggert werden sollen (Name, run_config_id).

    Kombiniert Trigger aus pipeline.json und aus der DB.
    Dedupliziert nach (pipeline_name, run_config_id).

    Args:
        upstream_pipeline_name: Name der Upstream-Pipeline (die gerade fertig wurde)
        on_success: True wenn Upstream erfolgreich war, False bei Fehlschlag
        session: SQLModel Session
        route: Optionaler Route-String aus FASTFLOW_ROUTE_FILE (nur bei SUCCESS relevant)

    Returns:
        Liste von (pipeline_name, run_config_id) ohne Duplikate
    """
    seen: Set[Tuple[str, Optional[str]]] = set()
    pipelines_to_trigger: List[Tuple[str, Optional[str]]] = []

    def add(pipeline_name: str, run_config_id: Optional[str]) -> None:
        key = (pipeline_name, run_config_id or None)
        if key not in seen:
            if get_pipeline(pipeline_name) is None:
                logger.warning(
                    "Downstream-Trigger: Pipeline '%s' existiert nicht und wird übersprungen.",
                    pipeline_name,
                )
                return
            seen.add(key)
            pipelines_to_trigger.append((pipeline_name, run_config_id or None))

    # 1. Aus pipeline.json (Upstream-Pipeline-Metadaten)
    upstream = get_pipeline(upstream_pipeline_name)
    if upstream and getattr(upstream.metadata, "downstream_triggers", None):
        for t in upstream.metadata.downstream_triggers:
            on_route_json = t.get("on_route") or None
            if _matches(
                t.get("on_success", True),
                t.get("on_failure", False),
                on_route_json,
                on_success,
                route,
            ):
                add(t["pipeline"], t.get("run_config_id"))

    # 2. Aus DB (DownstreamTrigger)
    stmt = (
        select(DownstreamTrigger)
        .where(DownstreamTrigger.upstream_pipeline == upstream_pipeline_name)
        .where(DownstreamTrigger.enabled == True)  # noqa: E712
    )
    for trigger in session.exec(stmt).all():
        if _matches(
            trigger.on_success,
            trigger.on_failure,
            trigger.on_route or None,
            on_success,
            route,
        ):
            add(trigger.downstream_pipeline, trigger.run_config_id)

    return sorted(pipelines_to_trigger, key=lambda x: (x[0], x[1] or ""))
