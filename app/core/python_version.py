"""
Validierung von Python-Versionsangaben aus Pipeline-Metadaten.

`python_version` aus pipeline.json wird als Wert von `uv --python` an Subprozesse
weitergereicht – im Worker-Container (`uv run`) und, beim Pre-Heating, im
Orchestrator selbst (`uv pip compile`, `uv python install`).

Sicherheitsrelevant: uv akzeptiert dort nicht nur Versionsnummern, sondern auch
Pfade zu Interpretern – und *führt die angegebene Datei aus*, um sie zu
inspizieren. Das Pipeline-Repository ist im Orchestrator gemountet und Git
erhält das Execute-Bit, also wäre

    {"python_version": "/app/pipelines/demo/payload.sh"}

eine direkte Codeausführung im Orchestrator – ausserhalb jeder
Container-Isolation, mit Zugriff auf ENCRYPTION_KEY, JWT_SECRET_KEY, alle
Secrets und den Docker-Socket-Proxy. Ein führendes "-" wäre ausserdem
Argument-Injection in die uv-Kommandozeile.

Deshalb wird der Wert hier auf ein enges Muster eingeschränkt, bevor er
irgendeinen Subprozess erreicht: eine numerische Version, optional mit einem
Implementierungs-Präfix aus einer festen Whitelist.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Von uv unterstützte Implementierungs-Präfixe (z. B. "cpython@3.12", "pypy-3.10").
# Bewusst eine Whitelist: alles andere – insbesondere Pfade und Optionen – wird
# abgelehnt, statt zu versuchen, gefährliche Eingaben zu erkennen.
_PYTHON_VERSION_PATTERN = re.compile(
    r"""
    ^
    (?:(?:cpython|pypy|graalpy)[-@])?   # optionale Implementierung
    \d{1,2}\.\d{1,3}                    # Major.Minor (z. B. 3.11)
    (?:\.\d{1,4})?                      # optionale Patch-Version
    $
    """,
    re.VERBOSE,
)


class UnsafePythonVersionError(ValueError):
    """Eine Python-Versionsangabe hat das erlaubte Muster nicht erfüllt."""


def is_valid_python_version(value: object) -> bool:
    """
    Prüft, ob `value` eine akzeptierte Python-Versionsangabe ist.

    Akzeptiert: "3.11", "3.12.1", "cpython@3.12", "pypy-3.10".
    Abgelehnt: Pfade, Optionen ("--foo"), Glob-/Shell-Zeichen, leere Werte.
    """
    if not isinstance(value, str):
        return False
    return _PYTHON_VERSION_PATTERN.match(value.strip()) is not None


def sanitize_python_version(value: object, *, source: str) -> Optional[str]:
    """
    Normalisiert eine Versionsangabe beim Einlesen von Metadaten.

    Für den Lese-Pfad gedacht (pipeline.json): ein ungültiger Wert darf die
    Pipeline-Discovery nicht abbrechen, sonst macht eine einzige kaputte
    pipeline.json alle anderen Pipelines unsichtbar. Stattdessen wird der Wert
    verworfen und geloggt; der Aufrufer fällt auf DEFAULT_PYTHON_VERSION zurück.

    Args:
        value: Rohwert aus der Metadaten-Datei.
        source: Herkunft für die Log-Meldung (z. B. der Pipeline-Name).

    Returns:
        Die getrimmte Version, oder None wenn sie fehlt oder unzulässig ist.
    """
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    if not is_valid_python_version(value):
        logger.warning(
            "python_version %r in %s ist unzulässig und wird ignoriert "
            "(erlaubt: z. B. 3.11, 3.12.1, cpython@3.12). "
            "Es gilt DEFAULT_PYTHON_VERSION.",
            value,
            source,
        )
        return None
    return str(value).strip()


def ensure_safe_python_version(value: object) -> str:
    """
    Prüft eine Versionsangabe unmittelbar vor der Übergabe an einen Subprozess.

    Defense in Depth: der Wert ist an dieser Stelle normalerweise schon durch
    sanitize_python_version gegangen. Die Prüfung wird trotzdem wiederholt,
    damit ein künftiger Pfad, der die Metadaten umgeht (oder ein direkt
    gesetztes DEFAULT_PYTHON_VERSION), nicht ungeprüft in `uv --python` landet.

    Raises:
        UnsafePythonVersionError: Wenn der Wert das erlaubte Muster nicht erfüllt.
    """
    if not is_valid_python_version(value):
        raise UnsafePythonVersionError(
            f"Unzulässige Python-Version {value!r}: erlaubt sind nur Angaben wie "
            "'3.11', '3.12.1' oder 'cpython@3.12' – keine Pfade und keine Optionen."
        )
    return str(value).strip()
