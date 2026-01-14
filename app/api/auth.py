"""
Authentication API Endpoints.

Dieses Modul enthält alle REST-API-Endpoints für Authentication:
- Login
- Logout
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlmodel import Session, select

from app.auth import (
    authenticate_user,
    create_access_token,
    create_session,
    delete_session,
    get_current_user,
    get_or_create_user,
    verify_token
)
from app.config import config
from app.database import get_session
from app.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

security = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    """Request-Model für Login-Endpoint."""
    username: str
    password: str


class LoginResponse(BaseModel):
    """Response-Model für Login-Endpoint."""
    access_token: str
    token_type: str = "bearer"
    username: str


class LogoutResponse(BaseModel):
    """Response-Model für Logout-Endpoint."""
    message: str


@router.post("/login", response_model=LoginResponse, status_code=status.HTTP_200_OK)
async def login(
    login_data: LoginRequest,
    session: Session = Depends(get_session)
) -> LoginResponse:
    """
    Authentifiziert einen Benutzer und gibt ein JWT-Token zurück.
    
    Beim ersten Start wird der Standard-Benutzer (aus Config) erstellt,
    falls er noch nicht existiert.
    
    Args:
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


@router.get("/me", status_code=status.HTTP_200_OK)
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
        "created_at": current_user.created_at.isoformat()
    }
