"""
Authentication Module.

Dieses Modul verwaltet die Authentifizierung:
- Basic Login mit Password-Hashing
- Session-Management (JWT mit Datenbank-Persistenz)
- Protected Routes (Dependency für FastAPI)

⚠️ KRITISCH: Authentifizierung ist der wichtigste Schutz gegen
Docker-Socket-Missbrauch (Docker-Socket = Root-Zugriff auf Host).
UI darf NIEMALS ohne Login erreichbar sein.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4, UUID

from fastapi import Depends, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlmodel import Session, select

from app.config import config
from app.database import get_session
from app.models import User, Session as SessionModel, UserRole

logger = logging.getLogger(__name__)

# HTTPBearer für JWT-Token-Extraktion
security = HTTPBearer(auto_error=False)


def create_access_token(username: str, expires_delta: Optional[timedelta] = None) -> str:
    """
    Erstellt ein JWT-Access-Token für einen Benutzer.
    
    Standard-Laufzeit: JWT_ACCESS_TOKEN_MINUTES (15 Minuten) für bessere Sicherheit.
    Kann mit expires_delta überschrieben werden für Rückwärtskompatibilität.
    
    Args:
        username: Benutzername
        expires_delta: Optionale Ablaufzeit (Standard: JWT_ACCESS_TOKEN_MINUTES)
        
    Returns:
        str: JWT-Access-Token
    """
    if expires_delta is None:
        # Verwende kürzere Standard-Laufzeit für Access Tokens (15 Minuten)
        expires_delta = timedelta(minutes=config.JWT_ACCESS_TOKEN_MINUTES)
    
    expire = datetime.utcnow() + expires_delta
    
    to_encode = {
        "sub": username,
        "exp": expire,
        "type": "access"  # Token-Typ für Unterscheidung
    }
    
    encoded_jwt = jwt.encode(
        to_encode,
        config.JWT_SECRET_KEY,
        algorithm=config.JWT_ALGORITHM
    )
    
    return encoded_jwt


def verify_token(token: str) -> Optional[str]:
    """
    Verifiziert ein JWT-Token und gibt den Benutzernamen zurück.
    
    Args:
        token: JWT-Token
        
    Returns:
        Optional[str]: Benutzername wenn Token gültig, sonst None
        
    Raises:
        JWTError: Wenn Token ungültig oder abgelaufen
    """
    try:
        payload = jwt.decode(
            token,
            config.JWT_SECRET_KEY,
            algorithms=[config.JWT_ALGORITHM]
        )
        username: str = payload.get("sub")
        if username is None:
            return None
        return username
    except JWTError:
        return None


def create_session(session: Session, user: User, token: str) -> SessionModel:
    """
    Erstellt eine Session in der Datenbank.
    
    Args:
        session: Datenbank-Session
        user: Benutzer-Instanz
        token: JWT-Token
        
    Returns:
        SessionModel: Erstellte Session
    """
    expires_at = datetime.utcnow() + timedelta(hours=config.JWT_EXPIRATION_HOURS)
    
    db_session = SessionModel(
        token=token,
        user_id=user.id,
        expires_at=expires_at
    )
    
    session.add(db_session)
    session.commit()
    session.refresh(db_session)
    
    return db_session


def get_session_by_token(session: Session, token: str) -> Optional[SessionModel]:
    """
    Holt eine Session aus der Datenbank anhand des Tokens.
    
    Args:
        session: Datenbank-Session
        token: JWT-Token
        
    Returns:
        Optional[SessionModel]: Session wenn gefunden und gültig, sonst None
    """
    statement = select(SessionModel).where(
        SessionModel.token == token,
        SessionModel.expires_at > datetime.utcnow()
    )
    return session.exec(statement).first()


def delete_session(session: Session, token: str) -> None:
    """
    Löscht eine Session aus der Datenbank.
    
    Args:
        session: Datenbank-Session
        token: JWT-Token
    """
    statement = select(SessionModel).where(SessionModel.token == token)
    db_session = session.exec(statement).first()
    
    if db_session:
        session.delete(db_session)
        session.commit()


def delete_all_user_sessions(session: Session, user_id: UUID) -> int:
    """
    Löscht alle Sessions eines Benutzers aus der Datenbank.
    
    Wird verwendet bei:
    - Passwort-Reset (Sicherheit: Alle bestehenden Sessions invalidiert)
    - Benutzer-Blockierung (Benutzer wird sofort ausgeloggt)
    
    Args:
        session: Datenbank-Session
        user_id: Benutzer-ID (UUID)
        
    Returns:
        int: Anzahl der gelöschten Sessions
    """
    statement = select(SessionModel).where(SessionModel.user_id == user_id)
    user_sessions = session.exec(statement).all()
    
    count = len(user_sessions)
    for db_session in user_sessions:
        session.delete(db_session)
    
    if user_sessions:
        session.commit()
        logger.info(f"{count} Sessions für Benutzer {user_id} gelöscht")
    
    return count


def cleanup_expired_sessions(session: Session) -> None:
    """
    Bereinigt abgelaufene Sessions aus der Datenbank.
    
    Wird periodisch aufgerufen, um die Datenbank sauber zu halten.
    
    Args:
        session: Datenbank-Session
    """
    statement = select(SessionModel).where(
        SessionModel.expires_at <= datetime.utcnow()
    )
    expired_sessions = session.exec(statement).all()
    
    for db_session in expired_sessions:
        session.delete(db_session)
    
    if expired_sessions:
        session.commit()
        logger.info(f"{len(expired_sessions)} abgelaufene Sessions bereinigt")


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    token: Optional[str] = Query(None, description="JWT-Token als Query-Parameter (für EventSource/SSE)"),
    db_session: Session = Depends(get_session)
) -> User:
    """
    Dependency für FastAPI-Endpoints zur Authentifizierung.
    
    Verifiziert JWT-Token und gibt den aktuellen Benutzer zurück.
    Muss als Dependency in Protected Routes verwendet werden.
    
    Unterstützt zwei Methoden für Token-Übergabe:
    1. Authorization Header (Standard für REST-APIs)
    2. Query-Parameter "token" (für EventSource/SSE, da EventSource keine Custom Headers unterstützt)
    
    Args:
        credentials: HTTPBearer Credentials (JWT-Token aus Header)
        token: JWT-Token als Query-Parameter (optional, für EventSource)
        db_session: Datenbank-Session
        
    Returns:
        User: Aktueller Benutzer
        
    Raises:
        HTTPException: Wenn Token fehlt, ungültig oder abgelaufen
    """
    # Token aus Header oder Query-Parameter holen
    auth_token = None
    
    if credentials is not None:
        # Standard: Token aus Authorization Header
        auth_token = credentials.credentials
    elif token is not None:
        # Fallback: Token aus Query-Parameter (für EventSource/SSE)
        auth_token = token
    
    if auth_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentifizierung erforderlich",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = auth_token
    
    # Verifiziere Token
    username = verify_token(token)
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültiger oder abgelaufener Token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Prüfe Session in Datenbank (Persistenz)
    db_session_obj = get_session_by_token(db_session, token)
    if db_session_obj is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ihre Sitzung ist nach 24 Stunden abgelaufen. Bitte melden Sie sich erneut an.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Hole Benutzer
    statement = select(User).where(User.username == username)
    user = db_session.exec(statement).first()
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Benutzer nicht gefunden",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Fix: Korrigiere alte lowercase enum-Werte zu UPPERCASE (für Migration)
    if hasattr(user, 'role') and user.role:
        role_str = str(user.role) if not isinstance(user.role, str) else user.role
        if role_str in ['readonly', 'write', 'admin']:
            # Konvertiere lowercase zu UPPERCASE
            role_mapping = {'readonly': UserRole.READONLY, 'write': UserRole.WRITE, 'admin': UserRole.ADMIN}
            user.role = role_mapping[role_str]
            db_session.add(user)
            db_session.commit()
            db_session.refresh(user)
            logger.info(f"Rolle für Benutzer '{username}' von '{role_str}' zu '{user.role.value}' korrigiert")
    
    # Prüfe ob Benutzer blockiert ist
    if user.blocked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Benutzer ist blockiert",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """
    Dependency für FastAPI-Endpoints, die Admin-Rechte erfordern.
    
    Prüft ob der aktuelle Benutzer Admin-Rechte hat.
    
    Args:
        current_user: Aktueller Benutzer (aus get_current_user Dependency)
        
    Returns:
        User: Aktueller Benutzer (wenn Admin)
        
    Raises:
        HTTPException: Wenn Benutzer kein Admin ist
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin-Rechte erforderlich"
        )
    return current_user


def require_write(current_user: User = Depends(get_current_user)) -> User:
    """
    Dependency für FastAPI-Endpoints, die Write-Rechte erfordern.
    
    Prüft ob der aktuelle Benutzer Write- oder Admin-Rechte hat.
    Readonly-Nutzer werden abgelehnt.
    
    Args:
        current_user: Aktueller Benutzer (aus get_current_user Dependency)
        
    Returns:
        User: Aktueller Benutzer (wenn Write oder Admin)
        
    Raises:
        HTTPException: Wenn Benutzer nur Readonly-Rechte hat
    """
    if current_user.role == UserRole.READONLY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Write-Rechte erforderlich. Readonly-Nutzer können keine Änderungen vornehmen."
        )
    return current_user
