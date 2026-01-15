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

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from passlib.exc import UnknownHashError
from sqlmodel import Session, select

from app.config import config
from app.database import get_session
from app.models import User, Session as SessionModel, UserRole

logger = logging.getLogger(__name__)

# Password-Hashing-Kontext (bcrypt_sha256)
# bcrypt_sha256 wendet SHA-256 auf das Passwort an, bevor es mit bcrypt gehasht wird
# Das umgeht das 72-Byte-Limit von bcrypt
pwd_context = CryptContext(
    schemes=["bcrypt_sha256"],
    deprecated="auto"
)

# HTTPBearer für JWT-Token-Extraktion
security = HTTPBearer(auto_error=False)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifiziert ein Klartext-Passwort gegen einen Hash.
    
    Args:
        plain_password: Klartext-Passwort
        hashed_password: Gehashtes Passwort (bcrypt_sha256)
        
    Returns:
        bool: True wenn Passwort korrekt, sonst False
        
    Raises:
        UnknownHashError: Wenn Hash nicht im erwarteten Format ist (wird von authenticate_user abgefangen)
        ValueError: Wenn Hash leer oder None ist
    """
    # Prüfe ob Hash leer oder None ist
    if not hashed_password or not hashed_password.strip():
        logger.warning("Passwort-Hash ist leer oder None")
        return False
    
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except UnknownHashError:
        # Hash ist nicht im erwarteten Format (z.B. alter Hash-Format oder beschädigt)
        # Wirf die Exception weiter, damit authenticate_user sie abfangen kann
        raise
    except Exception as e:
        # Andere Fehler beim Verifizieren
        logger.error(f"Unerwarteter Fehler bei Passwort-Verifizierung: {e}")
        return False


def get_password_hash(password: str) -> str:
    """
    Erstellt einen bcrypt-Hash für ein Passwort.
    
    Args:
        password: Klartext-Passwort
        
    Returns:
        str: Gehashtes Passwort
    """
    # bcrypt_sha256 hat kein 72-Byte-Limit, da es SHA-256 vor dem Hashing anwendet
    # Aber wir müssen sicherstellen, dass das Backend initialisiert ist
    try:
        return pwd_context.hash(password)
    except (ValueError, AttributeError) as e:
        # Falls Backend noch nicht initialisiert ist, initialisiere es
        # Verwende ein sehr kurzes Passwort für die Initialisierung
        try:
            # Versuche mit einem kurzen Passwort zu initialisieren
            _ = pwd_context.hash("x")
            # Versuche es erneut mit dem echten Passwort
            return pwd_context.hash(password)
        except Exception:
            # Falls das auch fehlschlägt, verwende direkt bcrypt ohne passlib
            import bcrypt
            password_bytes = password.encode('utf-8')
            if len(password_bytes) > 72:
                import hashlib
                # Pre-hash mit SHA-256 wenn zu lang
                password_bytes = hashlib.sha256(password_bytes).digest()
            salt = bcrypt.gensalt()
            return bcrypt.hashpw(password_bytes, salt).decode('utf-8')


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
    
    # Prüfe ob dies der Standard-Admin-Nutzer ist
    from app.config import config
    is_default_admin = (username == config.AUTH_USERNAME)
    
    # Fix: Korrigiere alte lowercase enum-Werte zu UPPERCASE (für Migration)
    if user and hasattr(user, 'role') and user.role:
        role_str = str(user.role) if not isinstance(user.role, str) else user.role
        if role_str in ['readonly', 'write', 'admin']:
            # Konvertiere lowercase zu UPPERCASE
            role_mapping = {'readonly': UserRole.READONLY, 'write': UserRole.WRITE, 'admin': UserRole.ADMIN}
            user.role = role_mapping[role_str]
            session.add(user)
            session.commit()
            session.refresh(user)
            logger.info(f"Rolle für Benutzer '{username}' von '{role_str}' zu '{user.role.value}' korrigiert")
    
    if user is None:
        # Erstelle neuen Benutzer
        # Standard-Benutzer (aus Config) bekommt Admin-Rechte
        user = User(
            username=username,
            password_hash=get_password_hash(password),
            role=UserRole.ADMIN if is_default_admin else UserRole.READONLY
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        logger.info(f"Benutzer '{username}' erstellt (Rolle: {user.role.value})")
    else:
        # Wenn Benutzer existiert, aber keine Rolle hat (Migration), setze auf Admin für Standard-Benutzer
        if not hasattr(user, 'role') or user.role is None:
            user.role = UserRole.ADMIN if is_default_admin else UserRole.READONLY
            session.add(user)
            session.commit()
            session.refresh(user)
            logger.info(f"Rolle für Benutzer '{username}' gesetzt: {user.role.value}")
        # WICHTIG: Stelle sicher, dass der Standard-Admin-Nutzer immer Admin-Rechte hat
        elif is_default_admin and user.role != UserRole.ADMIN:
            logger.warning(f"Standard-Admin-Nutzer '{username}' hatte Rolle '{user.role.value}', wird auf ADMIN gesetzt")
            user.role = UserRole.ADMIN
            session.add(user)
            session.commit()
            session.refresh(user)
            logger.info(f"Rolle für Standard-Admin-Nutzer '{username}' auf ADMIN gesetzt")
    
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


def authenticate_user(session: Session, username: str, password: str) -> Optional[User]:
    """
    Authentifiziert einen Benutzer mit Benutzername und Passwort.
    
    Repariert automatisch ungültige Hashes für den Standard-Admin-Nutzer,
    wenn das eingegebene Passwort mit dem Config-Passwort übereinstimmt.
    Dies ermöglicht die Wiederherstellung nach Hash-Korruption.
    
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
    
    # Prüfe ob Hash vorhanden ist
    if not user.password_hash or not user.password_hash.strip():
        logger.warning(f"Benutzer '{username}' hat keinen gültigen Passwort-Hash")
        return None
    
    # Verifiziere Passwort
    try:
        if not verify_password(password, user.password_hash):
            return None
    except UnknownHashError:
        # Hash ist ungültig - prüfe ob wir ihn reparieren können
        # Nur für Standard-Admin-Nutzer und nur wenn Passwort mit Config übereinstimmt
        is_default_admin = (username == config.AUTH_USERNAME)
        
        if is_default_admin and password == config.AUTH_PASSWORD:
            # Sichere Hash-Reparatur: Nur für Standard-Admin mit korrektem Config-Passwort
            logger.warning(
                f"Passwort-Hash für Standard-Admin-Nutzer '{username}' ist ungültig. "
                "Repariere Hash mit Config-Passwort..."
            )
            try:
                user.password_hash = get_password_hash(password)
                session.add(user)
                session.commit()
                session.refresh(user)
                logger.info(f"Passwort-Hash für Benutzer '{username}' erfolgreich repariert")
                # Hash wurde repariert, Login ist erfolgreich
                return user
            except Exception as e:
                logger.error(f"Fehler beim Reparieren des Passwort-Hash für Benutzer '{username}': {e}")
                return None
        else:
            # Hash ist ungültig und kann nicht repariert werden
            logger.error(
                f"Passwort-Hash für Benutzer '{username}' ist ungültig. "
                "Login abgelehnt aus Sicherheitsgründen."
            )
            return None
    except Exception as e:
        logger.error(f"Fehler bei Passwort-Verifizierung für Benutzer '{username}': {e}")
        return None
    
    # Prüfe ob Benutzer blockiert ist
    if user.blocked:
        return None
    
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
