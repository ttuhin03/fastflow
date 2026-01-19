"""
Authentication API Endpoints.

Dieses Modul enthält alle REST-API-Endpoints für Authentication:
- GitHub OAuth (Login, Einladung)
- Logout, Refresh, Me
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlmodel import Session, select

from app.auth import (
    create_access_token,
    create_session,
    delete_session,
    get_current_user,
    get_session_by_token,
)
from app.config import config
from app.database import get_session
from app.analytics import track_user_logged_in, track_user_registered
from app.github_oauth import delete_oauth_state, generate_oauth_state, store_oauth_state
from app.posthog_client import get_system_settings
from app.github_oauth_user import get_github_authorize_url, get_github_user_data
from app.google_oauth_user import get_google_authorize_url, get_google_user_data
from app.middleware.rate_limiting import limiter
from app.models import User
from app.oauth_processing import process_oauth_login

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
    frontend = (config.FRONTEND_URL or config.BASE_URL or "http://localhost:8000").rstrip("/")
    return RedirectResponse(url=f"{frontend}/auth/callback#token={token}", status_code=302)


def _redirect_to_settings_linked(provider: str) -> RedirectResponse:
    frontend = (config.FRONTEND_URL or config.BASE_URL or "http://localhost:8000").rstrip("/")
    return RedirectResponse(url=f"{frontend}/settings?linked={provider}", status_code=302)


def _redirect_anklopfen_screen(user: User) -> RedirectResponse:
    """
    Redirect für Anklopfen-Fälle (ohne Token/Session):
    - status=rejected: Beitrittsanfrage abgelehnt → /request-rejected
    - blocked=True (z. B. aktiver Nutzer gesperrt): → /account-blocked
    - sonst (pending): → /request-sent
    """
    frontend = (config.FRONTEND_URL or config.BASE_URL or "http://localhost:8000").rstrip("/")
    if getattr(user, "status", None) == "rejected":
        path = "/request-rejected"
    elif user.blocked:
        path = "/account-blocked"
    else:
        path = "/request-sent"
    return RedirectResponse(url=f"{frontend}{path}", status_code=302)


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
    GitHub OAuth Callback. Nutzt process_oauth_login (Direkt, Auto-Match, Link, INITIAL_ADMIN, Einladung, Anklopfen).
    """
    if not code:
        raise HTTPException(status_code=400, detail="GitHub OAuth: code fehlt")
    try:
        github_user = await get_github_user_data(code)
    except HTTPException:
        raise
    # GitHub liefert "id", "login"; ggf. "avatar_url" für Profilbild
    oauth_data = {**github_user, "avatar_url": github_user.get("avatar_url")}
    try:
        user, link_only, anklopfen_only, is_new_user, registration_source = await process_oauth_login(
            provider="github",
            provider_id=str(github_user["id"]),
            email=github_user.get("email"),
            session=session,
            oauth_data=oauth_data,
            state=state,
        )
    except HTTPException:
        raise
    if anklopfen_only:
        if is_new_user:
            track_user_registered(session, "github", invitation=False, initial_admin=False, anklopfen=True)
        return _redirect_anklopfen_screen(user)
    if link_only:
        logger.info(f"GitHub-Konto für '{user.username}' verknüpft")
        return _redirect_to_settings_linked("github")
    if is_new_user and registration_source:
        track_user_registered(
            session, "github",
            invitation=(registration_source == "invitation"),
            initial_admin=(registration_source == "initial_admin"),
            anklopfen=(registration_source == "anklopfen"),
        )
    track_user_logged_in(session, "github", is_new_user)
    if state:
        delete_oauth_state(state)
    token = create_access_token(username=user.username)
    create_session(session, user, token)
    logger.info(f"User '{user.username}' per GitHub angemeldet")
    return _redirect_with_token(token)


@router.get("/google/authorize")
@limiter.limit("20/minute")
async def google_authorize(
    request: Request,
    state: Optional[str] = None,
) -> RedirectResponse:
    """
    Leitet zur Google OAuth Authorize-URL weiter.
    state: optional (Invitation-Token oder leer für Login mit CSRF).
    """
    if not config.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google OAuth ist nicht konfiguriert (GOOGLE_CLIENT_ID fehlt)")
    s = state if state else generate_oauth_state()
    if not state:
        store_oauth_state(s, {"purpose": "login"})
    url = get_google_authorize_url(s)
    return RedirectResponse(url=url, status_code=302)


@router.get("/google/callback")
async def google_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    session: Session = Depends(get_session),
) -> RedirectResponse:
    """
    Google OAuth Callback. Nutzt process_oauth_login (Direkt, Auto-Match, Link, INITIAL_ADMIN, Einladung, Anklopfen).
    """
    if not code:
        raise HTTPException(status_code=400, detail="Google OAuth: code fehlt")
    try:
        google_user = await get_google_user_data(code)
    except HTTPException:
        raise
    try:
        user, link_only, anklopfen_only, is_new_user, registration_source = await process_oauth_login(
            provider="google",
            provider_id=str(google_user["id"]),
            email=google_user.get("email"),
            session=session,
            oauth_data=google_user,
            state=state,
        )
    except HTTPException:
        raise
    if anklopfen_only:
        if is_new_user:
            track_user_registered(session, "google", invitation=False, initial_admin=False, anklopfen=True)
        return _redirect_anklopfen_screen(user)
    if link_only:
        logger.info(f"Google-Konto für '{user.username}' verknüpft")
        return _redirect_to_settings_linked("google")
    if is_new_user and registration_source:
        track_user_registered(
            session, "google",
            invitation=(registration_source == "invitation"),
            initial_admin=(registration_source == "initial_admin"),
            anklopfen=(registration_source == "anklopfen"),
        )
    track_user_logged_in(session, "google", is_new_user)
    if state:
        delete_oauth_state(state)
    token = create_access_token(username=user.username)
    create_session(session, user, token)
    logger.info(f"User '{user.username}' per Google angemeldet")
    return _redirect_with_token(token)


@router.get("/link/google")
@limiter.limit("20/minute")
async def link_google(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> RedirectResponse:
    """
    Startet den Google-OAuth-Flow zum Verknüpfen des Google-Kontos mit dem eingeloggten User.
    Erfordert Authentifizierung. Nach erfolgreicher Verknüpfung: Redirect zu /settings?linked=google.
    """
    if not config.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google OAuth ist nicht konfiguriert (GOOGLE_CLIENT_ID fehlt)")
    s = generate_oauth_state()
    store_oauth_state(s, {"purpose": "link_google", "user_id": str(current_user.id)})
    url = get_google_authorize_url(s)
    logger.info("OAuth: Link-Flow gestartet provider=google user=%s", current_user.username)
    return RedirectResponse(url=url, status_code=302)


@router.get("/link/github")
@limiter.limit("20/minute")
async def link_github(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> RedirectResponse:
    """
    Startet den GitHub-OAuth-Flow zum Verknüpfen des GitHub-Kontos mit dem eingeloggten User.
    Erfordert Authentifizierung. Nach erfolgreicher Verknüpfung: Redirect zu /settings?linked=github.
    """
    if not config.GITHUB_CLIENT_ID:
        raise HTTPException(status_code=503, detail="GitHub OAuth ist nicht konfiguriert (GITHUB_CLIENT_ID fehlt)")
    s = generate_oauth_state()
    store_oauth_state(s, {"purpose": "link_github", "user_id": str(current_user.id)})
    url = get_github_authorize_url(s)
    logger.info("OAuth: Link-Flow gestartet provider=github user=%s", current_user.username)
    return RedirectResponse(url=url, status_code=302)


@router.get("/me", response_model=dict, status_code=status.HTTP_200_OK)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """
    Gibt Informationen über den aktuell angemeldeten Benutzer zurück.
    Erweitet um email, has_github, has_google, avatar_url, is_setup_completed.
    """
    role_val = current_user.role.value if hasattr(current_user, "role") and current_user.role else "readonly"
    is_setup_completed = False
    try:
        ss = get_system_settings(session)
        is_setup_completed = ss.is_setup_completed
    except Exception:
        pass
    return {
        "username": current_user.username,
        "id": str(current_user.id),
        "email": getattr(current_user, "email", None),
        "has_github": bool(getattr(current_user, "github_id", None)),
        "has_google": bool(getattr(current_user, "google_id", None)),
        "avatar_url": getattr(current_user, "avatar_url", None),
        "created_at": current_user.created_at.isoformat(),
        "role": role_val,
        "is_setup_completed": is_setup_completed,
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
