"""Maskierung offensichtlicher Zugangsdaten in Logs und Quelltext.

**Das ist eine Minderung, keine Garantie.** Erkannt werden Werte mit
charakteristischer Form – Token mit festem Präfix, private Schlüssel, JWTs,
Zuweisungen an Schlüsselwörter wie ``password=``. Ein Passwort, das in einer
Fehlermeldung als gewöhnlicher Satz auftaucht ("login failed for hunter2"),
sieht wie normaler Text aus und bleibt stehen.

Fast-Flow maskiert Logs serverseitig nicht (siehe ``app/api/logs.py``). Wer
Pipeline-Logs über einen Agenten liest, trifft damit eine bewusste
Entscheidung; dieser Filter senkt die Wahrscheinlichkeit eines Leaks, er
beseitigt sie nicht.
"""

from __future__ import annotations

import re
from typing import Final

PLACEHOLDER: Final = "[redacted]"

# Reihenfolge ist relevant: der Block für private Schlüssel muss vor den
# zeilenweisen Mustern greifen, sonst bleibt der Rumpf des Schlüssels stehen.
_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        # Der Rumpf ist als Zeichenklasse statt als `.*?` formuliert: ein lazy
        # `.` unter DOTALL scannt bei jedem BEGIN ohne passendes END bis zum
        # Eingabeende, und jedes weitere BEGIN ist eine neue Startposition.
        # 64 KB aus lauter BEGIN-Markern ohne END brauchten so 624 ms. Die
        # Klasse schließt `-` aus, sodass der Scan am nächsten Marker endet.
        "private-key-block",
        re.compile(
            r"-----BEGIN[ A-Z]*PRIVATE KEY-----[^-]*(?:-(?!----)[^-]*)*"
            r"-----END[ A-Z]*PRIVATE KEY-----",
        ),
    ),
    # Fast-Flow-eigene API-Tokens (app/core/api_token_hash.py).
    ("fastflow-token", re.compile(r"\bffp_[A-Za-z0-9_-]{8}_[A-Za-z0-9_-]{43}\b")),
    # GitHub: klassische und fine-grained Tokens.
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("github-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    # AWS Access Key IDs (der Secret Key hat keine erkennbare Form und wird nur
    # über die Zuweisungsregel unten erwischt).
    ("aws-access-key-id", re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b")),
    # Slack-Tokens.
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    # JSON Web Tokens (inkl. der Session-JWTs von Fast-Flow selbst).
    #
    # Die Obergrenzen sind kein Schönheitsfehler: `-` steht in der Klasse, ist
    # aber kein Wortzeichen, also matcht `\beyJ` in einer Folge wie `-eyJ-eyJ…`
    # an jeder Stelle, und ein offenes `{8,}` frisst dabei jedes Mal den Rest
    # der Eingabe. Gemessen: 64 KB in 1,14 s, 256 KB in 17,8 s. Mit einer
    # Obergrenze bleibt die Arbeit je Startposition konstant.
    (
        "jwt",
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{8,4096}\.eyJ[A-Za-z0-9_-]{8,4096}"
            r"\.[A-Za-z0-9_-]{8,4096}\b"
        ),
    ),
    # Zugangsdaten in URLs: https://user:secret@host -> nur das Passwort ersetzen.
    #
    # Das Schema wird als feste Alternative statt als `[a-zA-Z][a-zA-Z0-9+.-]*`
    # geschrieben. In der alten Form standen `.` und `-` in der Klasse, aber
    # nicht in `\b`: jeder Buchstabe nach einem Punkt war eine Startposition,
    # von der aus bis zum Eingabeende nach einem `://` gesucht wurde. Text wie
    # `a.a.a.…` – Hostnamen, Modulpfade, Versionsnummern – kostete dadurch
    # quadratisch: 0,55 s bei 32 KB, hochgerechnet 2,2 s beim 64-KB-Deckel.
    (
        "url-credentials",
        re.compile(
            r"(?P<prefix>\b(?:https?|ftps?|ssh|git|postgres(?:ql)?|mysql|mongodb|redis|amqps?)"
            r"://[^\s:/@]{1,256}:)[^\s@/]{1,256}(?=@)"
        ),
    ),
    # Zuweisungen an verräterische Schlüssel, in Form von key=value, key: value
    # und "key": "value". Fängt u.a. AWS Secret Keys und DB-Passwörter.
    (
        "credential-assignment",
        re.compile(
            r"(?P<prefix>(?i:password|passwd|secret|token|api[_-]?key|access[_-]?key"
            r"|client[_-]?secret|auth)\"?\s*[:=]\s*\"?)"
            r"(?P<value>[^\s\"',;]{4,})"
        ),
    ),
)


def _replace_keeping_prefix(match: re.Match[str]) -> str:
    """Ersetzt nur die Wertgruppe und behält den erklärenden Präfix.

    ``password=hunter2`` wird zu ``password=[redacted]`` statt zu ``[redacted]``:
    der Agent soll sehen, *dass* dort ein Passwort steht – nur nicht welches.
    """
    prefix = match.groupdict().get("prefix") or ""
    return f"{prefix}{PLACEHOLDER}"


def redact(text: str) -> str:
    """Ersetzt erkannte Zugangsdaten durch ``[redacted]``.

    Gibt ``text`` unverändert zurück, wenn nichts passt. Leere Eingaben und
    ``None``-artige Werte werden zu ``""`` normalisiert, damit Aufrufer keine
    Sonderfälle behandeln müssen.
    """
    if not text:
        return ""
    result = text
    for name, pattern in _PATTERNS:
        if "prefix" in pattern.groupindex:
            result = pattern.sub(_replace_keeping_prefix, result)
        else:
            result = pattern.sub(PLACEHOLDER, result)
        del name  # nur zur Lesbarkeit der Mustertabelle benannt
    return result


def redact_if(text: str, enabled: bool) -> str:
    """Wendet :func:`redact` an, wenn ``enabled`` gesetzt ist."""
    return redact(text) if enabled else (text or "")
