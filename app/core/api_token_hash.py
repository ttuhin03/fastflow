"""Format, Erzeugung und Digest persönlicher API-Tokens.

Aufbau eines Tokens::

    ffp_<prefix>_<secret>
    |    |        |
    |    |        +-- 43 Zeichen aus secrets.token_urlsafe(32): der eigentliche
    |    |            Geheimnisanteil, nur dem Besitzer bekannt
    |    +----------- 8 Zeichen, unabhängig gezogen: öffentlicher Identifier,
    |                 wird in der UI angezeigt, damit ein Token ohne Kenntnis
    |                 des Geheimnisses wiedererkannt werden kann
    +---------------- festes Präfix, macht Tokens für Secret-Scanner auffindbar
                      (siehe Regel "fastflow-api-token" in .gitleaks.toml)

Der Prefix-Teil ist bewusst eine eigene Zufallsziehung und kein Ausschnitt des
Geheimnisses: er darf offen angezeigt und geloggt werden, ohne den Suchraum des
Geheimnisses zu verkleinern.

Gespeichert wird ausschließlich der SHA-256-Digest des *vollständigen* Tokens.
Wie in app.core.notification_api_key_hash ist das kein Passwort-Hashing: der
Eingabewert stammt aus secrets.token_urlsafe und besitzt volle Entropie, ein
reiner SHA-256 ist hier der Standard für einen nicht umkehrbaren
Nachschlage-Schlüssel (Argon2/bcrypt gehören zu Passwörtern).
"""

from __future__ import annotations

import hashlib
import re
import secrets
from typing import NamedTuple

TOKEN_PREFIX = "ffp_"
"""Festes Erkennungspräfix aller Fast-Flow-API-Tokens."""

_PREFIX_CHARS = 8
_SECRET_BYTES = 32

# token_urlsafe(32) liefert 43 Zeichen aus [A-Za-z0-9_-]. Das Muster wird vor jedem
# Datenbankzugriff geprüft: syntaktisch unmögliche Werte kosten so keine Query.
TOKEN_PATTERN = re.compile(
    r"^ffp_[A-Za-z0-9_-]{%d}_[A-Za-z0-9_-]{43}$" % _PREFIX_CHARS
)


class GeneratedApiToken(NamedTuple):
    """Ergebnis von :func:`generate_api_token`.

    ``token`` ist der einzige Moment, in dem der Klartext existiert – er wird
    nirgends gespeichert und darf nur einmal an den Aufrufer zurückgegeben werden.
    """

    token: str
    prefix: str
    token_hash: str


def digest_api_token(value: str) -> str:
    """Liefert den Hex-Digest, der als ``ApiToken.token_hash`` gespeichert wird.

    ``usedforsecurity=False`` markiert die Verwendung als Nicht-Passwort-Digest
    (relevant für FIPS-Builds und für Reviewer, die nach Passwort-Hashing suchen).
    """
    return hashlib.sha256(value.encode("utf-8"), usedforsecurity=False).hexdigest()


def generate_api_token() -> GeneratedApiToken:
    """Erzeugt ein neues Token samt öffentlichem Prefix und Digest."""
    # token_urlsafe(6) liefert 8 Zeichen – exakt die gewünschte Prefix-Länge.
    prefix = secrets.token_urlsafe(6)
    secret = secrets.token_urlsafe(_SECRET_BYTES)
    token = f"{TOKEN_PREFIX}{prefix}_{secret}"
    return GeneratedApiToken(token=token, prefix=prefix, token_hash=digest_api_token(token))


def looks_like_api_token(value: str) -> bool:
    """True, wenn ``value`` syntaktisch ein API-Token ist.

    Nur eine Formatprüfung – sie sagt nichts darüber aus, ob das Token existiert,
    gültig oder widerrufen ist. Dient dazu, den Token-Pfad vom JWT-Pfad zu trennen,
    bevor irgendetwas als JWT interpretiert wird.
    """
    return bool(value) and TOKEN_PATTERN.match(value) is not None
