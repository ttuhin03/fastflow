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
from uuid import uuid4

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlmodel import Session, select

from app.config import config
from app.database import get_session
from app.models import User, Session as SessionModel

logger = logging.getLogger(__name__)

# Password-Hashing-Kontext (bcrypt)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTPBearer für JWT-Token-Extraktion
security = HTTPBearer(auto_error=False)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifiziert ein Klartext-Passwort gegen einen Hash.
    
    Args:
        plain_password: Klartext-Passwort
        hashed_password: Gehashtes Passwort (bcrypt)
        
    Returns:
        bool: True wenn Passwort korrekt, sonst False
    """
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    Erstellt einen bcrypt-Hash für ein Passwort.
    
    Args:
        password: Klartext-Passwort
        
    Returns:
        str: Gehashtes Passwort
    """
    return pwd_context.hash(password)


def create_access_token(username: str, expires_delta: Optional[timedelta] = None) -> str:
    """
    Erstellt ein JWT-Token für einen Benutzer.
    
    Args:
        username: Benutzername
        expires_delta: Optionale Ablaufzeit (Standard: JWT_EXPIRATION_HOURS)
        
    Returns:
        str: JWT-Token
    """
    if expires_delta is None:
        expires_delta = timedelta(hours=config.JWT_EXPIRATION_HOURS)
    
    expire = datetime.utcnow() + expires_delta
    
    to_encode = {
        "sub": username,
        "exp": expire
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


def get_or_create_user(session: Session, username: str, password: str) -> User:
    """
    Holt einen Benutzer aus der Datenbank oder erstellt ihn.
    
    Beim ersten Start wird der Standard-Benutzer (aus Config) erstellt,
    falls er noch nicht existiert.
    
    Args:
        session: Datenbank-Session
        username: Benutzername
        password: Klartext-Passwort (wird gehasht gespeichert)
        
    Returns:
        User: Benutzer-Instanz
    """
    # Prüfe ob Benutzer existiert
    statement = select(User).where(User.username == username)
    user = session.exec(statement).first()
    
    if user is None:
        # Erstelle neuen Benutzer
        user = User(
            username=username,
            password_hash=get_password_hash(password)
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        logger.info(f"Benutzer '{username}' erstellt")
    
    return user


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
    db_session: Session = Depends(get_session)
) -> User:
    """
    Dependency für FastAPI-Endpoints zur Authentifizierung.
    
    Verifiziert JWT-Token und gibt den aktuellen Benutzer zurück.
    Muss als Dependency in Protected Routes verwendet werden.
    
    Args:
        credentials: HTTPBearer Credentials (JWT-Token)
        db_session: Datenbank-Session
        
    Returns:
        User: Aktueller Benutzer
        
    Raises:
        HTTPException: Wenn Token fehlt, ungültig oder abgelaufen
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentifizierung erforderlich",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    
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
            detail="Session nicht gefunden oder abgelaufen",
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
    
    return user


def authenticate_user(session: Session, username: str, password: str) -> Optional[User]:
    """
    Authentifiziert einen Benutzer mit Benutzername und Passwort.
    
    Args:
        session: Datenbank-Session
        username: Benutzername
        password: Klartext-Passwort
        
    Returns:
        Optional[User]: Benutzer wenn Authentifizierung erfolgreich, sonst None
    """
    # Hole Benutzer aus Datenbank
    statement = select(User).where(User.username == username)
    user = session.exec(statement).first()
    
    if user is None:
        return None
    
    # Verifiziere Passwort
    if not verify_password(password, user.password_hash):
        return None
    
    return user
