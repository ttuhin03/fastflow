"""Principal-Auflösung für Session- *und* Token-Authentifizierung.

Bestehende Endpoints hängen an :func:`app.auth.auth.get_current_user` und
akzeptieren ausschließlich Session-JWTs aus einem OAuth-Login. Dieses Modul legt
einen Principal-Begriff darüber, der zusätzlich persönliche API-Tokens versteht,
ohne den bisherigen Pfad zu verändern: Endpoints, die Tokens akzeptieren sollen,
tauschen lediglich ihre Dependency gegen :func:`require_scope`.

Zentrale Regel: die Verzweigung zwischen Token- und Session-Pfad erfolgt am
festen Präfix ``ffp_``, **bevor** irgendetwas als JWT interpretiert wird. Ein
API-Token darf nie in :func:`app.auth.auth.get_session_by_token` landen und ein
Session-JWT nie gegen die Token-Tabelle geprüft werden.

Die effektive Berechtigung ist immer die Schnittmenge aus den Scopes des Tokens
und den Scopes, die die Rolle des Besitzers zulässt. Ein READONLY-Nutzer kann
damit kein Token mit ``run`` benutzen, selbst wenn ein solcher Scope – etwa nach
einer Rollen-Herabstufung – noch in der Zeile steht.
"""

from __future__ import annotations

import logging
import secrets as secrets_module
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, FrozenSet, Iterable, Literal, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlmodel import Session, select, update

from app.auth.auth import get_current_user, security
from app.core.api_token_hash import digest_api_token, looks_like_api_token
from app.core.database import get_session, retry_on_sqlite_io
from app.models import ApiToken, ApiTokenScope, User, UserRole, UserStatus

logger = logging.getLogger(__name__)

AuthKind = Literal["session", "token"]

# Welche Scopes eine Rolle überhaupt gewähren darf. READONLY erhält alle lesenden
# Scopes; RUN erfordert Schreibrechte. Ein Admin-Scope existiert bewusst nicht –
# administrative Endpoints bleiben session-only (siehe ApiTokenScope).
SCOPES_BY_ROLE: dict[UserRole, FrozenSet[ApiTokenScope]] = {
    UserRole.READONLY: frozenset({ApiTokenScope.READ, ApiTokenScope.LOGS, ApiTokenScope.SOURCE}),
    UserRole.WRITE: frozenset(
        {ApiTokenScope.READ, ApiTokenScope.LOGS, ApiTokenScope.SOURCE, ApiTokenScope.RUN}
    ),
    UserRole.ADMIN: frozenset(
        {ApiTokenScope.READ, ApiTokenScope.LOGS, ApiTokenScope.SOURCE, ApiTokenScope.RUN}
    ),
}

# Einheitliche Fehlermeldung für jeden fehlgeschlagenen Token-Versuch. Unbekannt,
# widerrufen und abgelaufen werden absichtlich nicht unterschieden, damit die
# Antwort keine Aussage über die Existenz eines Tokens zulässt.
_INVALID_TOKEN_DETAIL = "Ungültiges, abgelaufenes oder widerrufenes API-Token"

# Mindestabstand zwischen zwei Schreibvorgängen auf last_used_at. Ohne Drosselung
# erzeugt jeder lesende Request einen Write – auf SQLite ein spürbarer Kostenfaktor.
LAST_USED_THROTTLE_SECONDS = 60


def scopes_for_role(role: UserRole) -> FrozenSet[ApiTokenScope]:
    """Liefert die Scopes, die eine Rolle gewähren darf.

    Unbekannte Rollen erhalten die leere Menge (fail-closed), damit eine künftig
    ergänzte Rolle nicht versehentlich alles darf.
    """
    return SCOPES_BY_ROLE.get(role, frozenset())


def parse_scopes(raw: Iterable[str]) -> FrozenSet[ApiTokenScope]:
    """Wandelt gespeicherte Scope-Strings in Enum-Werte.

    Unbekannte Werte werden verworfen statt zu einem Fehler zu führen: wird ein
    Scope in einer späteren Version entfernt, sollen bestehende Tokens mit ihren
    verbleibenden Scopes weiterarbeiten, nicht hart ausfallen.
    """
    parsed: set[ApiTokenScope] = set()
    for value in raw or ():
        try:
            parsed.add(ApiTokenScope(value))
        except ValueError:
            logger.debug("Unbekannter Scope in api_tokens verworfen: %r", value)
    return frozenset(parsed)


@dataclass(frozen=True)
class Principal:
    """Wer stellt diesen Request, und was darf er.

    ``scopes`` ist bereits die effektive Menge (Token-Scopes geschnitten mit den
    Scopes der Rolle); bei Session-Authentifizierung sind es alle Scopes der
    Rolle. ``token_id`` ist nur bei ``auth_kind == "token"`` gesetzt und wird für
    die Audit-Attribution verwendet.
    """

    user: User
    scopes: FrozenSet[ApiTokenScope]
    auth_kind: AuthKind
    token_id: Optional[UUID] = None
    token_label: Optional[str] = None

    def has_scope(self, scope: ApiTokenScope) -> bool:
        """True, wenn dieser Principal den Scope besitzt."""
        return scope in self.scopes

    def audit_details(self) -> dict:
        """Zusatzfelder für :func:`app.services.audit.log_audit`.

        Ohne diese Attribution lässt sich im Audit-Log nicht unterscheiden, ob
        eine Aktion von einem Menschen im Browser oder von einem automatisierten
        Client kam – mit wachsender Automatisierung verliert das Log sonst
        seinen Wert.
        """
        details = {"auth_kind": self.auth_kind}
        if self.token_id is not None:
            details["token_id"] = str(self.token_id)
        if self.token_label:
            details["token_label"] = self.token_label
        return details


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Normalisiert einen DB-Zeitstempel auf zeitzonen-bewusstes UTC.

    SQLite liefert naive datetimes zurück; die Anwendung schreibt durchgehend UTC
    (siehe ``_utc_now`` in app.models). Ohne diese Normalisierung schlägt jeder
    Vergleich mit ``datetime.now(timezone.utc)`` mit einem TypeError fehl.
    """
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _touch_last_used(db_session: Session, token_row: ApiToken, now: datetime) -> None:
    """Schreibt ``last_used_at`` – gedrosselt und niemals request-fatal.

    Ein fehlgeschlagener Statistik-Write darf einen ansonsten gültigen Request
    nicht scheitern lassen (z.B. read-only-Replica oder gesperrte SQLite-Datei).
    Verwendet ein gezieltes UPDATE statt einer ORM-Mutation, damit ausschließlich
    diese eine Spalte geschrieben wird.
    """
    previous = _as_utc(token_row.last_used_at)
    if previous is not None and (now - previous).total_seconds() < LAST_USED_THROTTLE_SECONDS:
        return
    try:
        retry_on_sqlite_io(
            lambda: db_session.exec(
                update(ApiToken).where(ApiToken.id == token_row.id).values(last_used_at=now)
            ),
            session=db_session,
        )
        db_session.commit()
    except Exception as exc:  # pragma: no cover - reiner Best-Effort-Pfad
        logger.debug("last_used_at konnte nicht aktualisiert werden: %s", exc)
        try:
            db_session.rollback()
        except Exception:
            pass


def _invalid_token() -> HTTPException:
    """Einheitliche 401-Antwort für jeden fehlgeschlagenen Token-Versuch."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_INVALID_TOKEN_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _principal_from_api_token(db_session: Session, raw_token: str) -> Principal:
    """Löst ein API-Token zu einem Principal auf.

    Der Nachschlag erfolgt über den indizierten SHA-256-Digest; Ablauf und
    Widerruf werden in derselben Query gefiltert, damit keine ungültige Zeile
    überhaupt nach Python gelangt. Der anschließende ``compare_digest`` ist
    Redundanz für den Fall, dass die Query je durch eine unscharfe
    Vergleichssemantik ersetzt wird (etwa case-insensitive Collations).
    """
    digest = digest_api_token(raw_token)
    now = datetime.now(timezone.utc)

    statement = select(ApiToken).where(
        ApiToken.token_hash == digest,
        ApiToken.revoked_at.is_(None),
        ApiToken.expires_at > now,
    )
    token_row = retry_on_sqlite_io(lambda: db_session.exec(statement).first(), session=db_session)

    if token_row is None or not secrets_module.compare_digest(digest, token_row.token_hash):
        raise _invalid_token()

    user = retry_on_sqlite_io(
        lambda: db_session.exec(select(User).where(User.id == token_row.user_id)).first(),
        session=db_session,
    )
    # Blockierte und nicht freigegebene Nutzer verlieren ihre Tokens sofort mit –
    # dieselben Prüfungen wie im Session-Pfad (siehe get_current_user). Ein
    # verwaistes Token (Nutzer gelöscht) fällt hier ebenfalls raus: die Prüfung
    # ist die eigentliche Garantie, nicht das ON DELETE CASCADE der Migration.
    if (
        user is None
        or user.blocked
        or getattr(user, "status", UserStatus.ACTIVE) != UserStatus.ACTIVE
    ):
        raise _invalid_token()

    effective = parse_scopes(token_row.scopes) & scopes_for_role(user.role)
    if not effective:
        # Alle Scopes durch die Rolle entwertet: als Authentifizierungsfehler
        # behandeln, nicht als 403 – das Token ist faktisch wertlos.
        raise _invalid_token()

    _touch_last_used(db_session, token_row, now)

    return Principal(
        user=user,
        scopes=effective,
        auth_kind="token",
        token_id=token_row.id,
        token_label=token_row.label,
    )


async def get_principal(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db_session: Session = Depends(get_session),
) -> Principal:
    """Dependency: löst den Bearer-Wert zu einem :class:`Principal` auf.

    Akzeptiert beides – ein persönliches API-Token (Präfix ``ffp_``) und ein
    Session-JWT. Der Session-Pfad delegiert vollständig an
    :func:`app.auth.auth.get_current_user`, damit Sperr-, Status- und
    Session-Prüfungen nur an einer Stelle gepflegt werden.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentifizierung erforderlich",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw = credentials.credentials

    if looks_like_api_token(raw):
        return _principal_from_api_token(db_session, raw)

    user = await get_current_user(credentials=credentials, db_session=db_session)
    return Principal(
        user=user,
        scopes=scopes_for_role(user.role),
        auth_kind="session",
    )


def require_scope(*needed: ApiTokenScope) -> Callable[..., Principal]:
    """Dependency-Factory: verlangt alle angegebenen Scopes.

    Beispiel::

        @router.get("/runs")
        async def list_runs(principal: Principal = Depends(require_scope(ApiTokenScope.READ))):
            ...

    Bei Session-Authentifizierung greift die Prüfung ebenfalls – dort ergeben
    sich die Scopes aus der Rolle, ein READONLY-Nutzer scheitert also an
    ``RUN`` genauso wie ein entsprechend beschränktes Token.
    """
    if not needed:
        raise ValueError("require_scope benötigt mindestens einen Scope")

    async def _require(principal: Principal = Depends(get_principal)) -> Principal:
        missing = [scope.value for scope in needed if scope not in principal.scopes]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Fehlende Berechtigung: {', '.join(sorted(missing))}",
            )
        return principal

    return _require
