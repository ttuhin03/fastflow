"""API-Endpoints für persönliche API-Tokens.

- ``POST   /api/tokens``            Token erzeugen (Klartext genau einmal)
- ``GET    /api/tokens``            Eigene Tokens auflisten (Admins: alle)
- ``DELETE /api/tokens/{token_id}`` Token widerrufen

Diese Endpoints sind bewusst **session-only**: sie hängen an
:func:`app.auth.auth.get_current_user`, das ausschließlich Session-JWTs aus einem
OAuth-Login akzeptiert. Ein API-Token kann damit kein weiteres Token erzeugen
oder fremde Tokens widerrufen – andernfalls wäre ein einmal entwendetes Token
beliebig verlängerbar und der Widerruf wirkungslos.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, select, update

from app.auth import get_current_user
from app.auth.principal import scopes_for_role
from app.core.api_token_hash import generate_api_token
from app.core.database import get_session, retry_on_sqlite_io
from app.core.errors import get_500_detail
from app.middleware.rate_limiting import limiter
from app.models import ApiToken, ApiTokenScope, User, UserRole
from app.services.audit import log_audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tokens", tags=["tokens"])

LABEL_MAX_LENGTH = 100
DEFAULT_EXPIRY_DAYS = 90
MAX_EXPIRY_DAYS = 365
MAX_ACTIVE_TOKENS_PER_USER = 20
"""Obergrenze aktiver Tokens je Nutzer – begrenzt sowohl den Schaden eines
kompromittierten Kontos als auch unbegrenztes Zeilenwachstum."""


class CreateApiTokenRequest(BaseModel):
    """Body für ``POST /api/tokens``."""

    label: str = Field(..., description="Bezeichnung, z.B. 'CI nightly'")
    scopes: List[ApiTokenScope] = Field(..., description="Gewünschte Scopes (mindestens einer)")
    expires_in_days: int = Field(
        default=DEFAULT_EXPIRY_DAYS,
        ge=1,
        le=MAX_EXPIRY_DAYS,
        description=f"Gültigkeitsdauer in Tagen (1–{MAX_EXPIRY_DAYS}, Standard {DEFAULT_EXPIRY_DAYS})",
    )

    @field_validator("label")
    @classmethod
    def _validate_label(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("label darf nicht leer sein")
        if len(cleaned) > LABEL_MAX_LENGTH:
            raise ValueError(f"label darf maximal {LABEL_MAX_LENGTH} Zeichen haben")
        return cleaned

    @field_validator("scopes")
    @classmethod
    def _validate_scopes(cls, value: List[ApiTokenScope]) -> List[ApiTokenScope]:
        if not value:
            raise ValueError("scopes darf nicht leer sein")
        # Reihenfolge stabil halten, Duplikate entfernen (sonst stünde ein Scope
        # mehrfach in der gespeicherten Liste).
        unique = list(dict.fromkeys(value))
        return unique


class ApiTokenItem(BaseModel):
    """Metadaten eines Tokens. Enthält nie den Token-Wert."""

    id: str
    label: str
    prefix: str
    scopes: List[str]
    created_at: str
    expires_at: str
    last_used_at: Optional[str] = None
    revoked_at: Optional[str] = None
    expired: bool
    username: Optional[str] = Field(
        default=None,
        description="Besitzer – nur befüllt, wenn ein Admin fremde Tokens sieht",
    )


class ApiTokenListResponse(BaseModel):
    """Antwort für ``GET /api/tokens``."""

    tokens: List[ApiTokenItem]
    available_scopes: List[str] = Field(
        description="Scopes, die die Rolle des aufrufenden Nutzers vergeben darf"
    )
    max_expiry_days: int = MAX_EXPIRY_DAYS
    default_expiry_days: int = DEFAULT_EXPIRY_DAYS


class CreateApiTokenResponse(BaseModel):
    """Antwort für ``POST /api/tokens``.

    ``token`` ist der einzige Moment, in dem der Klartext existiert – er wird
    nicht gespeichert und kann nicht erneut abgerufen werden.
    """

    token: str
    id: str
    label: str
    prefix: str
    scopes: List[str]
    expires_at: str


def _as_utc(value: datetime) -> datetime:
    """Normalisiert einen DB-Zeitstempel auf UTC (SQLite liefert naiv zurück)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _iso(value: Optional[datetime]) -> Optional[str]:
    """ISO-8601-Darstellung mit Zeitzonen-Offset.

    Der Offset ist nicht kosmetisch: nach ECMA-262 interpretiert ``new Date()``
    eine Datums-Zeit-Angabe *ohne* Offset als **lokale** Zeit. Ohne ihn zeigte
    die UI jeden Zeitstempel um den Zonenversatz verschoben an – in Berlin zwei
    Stunden, in Auckland dreizehn – und ein Token in seiner letzten Stunde
    erschiene als bereits abgelaufen, während die API expired=false meldet.
    """
    return _as_utc(value).isoformat() if value else None


def _to_item(token: ApiToken, now: datetime, owner_username: Optional[str] = None) -> ApiTokenItem:
    """Wandelt eine Zeile in die API-Darstellung."""
    return ApiTokenItem(
        id=str(token.id),
        label=token.label,
        prefix=token.prefix,
        scopes=list(token.scopes or []),
        created_at=_iso(token.created_at) or "",
        expires_at=_iso(token.expires_at) or "",
        last_used_at=_iso(token.last_used_at),
        revoked_at=_iso(token.revoked_at),
        expired=_as_utc(token.expires_at) <= now,
        username=owner_username,
    )


@router.post("", response_model=CreateApiTokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_api_token(
    request: Request,
    payload: CreateApiTokenRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> CreateApiTokenResponse:
    """Erzeugt ein neues API-Token für den aufrufenden Nutzer.

    Die angeforderten Scopes müssen vollständig in dem liegen, was die Rolle des
    Nutzers zulässt – ein READONLY-Nutzer kann also kein Token mit ``run``
    erzeugen. Der Klartext wird ausschließlich hier zurückgegeben.
    """
    allowed = scopes_for_role(current_user.role)
    requested = set(payload.scopes)
    forbidden = sorted(scope.value for scope in requested - allowed)
    if forbidden:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Rolle {current_user.role.value} darf folgende Scopes nicht vergeben: "
                f"{', '.join(forbidden)}"
            ),
        )

    now = datetime.now(timezone.utc)

    def _count_active() -> int:
        return len(
            retry_on_sqlite_io(
                lambda: session.exec(
                    select(ApiToken).where(
                        ApiToken.user_id == current_user.id,
                        ApiToken.revoked_at.is_(None),
                        ApiToken.expires_at > now,
                    )
                ).all(),
                session=session,
            )
        )

    def _too_many() -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Maximal {MAX_ACTIVE_TOKENS_PER_USER} aktive Tokens je Nutzer. "
                "Bitte zuerst ein bestehendes Token widerrufen."
            ),
        )

    if _count_active() >= MAX_ACTIVE_TOKENS_PER_USER:
        raise _too_many()

    generated = generate_api_token()
    token_row = ApiToken(
        token_hash=generated.token_hash,
        prefix=generated.prefix,
        label=payload.label,
        user_id=current_user.id,
        scopes=[scope.value for scope in payload.scopes],
        expires_at=now + timedelta(days=payload.expires_in_days),
        created_at=now,
    )

    try:
        session.add(token_row)
        session.commit()
        session.refresh(token_row)
        # Erneut zählen, nachdem die Zeile steht: zwischen Prüfung und Insert
        # können parallele Requests dieselbe Zahl gelesen haben. Ein reines
        # check-then-act ließe beide durch und das Limit hielte genau dann
        # nicht, wenn es zählt – bei einem kompromittierten Konto.
        if _count_active() > MAX_ACTIVE_TOKENS_PER_USER:
            session.delete(token_row)
            session.commit()
            raise _too_many()
    except HTTPException:
        raise
    except Exception as exc:
        session.rollback()
        logger.exception("API-Token konnte nicht angelegt werden")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=get_500_detail(exc),
        )

    # Bewusst ohne Token-Wert und ohne Digest: der Audit-Eintrag identifiziert das
    # Token über id und prefix.
    log_audit(
        session,
        "api_token_create",
        "api_token",
        str(token_row.id),
        details={
            "label": token_row.label,
            "prefix": token_row.prefix,
            "scopes": list(token_row.scopes or []),
            "expires_at": _iso(token_row.expires_at),
        },
        user=current_user,
    )
    logger.info(
        "API-Token angelegt: id=%s prefix=%s user=%s scopes=%s",
        token_row.id,
        token_row.prefix,
        current_user.username,
        ",".join(token_row.scopes or []),
    )

    return CreateApiTokenResponse(
        token=generated.token,
        id=str(token_row.id),
        label=token_row.label,
        prefix=token_row.prefix,
        scopes=list(token_row.scopes or []),
        expires_at=_iso(token_row.expires_at) or "",
    )


@router.get("", response_model=ApiTokenListResponse)
async def list_api_tokens(
    include_revoked: bool = Query(
        default=False, description="Widerrufene Tokens mit ausgeben"
    ),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> ApiTokenListResponse:
    """Listet die eigenen Tokens auf; Admins sehen die aller Nutzer.

    Gibt ausschließlich Metadaten zurück – der Token-Wert existiert nach der
    Erzeugung nirgends mehr.
    """
    is_admin = current_user.role == UserRole.ADMIN
    allowed_scopes = scopes_for_role(current_user.role)
    filters = [] if is_admin else [ApiToken.user_id == current_user.id]
    if not include_revoked:
        filters.append(ApiToken.revoked_at.is_(None))

    statement = select(ApiToken)
    if filters:
        statement = statement.where(*filters)
    statement = statement.order_by(ApiToken.created_at.desc())

    rows = retry_on_sqlite_io(lambda: session.exec(statement).all(), session=session)

    # Nur für die Admin-Ansicht: Besitzernamen in einer Query nachladen, statt je
    # Zeile einzeln (N+1).
    usernames: Dict[UUID, str] = {}
    if is_admin and rows:
        owner_ids = {row.user_id for row in rows}
        owners = retry_on_sqlite_io(
            lambda: session.exec(select(User).where(User.id.in_(owner_ids))).all(),
            session=session,
        )
        usernames = {owner.id: owner.username for owner in owners}

    now = datetime.now(timezone.utc)
    items = [
        _to_item(
            row,
            now,
            owner_username=usernames.get(row.user_id) if is_admin else None,
        )
        for row in rows
    ]

    return ApiTokenListResponse(
        tokens=items,
        # Reihenfolge der Enum-Deklaration statt alphabetisch: ApiTokenScope ist
        # nach aufsteigendem Risiko deklariert (read < logs/source < run). Die UI
        # zeigt die Scopes in dieser Reihenfolge an, der harmloseste zuerst.
        available_scopes=[
            scope.value for scope in ApiTokenScope if scope in allowed_scopes
        ],
    )


@router.delete("/{token_id}", response_model=Dict[str, Any])
async def revoke_api_token(
    token_id: UUID,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Widerruft ein Token.

    Kein Hard-Delete: ``revoked_at`` wird gesetzt, damit bestehende
    Audit-Einträge weiterhin auf eine existierende Zeile zeigen.

    Der Widerruf erfolgt als eine atomare UPDATE-Anweisung mit
    ``revoked_at IS NULL`` in der WHERE-Klausel. Ein SELECT gefolgt von einem
    separaten UPDATE wäre unter Postgres READ COMMITTED nicht race-sicher: zwei
    gleichzeitige Requests könnten beide die Prüfung passieren und beide einen
    Audit-Eintrag schreiben. So schreibt genau einer.
    """
    ownership = [] if current_user.role == UserRole.ADMIN else [ApiToken.user_id == current_user.id]

    existing = retry_on_sqlite_io(
        lambda: session.exec(
            select(ApiToken).where(ApiToken.id == token_id, *ownership)
        ).first(),
        session=session,
    )
    # Fremde und nicht existierende Tokens ergeben dieselbe Antwort: ein Nutzer
    # soll nicht herausfinden können, welche Token-IDs anderswo existieren.
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Token nicht gefunden: {token_id}",
        )

    now = datetime.now(timezone.utc)
    try:
        result = retry_on_sqlite_io(
            lambda: session.exec(
                update(ApiToken)
                .where(ApiToken.id == token_id, ApiToken.revoked_at.is_(None), *ownership)
                .values(revoked_at=now)
            ),
            session=session,
        )
        newly_revoked = result.rowcount == 1
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.exception("API-Token konnte nicht widerrufen werden: %s", token_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=get_500_detail(exc),
        )

    if newly_revoked:
        log_audit(
            session,
            "api_token_revoke",
            "api_token",
            str(token_id),
            details={"label": existing.label, "prefix": existing.prefix},
            user=current_user,
        )
        logger.info(
            "API-Token widerrufen: id=%s prefix=%s durch=%s",
            token_id,
            existing.prefix,
            current_user.username,
        )

    # Idempotent: ein bereits widerrufenes Token ist kein Fehlerfall.
    return {"status": "revoked", "id": str(token_id)}
