"""
Pipeline Graph Service.

Berechnet den gerichteten Graphen aller Pipelines aus Downstream-Triggern
(pipeline.json + DB) und erkennt Zyklen via DFS.
"""

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlmodel import Session, select

from app.models import DownstreamTrigger
from app.services.pipeline_discovery import discover_pipelines

logger = logging.getLogger(__name__)


def get_pipelines_graph(session: Session) -> Dict[str, Any]:
    """
    Baut den Pipeline-Abhängigkeitsgraphen aus allen Downstream-Triggern.

    Kombiniert Trigger aus pipeline.json-Metadaten und der DB (DownstreamTrigger).
    Führt eine Zyklus-Erkennung via DFS durch und markiert gefundene Zyklen.

    Returns:
        Dict mit:
          - nodes: Sortierte Liste aller Pipeline-Namen (auch referenzierte, nicht-entdeckte)
          - edges: Liste aller Kanten mit from, to, on_success, on_failure, run_config_id, source
          - has_cycles: True wenn mindestens ein Zyklus existiert
          - cycles: Liste der Zyklen; jeder Zyklus ist eine Liste von Pipeline-Namen
                    (erster == letzter Name, z.B. ["a", "b", "a"])
    """
    all_names: Set[str] = set()
    edges: List[Dict[str, Any]] = []
    seen_edges: Set[Tuple[str, str, Optional[str]]] = set()

    # 1. Aus pipeline.json-Metadaten
    try:
        discovered_pipelines = discover_pipelines()
    except Exception as e:
        logger.warning("Pipeline-Discovery fehlgeschlagen beim Graph-Aufbau: %s", e)
        discovered_pipelines = []

    for pipeline in discovered_pipelines:
        all_names.add(pipeline.name)
        triggers = getattr(pipeline.metadata, "downstream_triggers", None) or []
        for t in triggers:
            dst = t.get("pipeline")
            if not dst:
                continue
            run_config_id = t.get("run_config_id") or None
            key = (pipeline.name, dst, run_config_id)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            all_names.add(dst)
            edges.append({
                "from": pipeline.name,
                "to": dst,
                "on_success": t.get("on_success", True),
                "on_failure": t.get("on_failure", False),
                "on_route": t.get("on_route") or None,
                "run_config_id": run_config_id,
                "source": "pipeline_json",
            })

    # 2. Aus DB (DownstreamTrigger)
    try:
        stmt = select(DownstreamTrigger).where(DownstreamTrigger.enabled == True)  # noqa: E712
        for trigger in session.exec(stmt).all():
            run_config_id = trigger.run_config_id or None
            key = (trigger.upstream_pipeline, trigger.downstream_pipeline, run_config_id)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            all_names.add(trigger.upstream_pipeline)
            all_names.add(trigger.downstream_pipeline)
            edges.append({
                "from": trigger.upstream_pipeline,
                "to": trigger.downstream_pipeline,
                "on_success": trigger.on_success,
                "on_failure": trigger.on_failure,
                "on_route": trigger.on_route or None,
                "run_config_id": run_config_id,
                "source": "api",
            })
    except Exception as e:
        logger.warning("Fehler beim Laden der DB-Downstream-Trigger für Graph: %s", e)

    cycles = _detect_cycles(list(all_names), edges)

    return {
        "nodes": sorted(all_names),
        "edges": edges,
        "has_cycles": len(cycles) > 0,
        "cycles": cycles,
    }


def _detect_cycles(
    nodes: List[str],
    edges: List[Dict[str, Any]],
) -> List[List[str]]:
    """
    DFS-basierte Zyklus-Erkennung für einen gerichteten Graphen.

    Gibt eine Liste aller gefundenen Zyklen zurück. Jeder Zyklus ist eine
    Liste von Knoten-Namen, wobei der erste und letzte Eintrag identisch sind
    (z.B. ["pipeline_a", "pipeline_b", "pipeline_a"]).

    Duplikate (gleiche Knotenmengen, nur andere Startpunkte) werden herausgefiltert.
    """
    # Adjazenzliste aufbauen (Mehrfachkanten auf gleicher (src, dst) deduplizieren)
    adj: Dict[str, Set[str]] = {n: set() for n in nodes}
    for e in edges:
        src, dst = e["from"], e["to"]
        if src not in adj:
            adj[src] = set()
        if dst not in adj:
            adj[dst] = set()
        adj[src].add(dst)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {n: WHITE for n in adj}
    path: List[str] = []
    found_cycles: List[List[str]] = []
    # Zyklus-Signaturen: frozenset der Kanten im Zyklus zur Deduplizierung
    cycle_sigs: Set[frozenset] = set()

    def dfs(node: str) -> None:
        color[node] = GRAY
        path.append(node)
        for neighbor in sorted(adj.get(node, set())):
            neighbor_color = color.get(neighbor, WHITE)
            if neighbor_color == GRAY:
                # Zyklus gefunden – Pfad ab dem Back-Edge-Ziel extrahieren
                try:
                    start_idx = path.index(neighbor)
                except ValueError:
                    continue
                cycle = path[start_idx:] + [neighbor]
                sig = frozenset(zip(cycle, cycle[1:]))
                if sig not in cycle_sigs:
                    cycle_sigs.add(sig)
                    found_cycles.append(cycle)
            elif neighbor_color == WHITE:
                dfs(neighbor)
        path.pop()
        color[node] = BLACK

    for node in sorted(adj.keys()):
        if color[node] == WHITE:
            dfs(node)

    return found_cycles
