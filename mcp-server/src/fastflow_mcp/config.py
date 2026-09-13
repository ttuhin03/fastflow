"""Konfiguration des MCP-Servers aus Umgebungsvariablen.

Der Server hält genau ein Geheimnis: das API-Token. Es wird ausschließlich als
``Authorization``-Header verwendet und darf weder in Logs noch in Tracebacks
erscheinen – deshalb maskiert :class:`Config` es in ``repr``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlparse

TOKEN_PREFIX = "ffp_"

DEFAULT_TIMEOUT_SECONDS = 30.0
MIN_TIMEOUT_SECONDS = 1.0
MAX_TIMEOUT_SECONDS = 300.0


class ConfigError(RuntimeError):
    """Fehlende oder unbrauchbare Konfiguration.

    Wird beim Start ausgelöst, bevor eine Verbindung versucht wird – ein
    MCP-Client soll die Ursache im stderr des Prozesses lesen können, statt
    später an unklaren Tool-Fehlern zu scheitern.
    """


def _bool_env(source: Mapping[str, str], name: str, default: bool) -> bool:
    raw = source.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _float_env(
    source: Mapping[str, str], name: str, default: float, minimum: float, maximum: float
) -> float:
    raw = source.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} ist keine Zahl: {raw!r}") from exc
    if not (minimum <= value <= maximum):
        raise ConfigError(f"{name} muss zwischen {minimum} und {maximum} liegen, war {value}")
    return value


@dataclass(frozen=True)
class Config:
    """Laufzeitkonfiguration des Servers."""

    base_url: str
    token: str = field(repr=False)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    verify_tls: bool = True
    redact_secrets: bool = True

    @property
    def api_url(self) -> str:
        """Basis-URL der REST-API (ohne abschließenden Schrägstrich)."""
        return f"{self.base_url}/api"

    def __repr__(self) -> str:  # pragma: no cover - triviale Formatierung
        # Nicht nur weglassen, sondern sichtbar maskieren: ein fehlendes Feld
        # sähe im Traceback aus wie "Token nicht gesetzt".
        return (
            f"Config(base_url={self.base_url!r}, token='***', "
            f"timeout_seconds={self.timeout_seconds!r}, verify_tls={self.verify_tls!r}, "
            f"redact_secrets={self.redact_secrets!r})"
        )


def load_config(env: Mapping[str, str] | None = None) -> Config:
    """Liest die Konfiguration aus der Umgebung.

    Args:
        env: Alternative Umgebung (für Tests). Default: ``os.environ``.

    Raises:
        ConfigError: Wenn URL oder Token fehlen oder unbrauchbar sind.
    """
    source = os.environ if env is None else env

    raw_url = (source.get("FASTFLOW_URL") or "").strip().rstrip("/")
    if not raw_url:
        raise ConfigError(
            "FASTFLOW_URL ist nicht gesetzt. Erwartet wird die Basis-URL der "
            "Fast-Flow-Instanz, z.B. https://fastflow.example.com"
        )
    parsed = urlparse(raw_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ConfigError(
            f"FASTFLOW_URL muss mit http:// oder https:// beginnen, war {raw_url!r}"
        )

    token = (source.get("FASTFLOW_TOKEN") or "").strip()
    if not token:
        raise ConfigError(
            "FASTFLOW_TOKEN ist nicht gesetzt. Ein persönliches API-Token wird "
            "in der Fast-Flow-UI unter Einstellungen → API-Tokens erzeugt."
        )
    if not token.startswith(TOKEN_PREFIX):
        # Kein harter Fehler: die API akzeptiert auch ein Session-JWT. Das läuft
        # aber nach wenigen Stunden ab und taugt nicht für einen Dauerbetrieb,
        # deshalb der explizite Hinweis.
        raise ConfigError(
            f"FASTFLOW_TOKEN sieht nicht wie ein API-Token aus (erwartet Präfix "
            f"{TOKEN_PREFIX!r}). Ein Session-JWT aus dem Browser läuft nach wenigen "
            f"Stunden ab – bitte unter Einstellungen → API-Tokens ein Token erzeugen."
        )

    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        # Kein Abbruch (interne Netze ohne TLS kommen vor), aber der Nutzer soll
        # wissen, dass sein Token dann im Klartext über die Leitung geht.
        import sys

        print(
            f"WARNUNG: FASTFLOW_URL nutzt http:// gegen {parsed.hostname}. "
            "Das API-Token wird unverschlüsselt übertragen.",
            file=sys.stderr,
        )

    return Config(
        base_url=raw_url,
        token=token,
        timeout_seconds=_float_env(
            source,
            "FASTFLOW_TIMEOUT_SECONDS",
            DEFAULT_TIMEOUT_SECONDS,
            MIN_TIMEOUT_SECONDS,
            MAX_TIMEOUT_SECONDS,
        ),
        verify_tls=_bool_env(source, "FASTFLOW_VERIFY_TLS", True),
        redact_secrets=_bool_env(source, "FASTFLOW_REDACT_SECRETS", True),
    )
