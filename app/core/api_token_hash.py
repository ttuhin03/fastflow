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

    **SHA-256 ist hier richtig, kein Versäumnis.** CodeQL meldet an dieser Stelle
    ``py/weak-sensitive-data-hashing`` ("Sensitive data (password) …"); die Regel
    zielt auf Passwort-Hashing und greift hier über den Variablennamen ``secret``
    in :func:`generate_api_token`. Drei Gründe, warum Argon2/bcrypt an dieser
    Stelle nicht nur unnötig, sondern schädlich wären:

    1. **Es gibt keinen Suchraum.** Ein langsames KDF macht *Raten* teuer. Das
       lohnt bei Passwörtern, weil Menschen aus einem winzigen Raum wählen. Der
       Eingabewert hier stammt aus ``secrets.token_urlsafe(32)`` – 256 Bit aus
       dem CSPRNG des Betriebssystems. Jeden Versuch um Faktor 100.000 zu
       verteuern ändert nichts, wenn man 2^255 Versuche bräuchte.
    2. **Es läuft pro Request, nicht pro Login.** Jeder authentifizierte
       API-Aufruf durchläuft diese Funktion. Argon2id mit sinnvollen Parametern
       kostet ~100 ms CPU und zweistellige MB RAM – das wäre ein
       Selbstbedienungs-DoS: wer Müll mit ``ffp_``-Form schickt, verbrennt
       Serverleistung, bevor der Wert überhaupt abgelehnt werden kann.
    3. **Ein gesalzenes KDF verträgt sich nicht mit dem Nachschlagen.** Der
       Digest *ist* der indizierte Suchschlüssel (siehe
       ``ApiToken.token_hash``). Mit einem Salt pro Zeile ließe sich die
       passende Zeile nicht finden – man müsste das KDF gegen *jede* Zeile
       ausführen, oder doch wieder einen ungesalzenen Index führen.

    Dasselbe Verfahren nutzt ``app.core.notification_api_key_hash`` seit jeher,
    und es entspricht dem, was GitHub, Stripe und AWS für API-Schlüssel tun.

    ``usedforsecurity=False`` markiert die Verwendung zusätzlich als
    Nicht-Passwort-Digest (relevant für FIPS-Builds).
    """
    # Der Marker unten bleibt für den Fall, dass Code Scanning einmal auf
    # advanced setup umgestellt wird. Wirkung hat er derzeit nicht: CodeQL
    # sammelt Suppression-Kommentare zwar als suppressions[] ins SARIF, das
    # default setup wertet sie aber nicht aus – dafür bräuchte es die
    # AlertSuppression-Query plus eine Dismiss-Action. Der Befund ist deshalb
    # in Code Scanning selbst als "false positive" abgelehnt (Alert #183).
    #
    # Die vier Taint-Pfade starten übrigens alle am Test-Helper _api_token()
    # in tests/test_auth_revocation.py: CodeQL stuft dessen Rückgabe allein
    # wegen des Namens als Passwort ein, nicht wegen irgendetwas an der Krypto.
    # codeql[py/weak-sensitive-data-hashing]
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
