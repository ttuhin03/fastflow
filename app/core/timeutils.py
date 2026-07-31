"""
Zeit-Hilfsfunktionen für die API-Serialisierung.

Datenbank-Spalten vom Typ DateTime speichern unter SQLite und PostgreSQL
Timestamps ohne Zeitzone. Beim Lesen kommen deshalb naive datetime-Objekte
zurück, obwohl die Anwendung durchgängig UTC schreibt (siehe _utc_now in
app.models). Ohne Offset im JSON interpretiert der Browser den Wert als
Lokalzeit – die angezeigte Uhrzeit wäre je nach Zeitzone des Clients falsch.
"""

from datetime import datetime, timezone
from typing import Optional


def to_utc_iso(value: Optional[datetime]) -> Optional[str]:
    """
    Serialisiert einen Zeitstempel als ISO-8601-String mit UTC-Offset.

    Args:
        value: Zeitstempel aus der Datenbank (naiv = UTC) oder None

    Returns:
        Optional[str]: z. B. "2026-07-31T09:12:00+00:00", None wenn value None ist
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()
