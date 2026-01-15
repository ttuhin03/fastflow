"""
Authentication API Endpoints.

Dieses Modul enthält alle REST-API-Endpoints für Authentication:
- Login
- Logout
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, field_validator
from sqlmodel import Session, select
import re

from app.auth import (
    authenticate_user,
    create_access_token,
    create_session,
    delete_session,
    get_current_user,
    get_or_create_user,
    get_session_by_token,
    verify_token
)
from app.config import config
from app.database import get_session
from app.middleware.rate_limiting import limiter
from app.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

security = HTTPBearer(auto_error=False)


def validate_username_format(username: str) -> None:
    """
    Validiert Benutzername-Format.
    
    Anforderungen:
    - Nur alphanumerische Zeichen und Unterstriche erlaubt
    - Länge: 3-50 Zeichen
    - Darf nicht mit Unterstrichen beginnen oder enden
    
    Args:
        username: Benutzername zum Validieren
        
    Raises:
        ValueError: Wenn Benutzername ungültig ist
    """
    if len(username) < 3 or len(username) > 50:
        raise ValueError("Benutzername muss zwischen 3 und 50 Zeichen lang sein")
    
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        raise ValueError("Benutzername darf nur Buchstaben, Zahlen und Unterstriche enthalten")
    
    if username.startswith('_') or username.endswith('_'):
        raise ValueError("Benutzername darf nicht mit Unterstrichen beginnen oder enden")


class LoginRequest(BaseModel):
    """Request-Model für Login-Endpoint."""
    username: str
    password: str
    
    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        """Validiert Benutzername-Format."""
        validate_username_format(v)
        return v


class LoginResponse(BaseModel):
    """Response-Model für Login-Endpoint."""
    access_token: str
    token_type: str = "bearer"
    username: str


class LogoutResponse(BaseModel):
    """Response-Model für Logout-Endpoint."""
    message: str


@router.post("/login", response_model=LoginResponse, status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
async def login(
    request: Request,
    login_data: LoginRequest,
    session: Session = Depends(get_session)
) -> LoginResponse:
    """
    Authentifiziert einen Benutzer und gibt ein JWT-Token zurück.
    
    Beim ersten Start wird der Standard-Benutzer (aus Config) erstellt,
    falls er noch nicht existiert.
    
    Args:
        request: FastAPI Request (für Rate Limiting)
        login_data: Login-Daten (Benutzername und Passwort)
        session: Datenbank-Session
        
    Returns:
        LoginResponse: JWT-Token und Benutzername
        
    Raises:
        HTTPException: Wenn Authentifizierung fehlschlägt
    """
    # Erstelle Standard-Benutzer beim ersten Start (falls nicht vorhanden)
    get_or_create_user(
        session,
        config.AUTH_USERNAME,
        config.AUTH_PASSWORD
    )
    
    # Authentifiziere Benutzer
    user = authenticate_user(session, login_data.username, login_data.password)
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültiger Benutzername oder Passwort",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Erstelle JWT-Token
    access_token = create_access_token(username=user.username)
    
    # Erstelle Session in Datenbank (Persistenz)
    create_session(session, user, access_token)
    
    logger.info(f"Benutzer '{user.username}' hat sich angemeldet")
    
    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        username=user.username
    )


@router.get("/me", response_model=dict, status_code=status.HTTP_200_OK)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
) -> dict:
    """
    Gibt Informationen über den aktuell angemeldeten Benutzer zurück.
    
    Args:
        current_user: Aktueller Benutzer (aus Dependency)
        
    Returns:
        dict: Benutzer-Informationen
    """
    return {
        "username": current_user.username,
        "id": str(current_user.id),
        "created_at": current_user.created_at.isoformat(),
        "role": current_user.role.value if hasattr(current_user, 'role') else 'readonly'
    }


@router.post("/refresh", response_model=LoginResponse, status_code=status.HTTP_200_OK)
async def refresh_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    session: Session = Depends(get_session)
) -> LoginResponse:
    """
    Erstellt ein neues Access Token basierend auf dem bestehenden Token.
    
    Ermöglicht Token-Refresh ohne erneuten Login. Erstellt ein neues
    Access Token mit erweiterter Laufzeit, solange das bestehende Token
    noch gültig ist und die Session in der Datenbank existiert.
    
    Args:
        request: FastAPI Request (für Rate Limiting)
        credentials: HTTPBearer Credentials (JWT-Token)
        session: Datenbank-Session
        
    Returns:
        LoginResponse: Neues JWT-Access-Token
        
    Raises:
        HTTPException: Wenn Token ungültig oder Session nicht gefunden
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentifizierung erforderlich",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    
    # Verifiziere bestehendes Token
    username = verify_token(token)
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültiger oder abgelaufener Token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Prüfe Session in Datenbank
    db_session_obj = get_session_by_token(session, token)
    if db_session_obj is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session nicht gefunden oder abgelaufen",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Hole Benutzer
    statement = select(User).where(User.username == username)
    user = session.exec(statement).first()
    
    if user is None or user.blocked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Benutzer nicht gefunden oder blockiert",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Erstelle neues Access Token
    new_access_token = create_access_token(username=user.username)
    
    # Aktualisiere Session in Datenbank mit neuem Token
    # Lösche alte Session und erstelle neue
    delete_session(session, token)
    create_session(session, user, new_access_token)
    
    logger.info(f"Token für Benutzer '{user.username}' erneuert")
    
    return LoginResponse(
        access_token=new_access_token,
        token_type="bearer",
        username=user.username
    )


@router.post("/logout", response_model=LogoutResponse, status_code=status.HTTP_200_OK)
async def logout(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> LogoutResponse:
    """
    Meldet einen Benutzer ab und löscht die Session.
    
    Args:
        credentials: HTTPBearer Credentials (JWT-Token)
        session: Datenbank-Session
        current_user: Aktueller Benutzer (aus Dependency)
        
    Returns:
        LogoutResponse: Erfolgsmeldung
    """
    if credentials:
        token = credentials.credentials
        delete_session(session, token)
        logger.info(f"Benutzer '{current_user.username}' hat sich abgemeldet")
    
    return LogoutResponse(message="Erfolgreich abgemeldet")
