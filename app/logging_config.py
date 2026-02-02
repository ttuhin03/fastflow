"""
Logging-Konfiguration.

Enthält JsonFormatter und setup_logging() für einheitliches
Log-Level und optionales JSON-Format (z. B. für Produktion).
"""

import json
import logging
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """Formatter für strukturierte JSON-Logs (eine Zeile pro Eintrag)."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj, default=str)


def setup_logging(log_level: str = "INFO", log_json: bool = False) -> None:
    """
    Setzt Log-Level und optional JSON-Format für alle Root-Handler.

    Args:
        log_level: Name des Log-Levels (z. B. "INFO", "DEBUG").
        log_json: Wenn True, werden alle Handler auf JsonFormatter umgestellt.
    """
    root = logging.getLogger()
    level = getattr(logging, log_level.upper(), logging.INFO)
    root.setLevel(level)
    if log_json:
        try:
            for h in root.handlers:
                h.setFormatter(JsonFormatter())
        except Exception as e:
            logging.getLogger(__name__).warning(
                "LOG_JSON aktiviert, Formatter-Setup fehlgeschlagen: %s", e
            )
