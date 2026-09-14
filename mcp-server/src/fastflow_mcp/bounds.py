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


def split_lines(text: str) -> list[str]:
    """Zerlegt Text an ``\n`` – und nur daran.

    Nicht ``str.splitlines()``: das trennt zusätzlich bei ``\v``, ``\f``,
    ``\u2028``, ``\x85`` und ``\r``. Zählt man damit, meldet der Server eine
    Kürzung, wo keine war, und schneidet anschließend genau die Zeilen weg, in
    denen der Traceback stand – gemessen an einem Beispiel: 5 Einheiten statt 1.

    ``\r`` allein ist dabei entschärft, weil die API die Datei im
    Text-Modus liest und Universal-Newlines ``\r`` schon dort zu ``\n``
    machen. Die übrigen Trenner erreichen den Server unverändert – und sich auf
    den Lesemodus der Gegenseite zu verlassen ist genau die Kopplung, die dieses
    Modul vermeiden soll. Die API bildet ihren Tail ebenfalls über
    ``split("\n")``; hier muss dieselbe Definition gelten.
    """
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines

# Logs
LOG_DEFAULT_TAIL: Final = 200
LOG_MAX_TAIL: Final = 2_000
LOG_MAX_BYTES: Final = 64 * 1024

# Zell-Ausgaben in der Run-Detailansicht
CELL_MAX_LINES: Final = 40
CELL_MAX_BYTES: Final = 8 * 1024

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

    lines = split_lines(text)
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
        kept = split_lines(joined)
        truncated = True
        encoded = joined.encode("utf-8")

    return Bounded(
        text=joined,
        truncated=truncated,
        total_lines=total,
        returned_lines=len(kept),
        returned_bytes=len(encoded),
    )


def head_lines(text: str, max_lines: int, max_bytes: int = CELL_MAX_BYTES) -> Bounded:
    """Behält die ersten ``max_lines`` Zeilen, höchstens aber ``max_bytes``.

    Für Zell-Ausgaben: dort steht am Anfang, was die Zelle tun wollte.

    Der Byte-Deckel ist kein Beiwerk. Vierzig *Zeilen* sind keine vierzig
    begrenzten Dinge: ein einzelnes ``print(json.dumps(df.to_dict()))`` erzeugt
    eine Zeile von mehreren Megabyte. Ohne Deckel landete die vollständig im
    Kontext des Agenten – genau das, was dieses Modul verhindern soll – und
    liefe zusätzlich durch sämtliche Redaktions-Regexes.
    """
    if not text:
        return Bounded("", False, 0, 0, 0)
    lines = split_lines(text)
    total = len(lines)
    kept = lines[:max_lines]
    truncated = total > len(kept)

    joined = "\n".join(kept)
    encoded = joined.encode("utf-8")
    if len(encoded) > max_bytes:
        joined = encoded[:max_bytes].decode("utf-8", errors="ignore")
        kept = split_lines(joined)
        truncated = True
        encoded = joined.encode("utf-8")

    return Bounded(
        text=joined,
        truncated=truncated,
        total_lines=total,
        returned_lines=len(kept),
        returned_bytes=len(encoded),
    )


def clip_bytes(text: str, max_bytes: int) -> Bounded:
    """Kürzt auf ``max_bytes`` vom Anfang her (für Quelldateien)."""
    if not text:
        return Bounded("", False, 0, 0, 0)
    encoded = text.encode("utf-8")
    total_lines = len(split_lines(text))
    if len(encoded) <= max_bytes:
        return Bounded(text, False, total_lines, total_lines, len(encoded))
    clipped = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return Bounded(
        text=clipped,
        truncated=True,
        total_lines=total_lines,
        returned_lines=len(split_lines(clipped)),
        returned_bytes=len(clipped.encode("utf-8")),
    )
