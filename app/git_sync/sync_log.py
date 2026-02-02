"""
Sync-Log: Lesen und Schreiben von Sync-Log-Einträgen (JSONL).
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import aiofiles

from app.config import config

logger = logging.getLogger(__name__)


def _get_sync_log_file() -> Path:
    """Gibt den Pfad zur Sync-Log-Datei zurück."""
    return config.LOGS_DIR / "sync.log"


async def _write_sync_log(entry: Dict[str, Any]) -> None:
    """Schreibt einen Sync-Log-Eintrag in die Log-Datei (JSONL-Format)."""
    log_file = _get_sync_log_file()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    entry["timestamp"] = datetime.utcnow().isoformat()
    try:
        async with aiofiles.open(log_file, "a", encoding="utf-8") as f:
            await f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.error("Fehler beim Schreiben von Sync-Log: %s", e)


async def get_sync_logs(limit: int = 100) -> List[Dict[str, Any]]:
    """
    Liest Sync-Logs aus der Log-Datei (neueste zuerst).

    Args:
        limit: Maximale Anzahl Log-Einträge (Standard: 100)

    Returns:
        Liste von Log-Einträgen
    """
    log_file = _get_sync_log_file()
    if not log_file.exists():
        return []
    try:
        logs = []
        async with aiofiles.open(log_file, "r", encoding="utf-8") as f:
            async for line in f:
                line = line.strip()
                if line:
                    try:
                        entry = json.loads(line)
                        logs.append(entry)
                    except json.JSONDecodeError:
                        continue
        logs.reverse()
        return logs[:limit]
    except Exception as e:
        logger.error("Fehler beim Lesen von Sync-Logs: %s", e)
        return []
