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
from typing import List, Optional
from uuid import UUID, uuid4
from datetime import datetime, timedelta
import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlmodel import Session, select

from app.auth import get_current_user, require_admin, get_password_hash, delete_all_user_sessions
from app.database import get_session
from app.models import User, UserRole

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


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

    class Config:
        from_attributes = True


def validate_password_strength(password: str) -> None:
    """
    Validiert Passwort-Stärke.
    
    Anforderungen:
    - Mindestlänge: 8 Zeichen
    - Optional: Empfehlung für stärkere Passwörter (12+ Zeichen)
    
    Args:
        password: Passwort zum Validieren
        
    Raises:
        ValueError: Wenn Passwort zu schwach ist
    """
    if len(password) < 8:
        raise ValueError("Passwort muss mindestens 8 Zeichen lang sein")
    
    # Optional: Warnung für schwache Passwörter (aber nicht blockieren)
    if len(password) < 12:
        logger.warning("Passwort ist weniger als 12 Zeichen lang. Für bessere Sicherheit wird ein längeres Passwort empfohlen.")


class CreateUserRequest(BaseModel):
    """Request-Model für Benutzer-Erstellung."""
    username: str
    password: str
    email: Optional[EmailStr] = None
    role: UserRole = UserRole.READONLY
    
    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Validiert Passwort-Stärke."""
        validate_password_strength(v)
        return v


class UpdateUserRequest(BaseModel):
    """Request-Model für Benutzer-Aktualisierung."""
    email: Optional[EmailStr] = None
    role: Optional[UserRole] = None
    blocked: Optional[bool] = None


class InviteUserRequest(BaseModel):
    """Request-Model für Benutzer-Einladung."""
    email: EmailStr
    role: UserRole = UserRole.READONLY
    expires_hours: int = 168  # Standard: 7 Tage


class AcceptInviteRequest(BaseModel):
    """Request-Model für Einladungs-Annahme."""
    username: str
    password: str
    token: str
    
    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Validiert Passwort-Stärke."""
        validate_password_strength(v)
        return v


class ResetPasswordRequest(BaseModel):
    """Request-Model für Passwort-Reset."""
    new_password: str
    
    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Validiert Passwort-Stärke."""
        validate_password_strength(v)
        return v


@router.get("", response_model=List[UserResponse])
async def list_users(
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session)
) -> List[UserResponse]:
    """
    Listet alle Benutzer auf (nur für Admins).
    
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
            microsoft_id=user.microsoft_id
        )
        for user in users
    ]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    request: CreateUserRequest,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session)
) -> UserResponse:
    """
    Erstellt einen neuen Benutzer direkt (nur für Admins).
    
    Args:
        request: Benutzer-Daten
        current_user: Aktueller Benutzer (muss Admin sein)
        session: Datenbank-Session
        
    Returns:
        UserResponse: Erstellter Benutzer
        
    Raises:
        HTTPException: Wenn Benutzername bereits existiert
    """
    # Prüfe ob Benutzername bereits existiert
    statement = select(User).where(User.username == request.username)
    existing_user = session.exec(statement).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Benutzername bereits vergeben"
        )
    
    # Prüfe ob E-Mail bereits existiert (falls angegeben)
    if request.email:
        statement = select(User).where(User.email == request.email)
        existing_email = session.exec(statement).first()
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="E-Mail-Adresse bereits vergeben"
            )
    
    # Erstelle neuen Benutzer
    user = User(
        username=request.username,
        password_hash=get_password_hash(request.password),
        email=request.email,
        role=request.role
    )
    
    session.add(user)
    session.commit()
    session.refresh(user)
    
    logger.info(f"Admin '{current_user.username}' hat Benutzer '{user.username}' erstellt")
    
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        role=user.role.value,
        blocked=user.blocked,
        created_at=user.created_at.isoformat(),
        microsoft_id=user.microsoft_id
    )


@router.post("/invite", response_model=dict, status_code=status.HTTP_201_CREATED)
async def invite_user(
    request: InviteUserRequest,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session)
) -> dict:
    """
    Erstellt einen Einladungslink für einen neuen Benutzer (nur für Admins).
    
    Args:
        request: Einladungs-Daten
        current_user: Aktueller Benutzer (muss Admin sein)
        session: Datenbank-Session
        
    Returns:
        dict: Einladungs-Token und Link
        
    Raises:
        HTTPException: Wenn E-Mail bereits vergeben ist
    """
    # Prüfe ob E-Mail bereits existiert
    statement = select(User).where(User.email == request.email)
    existing_user = session.exec(statement).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="E-Mail-Adresse bereits vergeben"
        )
    
    # Generiere Einladungs-Token
    invitation_token = str(uuid4())
    invitation_expires_at = datetime.utcnow() + timedelta(hours=request.expires_hours)
    
    # Erstelle temporären Benutzer mit Einladungs-Token
    user = User(
        username="",  # Wird beim Einlösen der Einladung gesetzt
        password_hash="",  # Wird beim Einlösen der Einladung gesetzt
        email=request.email,
        role=request.role,
        invitation_token=invitation_token,
        invitation_expires_at=invitation_expires_at
    )
    
    session.add(user)
    session.commit()
    session.refresh(user)
    
    # Erstelle Einladungs-Link (Frontend-Route)
    invite_link = f"/invite/{invitation_token}"
    
    logger.info(f"Admin '{current_user.username}' hat Einladung für '{request.email}' erstellt")
    
    return {
        "token": invitation_token,
        "link": invite_link,
        "expires_at": invitation_expires_at.isoformat()
    }


@router.post("/invite/{token}/accept", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def accept_invite(
    token: str,
    request: AcceptInviteRequest,
    session: Session = Depends(get_session)
) -> UserResponse:
    """
    Nimmt eine Einladung an und erstellt den Benutzer.
    
    Args:
        token: Einladungs-Token
        request: Benutzer-Daten (Username, Passwort)
        session: Datenbank-Session
        
    Returns:
        UserResponse: Erstellter Benutzer
        
    Raises:
        HTTPException: Wenn Token ungültig oder abgelaufen ist
    """
    # Finde Benutzer mit Token
    statement = select(User).where(User.invitation_token == token)
    user = session.exec(statement).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Einladungs-Token nicht gefunden"
        )
    
    if user.invitation_expires_at and user.invitation_expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Einladungs-Token ist abgelaufen"
        )
    
    # Prüfe ob Benutzername bereits existiert
    statement = select(User).where(User.username == request.username)
    existing_user = session.exec(statement).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Benutzername bereits vergeben"
        )
    
    # Aktualisiere Benutzer
    user.username = request.username
    user.password_hash = get_password_hash(request.password)
    user.invitation_token = None
    user.invitation_expires_at = None
    
    session.add(user)
    session.commit()
    session.refresh(user)
    
    logger.info(f"Benutzer '{user.username}' hat Einladung angenommen")
    
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        role=user.role.value,
        blocked=user.blocked,
        created_at=user.created_at.isoformat(),
        microsoft_id=user.microsoft_id
    )


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
        microsoft_id=user.microsoft_id
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
    
    # Aktualisiere Felder
    if request.email is not None:
        # Prüfe ob E-Mail bereits von anderem Benutzer verwendet wird
        statement = select(User).where(User.email == request.email, User.id != user_id)
        existing_user = session.exec(statement).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="E-Mail-Adresse bereits vergeben"
            )
        user.email = request.email
    
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
        microsoft_id=user.microsoft_id
    )


@router.post("/{user_id}/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(
    user_id: UUID,
    request: ResetPasswordRequest,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session)
) -> dict:
    """
    Setzt das Passwort eines Benutzers zurück (nur für Admins).
    
    Args:
        user_id: Benutzer-ID
        request: Neues Passwort
        current_user: Aktueller Benutzer (muss Admin sein)
        session: Datenbank-Session
        
    Returns:
        dict: Erfolgsmeldung
        
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
    
    # Setze neues Passwort
    user.password_hash = get_password_hash(request.new_password)
    
    session.add(user)
    session.commit()
    
    # Alle Sessions des Benutzers löschen (Sicherheit: Passwort wurde geändert)
    deleted_sessions = delete_all_user_sessions(session, user.id)
    logger.info(
        f"Admin '{current_user.username}' hat Passwort für Benutzer '{user.username}' zurückgesetzt. "
        f"{deleted_sessions} Sessions wurden invalidiert."
    )
    
    return {"message": "Passwort erfolgreich zurückgesetzt"}


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
        microsoft_id=user.microsoft_id
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
        microsoft_id=user.microsoft_id
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
