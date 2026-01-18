"""
Authentication API Endpoints.

Dieses Modul enthält alle REST-API-Endpoints für Authentication:
- GitHub OAuth (Login, Einladung)
- Logout, Refresh, Me
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlmodel import Session, select

from app.auth import (
    create_access_token,
    create_session,
    create_github_user,
    delete_session,
    get_current_user,
    get_or_create_github_admin,
    get_session_by_token,
)
from app.config import config
from app.database import get_session
from app.github_oauth import generate_oauth_state, store_oauth_state
from app.github_oauth_user import get_github_authorize_url, get_github_user_data
from app.middleware.rate_limiting import limiter
from app.models import User, Invitation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

security = HTTPBearer(auto_error=False)


class LoginResponse(BaseModel):
    """Response-Model für Token-basierte Responses (z.B. Refresh)."""
    access_token: str
    token_type: str = "bearer"
    username: str


class LogoutResponse(BaseModel):
    """Response-Model für Logout-Endpoint."""
    message: str


def _redirect_with_token(token: str) -> RedirectResponse:
    # FRONTEND_URL oder BASE_URL (wenn Frontend vom Backend mitausgeliefert wird)
    frontend = (config.FRONTEND_URL or config.BASE_URL or "http://localhost:8000").rstrip("/")
    return RedirectResponse(url=f"{frontend}/auth/callback#token={token}", status_code=302)


@router.get("/github/authorize")
@limiter.limit("20/minute")
async def github_authorize(
    request: Request,
    state: Optional[str] = None,
) -> RedirectResponse:
    """
    Leitet zur GitHub OAuth Authorize-URL weiter.
    state: optional, wird als OAuth state mitgegeben (Invitation-Token oder CSRF).
    """
    if not config.GITHUB_CLIENT_ID:
        raise HTTPException(status_code=503, detail="GitHub OAuth ist nicht konfiguriert (GITHUB_CLIENT_ID fehlt)")
    s = state if state else generate_oauth_state()
    if not state:
        store_oauth_state(s, {"purpose": "login"})
    url = get_github_authorize_url(s)
    return RedirectResponse(url=url, status_code=302)


@router.get("/github/callback")
async def github_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    session: Session = Depends(get_session),
) -> RedirectResponse:
    """
    GitHub OAuth Callback. Pfad A: INITIAL_ADMIN_EMAIL, B: bestehender github_id-User,
    C: gültige Invitation, D: 403.
    """
    if not code:
        raise HTTPException(status_code=400, detail="GitHub OAuth: code fehlt")

    try:
        github_user = await get_github_user_data(code)
    except HTTPException:
        raise

    email = github_user.get("email")
    github_id = str(github_user["id"])
    utc = datetime.utcnow

    # A: Initial Admin (email == INITIAL_ADMIN_EMAIL)
    if email and config.INITIAL_ADMIN_EMAIL and email == config.INITIAL_ADMIN_EMAIL:
        user = get_or_create_github_admin(session, github_user)
        if user:
            token = create_access_token(username=user.username)
            create_session(session, user, token)
            logger.info(f"Admin '{user.username}' via INITIAL_ADMIN_EMAIL angemeldet")
            return _redirect_with_token(token)

    # B: Bestehender User mit github_id
    stmt = select(User).where(User.github_id == github_id)
    existing = session.exec(stmt).first()
    if existing and not existing.blocked:
        token = create_access_token(username=existing.username)
        create_session(session, existing, token)
        logger.info(f"User '{existing.username}' per GitHub angemeldet")
        return _redirect_with_token(token)

    # C: Einladung (state = Invitation.token)
    if state:
        stmt = (
            select(Invitation)
            .where(Invitation.token == state, Invitation.is_used == False, Invitation.expires_at > datetime.utcnow())
        )
        inv = session.exec(stmt).first()
        if inv:
            inv.is_used = True
            session.add(inv)
            session.commit()
            user = create_github_user(session, github_user, inv.role)
            token = create_access_token(username=user.username)
            create_session(session, user, token)
            logger.info(f"User '{user.username}' via Einladung angemeldet")
            return _redirect_with_token(token)

    # D
    raise HTTPException(status_code=403, detail="Zutritt verweigert. Keine gültige Einladung gefunden.")


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
    Access Token mit erweiterter Laufzeit, solange die Session in der
    Datenbank existiert und gültig ist. Das bestehende Token kann bereits
    abgelaufen sein (Access Token läuft nach 15 Minuten ab), solange die
    Datenbank-Session noch gültig ist (24 Stunden).
    
    Args:
        request: FastAPI Request (für Rate Limiting)
        credentials: HTTPBearer Credentials (JWT-Token)
        session: Datenbank-Session
        
    Returns:
        LoginResponse: Neues JWT-Access-Token
        
    Raises:
        HTTPException: Wenn Session nicht gefunden oder abgelaufen
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentifizierung erforderlich",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    
    # Prüfe zuerst Session in Datenbank (auch wenn Token abgelaufen ist)
    # Die Session kann noch gültig sein (24h), auch wenn das Access Token abgelaufen ist (15min)
    db_session_obj = get_session_by_token(session, token)
    if db_session_obj is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ihre Sitzung ist nach 24 Stunden abgelaufen. Bitte melden Sie sich erneut an.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Hole Benutzer aus Session
    statement = select(User).where(User.id == db_session_obj.user_id)
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
