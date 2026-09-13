"""Obergrenzen für alles, was in den Kontext eines Agenten zurückfließt.

Das ist der eigentliche Mehrwert dieses Servers gegenüber einem rohen
``curl`` gegen die REST-API: ein Log eines gescheiterten ETL-Laufs kann
megabytegroß sein, und eine ungedeckelte Antwort verdrängt genau den Kontext,
den der Agent zum Diagnostizieren bräuchte.

Die Grenzen werden hier **erneut** durchgesetzt, obwohl die API selbst schon
deckelt (``app/api/logs.py`` kennt ``tail`` und eine Byte-Obergrenze). Ein
Client, der sich auf die Zusagen der Gegenseite verlässt, ist genau so lange
korrekt, bis sich die Gegenseite ändert.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# Logs
LOG_DEFAULT_TAIL: Final = 200
LOG_MAX_TAIL: Final = 2_000
LOG_MAX_BYTES: Final = 64 * 1024

# Zell-Ausgaben in der Run-Detailansicht
CELL_MAX_LINES: Final = 40

# Listen
RUNS_DEFAULT_LIMIT: Final = 20
RUNS_MAX_LIMIT: Final = 100
FAILURE_MAX_GROUPS: Final = 20

# Quelldateien
SOURCE_MAX_BYTES: Final = 128 * 1024


@dataclass(frozen=True)
class Bounded:
    """Ein gekürzter Text samt Angabe, was dabei verloren ging.

    Der Agent bekommt die Verkürzung immer mitgeteilt. Eine stillschweigend
    abgeschnittene Antwort wäre schlimmer als eine kurze: sie sieht aus wie
    das vollständige Bild und führt zu falschen Schlüssen.
    """

    text: str
    truncated: bool
    total_lines: int
    returned_lines: int
    returned_bytes: int

    def as_note(self) -> str:
        """Einzeiliger Hinweis für den Agenten, oder '' wenn nichts gekürzt wurde."""
        if not self.truncated:
            return ""
        return (
            f"[gekürzt: {self.returned_lines} von {self.total_lines} Zeilen, "
            f"{self.returned_bytes} Bytes – ältere Zeilen weggelassen]"
        )


def clamp(value: int | None, default: int, maximum: int, minimum: int = 1) -> int:
    """Begrenzt einen vom Agenten gewählten Wert auf einen brauchbaren Bereich.

    Ein Modell fragt gern ``limit=10000`` an. Statt den Aufruf mit einem Fehler
    abzulehnen (was eine Wiederholungsschleife auslöst), wird still auf das
    Maximum begrenzt – die Antwort nennt den tatsächlich verwendeten Wert.
    """
    if value is None:
        return default
    return max(minimum, min(int(value), maximum))


def tail_lines(
    text: str,
    max_lines: int = LOG_DEFAULT_TAIL,
    max_bytes: int = LOG_MAX_BYTES,
) -> Bounded:
    """Behält die letzten ``max_lines`` Zeilen, höchstens aber ``max_bytes``.

    Bei Logs ist das Ende die interessante Seite: dort steht der Fehler.
    """
    if not text:
        return Bounded("", False, 0, 0, 0)

    lines = text.splitlines()
    total = len(lines)
    kept = lines[-max_lines:] if total > max_lines else lines
    truncated = total > len(kept)

    joined = "\n".join(kept)
    encoded = joined.encode("utf-8")
    if len(encoded) > max_bytes:
        # Auf einer Zeichengrenze schneiden, damit kein halbes UTF-8-Zeichen
        # entsteht; danach die angebrochene erste Zeile verwerfen.
        clipped = encoded[-max_bytes:].decode("utf-8", errors="ignore")
        newline = clipped.find("\n")
        joined = clipped[newline + 1 :] if newline != -1 else clipped
        kept = joined.splitlines()
        truncated = True
        encoded = joined.encode("utf-8")

    return Bounded(
        text=joined,
        truncated=truncated,
        total_lines=total,
        returned_lines=len(kept),
        returned_bytes=len(encoded),
    )


def head_lines(text: str, max_lines: int) -> Bounded:
    """Behält die ersten ``max_lines`` Zeilen.

    Für Zell-Ausgaben: dort steht am Anfang, was die Zelle tun wollte.
    """
    if not text:
        return Bounded("", False, 0, 0, 0)
    lines = text.splitlines()
    total = len(lines)
    kept = lines[:max_lines]
    joined = "\n".join(kept)
    return Bounded(
        text=joined,
        truncated=total > len(kept),
        total_lines=total,
        returned_lines=len(kept),
        returned_bytes=len(joined.encode("utf-8")),
    )


def clip_bytes(text: str, max_bytes: int) -> Bounded:
    """Kürzt auf ``max_bytes`` vom Anfang her (für Quelldateien)."""
    if not text:
        return Bounded("", False, 0, 0, 0)
    encoded = text.encode("utf-8")
    total_lines = len(text.splitlines())
    if len(encoded) <= max_bytes:
        return Bounded(text, False, total_lines, total_lines, len(encoded))
    clipped = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return Bounded(
        text=clipped,
        truncated=True,
        total_lines=total_lines,
        returned_lines=len(clipped.splitlines()),
        returned_bytes=len(clipped.encode("utf-8")),
    )
