"""
User Management API Endpoints.

Dieses Modul enthält alle REST-API-Endpoints für Nutzermanagement:
- Nutzer auflisten
- Nutzer erstellen (direkt oder per Einladung)
- Nutzer aktualisieren
- Passwort zurücksetzen
- Nutzer blockieren/entblockieren
- Nutzer löschen
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlmodel import Session, select

from app.auth import get_current_user, require_admin, delete_all_user_sessions
from app.core.config import config
from app.core.database import get_session
from app.models import User, UserRole, UserStatus, Invitation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


def _user_status_value(user: User) -> str:
    """Status für API-Response: Enum-Wert (z. B. 'active') als String."""
    s = getattr(user, "status", UserStatus.ACTIVE)
    return s.value if isinstance(s, UserStatus) else str(s)


# Request/Response Models
class UserResponse(BaseModel):
    """Response-Model für Benutzer-Informationen."""
    id: str
    username: str
    email: Optional[str]
    role: str
    blocked: bool
    created_at: str
    microsoft_id: Optional[str] = None
    github_id: Optional[str] = None
    github_login: Optional[str] = None
    google_id: Optional[str] = None
    custom_oauth_id: Optional[str] = None
    status: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_user(cls, user: "User") -> "UserResponse":
        """Erstellt UserResponse aus einem User-Model."""
        return cls(
            id=str(user.id),
            username=user.username,
            email=user.email,
            role=user.role.value,
            blocked=user.blocked,
            created_at=user.created_at.isoformat(),
            microsoft_id=user.microsoft_id,
            github_id=user.github_id,
            github_login=getattr(user, "github_login", None),
            google_id=user.google_id,
            custom_oauth_id=getattr(user, "custom_oauth_id", None),
            status=_user_status_value(user),
        )


class ApproveUserRequest(BaseModel):
    """Request-Model für Freigabe einer Beitrittsanfrage."""
    role: UserRole = UserRole.READONLY


class InvitationResponse(BaseModel):
    """Response-Model für Einladungen (ohne token)."""
    id: str
    recipient_email: str
    is_used: bool
    expires_at: str
    created_at: str
    role: str


class UpdateUserRequest(BaseModel):
    """Request-Model für Benutzer-Aktualisierung. E-Mail kommt von GitHub/Google und wird nicht geändert."""
    role: Optional[UserRole] = None
    blocked: Optional[bool] = None


class InviteUserRequest(BaseModel):
    """Request-Model für Benutzer-Einladung."""
    email: EmailStr
    role: UserRole = UserRole.READONLY
    expires_hours: int = Field(default=168, ge=1, le=8760)  # 1h–1 Jahr


@router.get("", response_model=List[UserResponse])
async def list_users(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
) -> List[UserResponse]:
    """
    Listet alle Benutzer auf. Lesen: alle eingeloggten Nutzer; Änderungen: nur Admins.
    
    Args:
        current_user: Aktueller Benutzer (muss Admin sein)
        session: Datenbank-Session
        
    Returns:
        List[UserResponse]: Liste aller Benutzer
    """
    statement = select(User)
    users = session.exec(statement).all()
    
    return [
        UserResponse(
            id=str(user.id),
            username=user.username,
            email=user.email,
            role=user.role.value,
            blocked=user.blocked,
            created_at=user.created_at.isoformat(),
            microsoft_id=user.microsoft_id,
            github_id=user.github_id,
            github_login=getattr(user, "github_login", None),
            google_id=getattr(user, "google_id", None),
            custom_oauth_id=getattr(user, "custom_oauth_id", None),
            status=_user_status_value(user),
        )
        for user in users
    ]


@router.get("/invites", response_model=List[InvitationResponse])
async def list_invites(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> List[InvitationResponse]:
    """Listet alle Einladungen. Lesen: alle; Erstellen/Widerrufen: nur Admins."""
    stmt = select(Invitation).order_by(Invitation.created_at.desc())
    rows = session.exec(stmt).all()
    return [
        InvitationResponse(
            id=str(i.id),
            recipient_email=i.recipient_email,
            is_used=i.is_used,
            expires_at=i.expires_at.isoformat(),
            created_at=i.created_at.isoformat(),
            role=i.role.value,
        )
        for i in rows
    ]


@router.post("/invite", response_model=dict, status_code=status.HTTP_201_CREATED)
async def invite_user(
    request: InviteUserRequest,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict:
    """
    Erstellt eine Einladung (Invitation) und gibt den Link zurück.
    Einlösung nur via GitHub OAuth (/invite?token=... → /auth/github/authorize?state=token).
    """
    stmt = select(User).where(User.email == request.email)
    if session.exec(stmt).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="E-Mail-Adresse bereits vergeben")

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=request.expires_hours)
    inv = Invitation(
        recipient_email=request.email,
        token=token,
        is_used=False,
        expires_at=expires_at,
        role=request.role,
    )
    session.add(inv)
    session.commit()

    frontend = (config.FRONTEND_URL or config.BASE_URL or "http://localhost:8000").rstrip("/")
    link = f"{frontend}/invite?token={token}"
    logger.info(f"Admin '{current_user.username}' hat Einladung für '{request.email}' erstellt")
    return {"link": link, "expires_at": expires_at.isoformat()}


@router.delete("/invites/{invitation_id}", status_code=status.HTTP_200_OK)
async def delete_invite(
    invitation_id: UUID,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict:
    """Widerruft eine Einladung (nur für Admins)."""
    stmt = select(Invitation).where(Invitation.id == invitation_id)
    inv = session.exec(stmt).first()
    if not inv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Einladung nicht gefunden")
    session.delete(inv)
    session.commit()
    logger.info(f"Admin '{current_user.username}' hat Einladung {invitation_id} widerrufen")
    return {"message": "Einladung wurde widerrufen"}


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session)
) -> UserResponse:
    """
    Ruft einen einzelnen Benutzer ab (nur für Admins).
    
    Args:
        user_id: Benutzer-ID
        current_user: Aktueller Benutzer (muss Admin sein)
        session: Datenbank-Session
        
    Returns:
        UserResponse: Benutzer-Informationen
        
    Raises:
        HTTPException: Wenn Benutzer nicht gefunden wird
    """
    statement = select(User).where(User.id == user_id)
    user = session.exec(statement).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Benutzer nicht gefunden"
        )
    
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        role=user.role.value,
        blocked=user.blocked,
        created_at=user.created_at.isoformat(),
        microsoft_id=user.microsoft_id,
        github_id=user.github_id,
        github_login=getattr(user, "github_login", None),
        google_id=getattr(user, "google_id", None),
        custom_oauth_id=getattr(user, "custom_oauth_id", None),
        status=_user_status_value(user),
    )


@router.post("/{user_id}/approve", response_model=UserResponse)
async def approve_user(
    user_id: UUID,
    request: Optional[ApproveUserRequest] = Body(None),
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> UserResponse:
    """
    Gibt eine Beitrittsanfrage (pending) frei. Setzt status=active, blocked=False, role aus Body (Default: readonly).
    """
    statement = select(User).where(User.id == user_id)
    user = session.exec(statement).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benutzer nicht gefunden")
    st = getattr(user, "status", UserStatus.ACTIVE)
    if st != UserStatus.PENDING:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nur Beitrittsanfragen (pending) können freigegeben werden")
    role = (request.role if request else None) or UserRole.READONLY
    user.status = UserStatus.ACTIVE
    user.blocked = False
    user.role = role
    session.add(user)
    session.commit()
    session.refresh(user)
    logger.info("Admin %s hat Beitrittsanfrage von %s freigegeben (role=%s)", current_user.username, user.username, role.value)
    # Optional: E-Mail an Nutzer bei Freigabe
    try:
        from app.services.notifications import notify_user_approved
        await notify_user_approved(user)
    except Exception as e:
        logger.warning("E-Mail an Nutzer bei Freigabe fehlgeschlagen: %s", e)
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        role=user.role.value,
        blocked=user.blocked,
        created_at=user.created_at.isoformat(),
        microsoft_id=user.microsoft_id,
        github_id=user.github_id,
        github_login=getattr(user, "github_login", None),
        google_id=getattr(user, "google_id", None),
        custom_oauth_id=getattr(user, "custom_oauth_id", None),
        status=_user_status_value(user),
    )


@router.post("/{user_id}/reject", response_model=UserResponse)
async def reject_user(
    user_id: UUID,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> UserResponse:
    """
    Lehnt eine Beitrittsanfrage (pending) ab. Setzt status=rejected, blocked=True.
    """
    statement = select(User).where(User.id == user_id)
    user = session.exec(statement).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benutzer nicht gefunden")
    st = getattr(user, "status", UserStatus.ACTIVE)
    if st != UserStatus.PENDING:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nur Beitrittsanfragen (pending) können abgelehnt werden")
    user.status = UserStatus.REJECTED
    user.blocked = True
    session.add(user)
    session.commit()
    session.refresh(user)
    logger.info("Admin %s hat Beitrittsanfrage von %s abgelehnt", current_user.username, user.username)
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        role=user.role.value,
        blocked=user.blocked,
        created_at=user.created_at.isoformat(),
        microsoft_id=user.microsoft_id,
        github_id=user.github_id,
        github_login=getattr(user, "github_login", None),
        google_id=getattr(user, "google_id", None),
        custom_oauth_id=getattr(user, "custom_oauth_id", None),
        status=_user_status_value(user),
    )


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    request: UpdateUserRequest,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session)
) -> UserResponse:
    """
    Aktualisiert einen Benutzer (nur für Admins).
    
    Args:
        user_id: Benutzer-ID
        request: Aktualisierungs-Daten
        current_user: Aktueller Benutzer (muss Admin sein)
        session: Datenbank-Session
        
    Returns:
        UserResponse: Aktualisierte Benutzer-Informationen
        
    Raises:
        HTTPException: Wenn Benutzer nicht gefunden wird
    """
    statement = select(User).where(User.id == user_id)
    user = session.exec(statement).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Benutzer nicht gefunden"
        )
    
    # Aktualisiere Felder (E-Mail von OAuth-Provider wird nicht geändert)
    if request.role is not None:
        user.role = request.role
    
    if request.blocked is not None:
        user.blocked = request.blocked
    
    session.add(user)
    session.commit()
    session.refresh(user)
    
    logger.info(f"Admin '{current_user.username}' hat Benutzer '{user.username}' aktualisiert")
    
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        role=user.role.value,
        blocked=user.blocked,
        created_at=user.created_at.isoformat(),
        microsoft_id=user.microsoft_id,
        github_id=user.github_id,
        github_login=getattr(user, "github_login", None),
        google_id=getattr(user, "google_id", None),
        custom_oauth_id=getattr(user, "custom_oauth_id", None),
        status=_user_status_value(user),
    )


@router.post("/{user_id}/block", response_model=UserResponse)
async def block_user(
    user_id: UUID,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session)
) -> UserResponse:
    """
    Blockiert einen Benutzer (nur für Admins).
    
    Args:
        user_id: Benutzer-ID
        current_user: Aktueller Benutzer (muss Admin sein)
        session: Datenbank-Session
        
    Returns:
        UserResponse: Aktualisierte Benutzer-Informationen
        
    Raises:
        HTTPException: Wenn Benutzer nicht gefunden wird
    """
    statement = select(User).where(User.id == user_id)
    user = session.exec(statement).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Benutzer nicht gefunden"
        )
    
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sie können sich nicht selbst blockieren"
        )
    
    user.blocked = True
    session.add(user)
    session.commit()
    
    # Alle Sessions des Benutzers löschen (Benutzer wird sofort ausgeloggt)
    deleted_sessions = delete_all_user_sessions(session, user.id)
    session.refresh(user)
    
    logger.info(
        f"Admin '{current_user.username}' hat Benutzer '{user.username}' blockiert. "
        f"{deleted_sessions} Sessions wurden invalidiert."
    )
    
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        role=user.role.value,
        blocked=user.blocked,
        created_at=user.created_at.isoformat(),
        microsoft_id=user.microsoft_id,
        github_id=user.github_id,
        github_login=getattr(user, "github_login", None),
        google_id=getattr(user, "google_id", None),
        custom_oauth_id=getattr(user, "custom_oauth_id", None),
        status=_user_status_value(user),
    )


@router.post("/{user_id}/unblock", response_model=UserResponse)
async def unblock_user(
    user_id: UUID,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session)
) -> UserResponse:
    """
    Entblockiert einen Benutzer (nur für Admins).
    
    Args:
        user_id: Benutzer-ID
        current_user: Aktueller Benutzer (muss Admin sein)
        session: Datenbank-Session
        
    Returns:
        UserResponse: Aktualisierte Benutzer-Informationen
        
    Raises:
        HTTPException: Wenn Benutzer nicht gefunden wird
    """
    statement = select(User).where(User.id == user_id)
    user = session.exec(statement).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Benutzer nicht gefunden"
        )
    
    user.blocked = False
    session.add(user)
    session.commit()
    session.refresh(user)
    
    logger.info(f"Admin '{current_user.username}' hat Benutzer '{user.username}' entblockiert")
    
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        role=user.role.value,
        blocked=user.blocked,
        created_at=user.created_at.isoformat(),
        microsoft_id=user.microsoft_id,
        github_id=user.github_id,
        github_login=getattr(user, "github_login", None),
        google_id=getattr(user, "google_id", None),
        custom_oauth_id=getattr(user, "custom_oauth_id", None),
        status=_user_status_value(user),
    )


@router.delete("/{user_id}", status_code=status.HTTP_200_OK)
async def delete_user(
    user_id: UUID,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session)
) -> dict:
    """
    Löscht einen Benutzer (nur für Admins).
    
    Args:
        user_id: Benutzer-ID
        current_user: Aktueller Benutzer (muss Admin sein)
        session: Datenbank-Session
        
    Returns:
        dict: Erfolgsmeldung
        
    Raises:
        HTTPException: Wenn Benutzer nicht gefunden wird oder sich selbst löschen möchte
    """
    statement = select(User).where(User.id == user_id)
    user = session.exec(statement).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Benutzer nicht gefunden"
        )
    
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sie können sich nicht selbst löschen"
        )
    
    username = user.username
    session.delete(user)
    session.commit()
    
    logger.info(f"Admin '{current_user.username}' hat Benutzer '{username}' gelöscht")
    
    return {"message": "Benutzer erfolgreich gelöscht"}
