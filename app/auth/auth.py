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
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4, UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlmodel import Session, select

from app.core.config import config
from app.core.database import get_session, retry_on_sqlite_io
from app.models import (
    User,
    Session as SessionModel,
    UserRole,
    UserStatus,
    EphemeralToken,
    EphemeralTokenType,
)

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
    
    expire = datetime.now(timezone.utc) + expires_delta
    
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


def _create_ephemeral_token(
    session: Session, token_type: EphemeralTokenType, subject: str, ttl_seconds: int
) -> str:
    """Erstellt ein opakes, DB-gebundenes Kurzzeit-Token (siehe EphemeralToken)."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    row = EphemeralToken(
        token=token,
        token_type=token_type,
        subject=subject,
        expires_at=expires_at,
    )
    session.add(row)
    session.commit()
    return token


def create_log_download_token(session: Session, run_id: UUID) -> str:
    """
    Erstellt ein kurzlebiges, DB-gebundenes Token für Log-Download (60 Sekunden).
    Wird für Direktlinks verwendet, damit der Browser den Download nativ ausführt.
    """
    return _create_ephemeral_token(session, EphemeralTokenType.LOG_DOWNLOAD, str(run_id), ttl_seconds=60)


def verify_log_download_token(session: Session, token: str, run_id: UUID) -> bool:
    """
    Prüft, ob ein Log-Download-Token für die angegebene run_id gültig ist.

    Mehrfach nutzbar innerhalb der TTL (kein Single-Use), damit ein im Frontend
    kurz gecachter Download-Link nicht bei jedem Klick erneut angefordert werden muss.
    Das Token muss trotzdem einer aktiven DB-Zeile entsprechen (siehe EphemeralToken) –
    reine Signaturfälschung reicht nicht mehr aus.
    """
    statement = select(EphemeralToken).where(
        EphemeralToken.token == token,
        EphemeralToken.token_type == EphemeralTokenType.LOG_DOWNLOAD,
        EphemeralToken.subject == str(run_id),
        EphemeralToken.expires_at > datetime.now(timezone.utc),
    )
    return retry_on_sqlite_io(lambda: session.exec(statement).first(), session=session) is not None


def create_link_token(session: Session, user_id: UUID) -> str:
    """
    Erstellt ein kurzlebiges (60 Sekunden), DB-gebundenes Single-Use-Token zum Starten
    des OAuth-Account-Link-Flows.

    Wird verwendet, damit das Frontend beim Account-Linking (volle Browser-Navigation ohne
    Authorization-Header) nicht das volle Session-JWT als Query-Parameter mitschicken muss.
    Anders als ein reines JWT reicht eine gültige Signatur allein nicht: das Token muss
    einer nicht abgelaufenen, noch nicht eingelösten Zeile in der DB entsprechen. Das
    verhindert, dass ein Angreifer mit Kenntnis einer fremden user_id (z.B. via GET /users)
    und einem geleakten/schwachen JWT_SECRET_KEY einen Link-Token fälscht und so ein
    fremdes Konto per Account-Linking übernimmt (siehe TE-11 Finding 2 / TE-15).
    """
    return _create_ephemeral_token(session, EphemeralTokenType.ACCOUNT_LINK, str(user_id), ttl_seconds=60)


def verify_link_token(session: Session, token: str) -> Optional[UUID]:
    """
    Prüft ein Account-Link-Token und gibt die User-ID zurück, wenn es gültig ist.

    Single-use: die Zeile wird beim ersten gültigen Verifizieren als eingelöst markiert,
    ein zweiter Versuch mit demselben Token schlägt fehl. Gibt None zurück, wenn das
    Token unbekannt, abgelaufen, bereits eingelöst ist oder nicht vom Typ "account_link"
    ist.
    """
    statement = select(EphemeralToken).where(
        EphemeralToken.token == token,
        EphemeralToken.token_type == EphemeralTokenType.ACCOUNT_LINK,
        EphemeralToken.expires_at > datetime.now(timezone.utc),
        EphemeralToken.consumed_at.is_(None),
    )
    row = retry_on_sqlite_io(lambda: session.exec(statement).first(), session=session)
    if row is None:
        return None
    row.consumed_at = datetime.now(timezone.utc)
    session.add(row)
    session.commit()
    try:
        return UUID(row.subject)
    except (ValueError, TypeError):
        return None


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
        # Nur echte Access-Tokens dürfen als Identität gelten. Andere JWT-Typen
        # (z. B. log_download) tragen im "sub" eine Run-ID statt eines Benutzernamens
        # und dürfen niemals eine Authentifizierung bewirken (Token-Type-Confusion).
        if payload.get("type") != "access":
            return None
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
    expires_at = datetime.now(timezone.utc) + timedelta(hours=config.JWT_EXPIRATION_HOURS)
    
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
        SessionModel.expires_at > datetime.now(timezone.utc)
    )
    return retry_on_sqlite_io(
        lambda: session.exec(statement).first(), session=session
    )


def delete_session(session: Session, token: str) -> None:
    """
    Löscht eine Session aus der Datenbank.
    
    Args:
        session: Datenbank-Session
        token: JWT-Token
    """
    statement = select(SessionModel).where(SessionModel.token == token)
    db_session = retry_on_sqlite_io(
        lambda: session.exec(statement).first(), session=session
    )
    
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
        SessionModel.expires_at <= datetime.now(timezone.utc)
    )
    expired_sessions = session.exec(statement).all()
    
    for db_session in expired_sessions:
        session.delete(db_session)
    
    if expired_sessions:
        session.commit()
        logger.info(f"{len(expired_sessions)} abgelaufene Sessions bereinigt")


def cleanup_expired_ephemeral_tokens(session: Session) -> None:
    """
    Bereinigt abgelaufene Link-/Log-Download-Tokens aus der Datenbank.

    Wird periodisch aufgerufen, um die Datenbank sauber zu halten.

    Args:
        session: Datenbank-Session
    """
    statement = select(EphemeralToken).where(
        EphemeralToken.expires_at <= datetime.now(timezone.utc)
    )
    expired_tokens = session.exec(statement).all()

    for row in expired_tokens:
        session.delete(row)

    if expired_tokens:
        session.commit()
        logger.info(f"{len(expired_tokens)} abgelaufene Ephemeral-Tokens bereinigt")


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db_session: Session = Depends(get_session)
) -> User:
    """
    Dependency für FastAPI-Endpoints zur Authentifizierung.

    Verifiziert JWT-Token und gibt den aktuellen Benutzer zurück.
    Muss als Dependency in Protected Routes verwendet werden.

    Das Token wird ausschließlich über den Authorization-Header übergeben. Der früher
    unterstützte Query-Parameter "token" wurde entfernt, da volle Session-JWTs in URLs
    in Server-/Proxy-Logs, Browser-History und Referrer landen. Flows ohne
    Authorization-Header (z.B. Account-Linking per Browser-Navigation) verwenden dedizierte,
    kurzlebige Tokens (siehe create_link_token/verify_link_token).

    Args:
        credentials: HTTPBearer Credentials (JWT-Token aus Header)
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
            detail={
                "message": f"Ihre Sitzung ist nach {config.JWT_EXPIRATION_HOURS} Stunden abgelaufen. Bitte melden Sie sich erneut an.",
                "error_code": "SESSION_EXPIRED",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Hole Benutzer
    statement = select(User).where(User.username == username)
    user = retry_on_sqlite_io(
        lambda: db_session.exec(statement).first(), session=db_session
    )
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Benutzer nicht gefunden",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Prüfe ob Benutzer blockiert ist
    if user.blocked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Benutzer ist blockiert",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Abwehr: pending/rejected erhalten in diesem Flow keinen Token; falls doch:
    if getattr(user, "status", UserStatus.ACTIVE) != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Benutzer ist nicht freigegeben",
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
