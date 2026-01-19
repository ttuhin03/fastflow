"""
Secrets Management API Endpoints.

Dieses Modul enthält alle REST-API-Endpoints für Secrets-Management:
- Secrets auflisten
- Secret speichern
- Secret aktualisieren
- Secret löschen
"""

import re
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from pydantic import BaseModel

from app.database import get_session
from app.models import Secret, User
from app.secrets import encrypt, decrypt
from app.auth import require_write, get_current_user
from app.errors import get_500_detail

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/secrets", tags=["secrets"])

# Secret-Key: alphanumeric, underscore, hyphen, Schrägstrich; kein '..'; max 255 Zeichen
_SECRET_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_/\-]+$")


def _validate_secret_key(key: str) -> None:
    """Validiert Secret-Key. Erlaubt auch /.

    Raises:
        HTTPException: Bei ungültigem Key
    """
    if not key or len(key) > 255:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Secret-Key muss 1–255 Zeichen haben (Zeichen: A–Z, a–z, 0–9, _, -, /).",
        )
    if ".." in key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Secret-Key darf '..' nicht enthalten.",
        )
    if not _SECRET_KEY_PATTERN.match(key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Secret-Key darf nur A–Z, a–z, 0–9, _, - und / enthalten.",
        )


class SecretCreateRequest(BaseModel):
    """Request-Model für Secret-Erstellung."""
    key: str
    value: str
    is_parameter: bool = False


class SecretUpdateRequest(BaseModel):
    """Request-Model für Secret-Aktualisierung."""
    value: str
    is_parameter: Optional[bool] = None


@router.get("", response_model=List[Dict[str, Any]])
async def get_secrets(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    """
    Gibt alle Secrets zurück (Values entschlüsselt).
    
    Ruft alle Secrets aus der Datenbank ab und entschlüsselt die Werte
    für die Rückgabe an den Client.
    
    Args:
        session: SQLModel Session
        
    Returns:
        Liste aller Secrets mit entschlüsselten Werten
        
    Raises:
        HTTPException: Wenn ein Fehler beim Abrufen oder Entschlüsseln auftritt
    """
    try:
        statement = select(Secret)
        secrets = session.exec(statement).all()
        
        result = []
        for secret in secrets:
            try:
                # Parameter werden nicht verschlüsselt, Secrets schon
                if secret.is_parameter:
                    decrypted_value = secret.value
                else:
                    decrypted_value = decrypt(secret.value)
                result.append({
                    "key": secret.key,
                    "value": decrypted_value,
                    "is_parameter": secret.is_parameter,
                    "created_at": secret.created_at.isoformat(),
                    "updated_at": secret.updated_at.isoformat()
                })
            except ValueError as e:
                # Fehler beim Entschlüsseln eines Secrets sollte nicht alle Secrets blockieren
                # Aber wir loggen den Fehler und überspringen das Secret
                continue
        
        return result
        
    except Exception as e:
        logger.exception("Fehler beim Abrufen der Secrets")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=get_500_detail(e),
        ) from e


@router.post("", response_model=Dict[str, Any])
async def create_secret(
    request: SecretCreateRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_write),
) -> Dict[str, Any]:
    """
    Erstellt ein neues Secret (Value wird verschlüsselt gespeichert).
    
    Verschlüsselt den Wert vor der Speicherung in der Datenbank.
    Wenn ein Secret mit demselben Key bereits existiert, wird ein Fehler zurückgegeben.
    
    Args:
        request: Request-Body mit key und value
        session: SQLModel Session
        
    Returns:
        Dictionary mit erstelltem Secret (entschlüsselt)
        
    Raises:
        HTTPException: Wenn Secret bereits existiert oder Fehler bei Verschlüsselung auftritt
    """
    _validate_secret_key(request.key)
    try:
        # Prüfe ob Secret bereits existiert
        statement = select(Secret).where(Secret.key == request.key)
        existing = session.exec(statement).first()
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Secret mit Key '{request.key}' existiert bereits. Verwende PUT für Aktualisierung."
            )
        
        # Verschlüssele Value nur wenn es kein Parameter ist
        if request.is_parameter:
            stored_value = request.value  # Parameter werden nicht verschlüsselt
        else:
            stored_value = encrypt(request.value)  # Secrets werden verschlüsselt
        
        # Secret erstellen
        secret = Secret(
            key=request.key,
            value=stored_value,
            is_parameter=request.is_parameter
        )
        
        session.add(secret)
        session.commit()
        session.refresh(secret)
        
        # Entschlüsselten Wert für Response zurückgeben
        return {
            "key": secret.key,
            "value": request.value,  # Original-Wert (nicht verschlüsselt)
            "created_at": secret.created_at.isoformat(),
            "updated_at": secret.updated_at.isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        logger.exception("Fehler beim Erstellen des Secrets")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=get_500_detail(e),
        ) from e


@router.put("/{key:path}", response_model=Dict[str, Any])
async def update_secret(
    key: str,
    request: SecretUpdateRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_write),
) -> Dict[str, Any]:
    """
    Aktualisiert ein bestehendes Secret (Value wird verschlüsselt gespeichert).
    Key darf / enthalten (z.B. "env/DATABASE_URL").

    Verschlüsselt den Wert vor der Speicherung in der Datenbank.
    Wenn das Secret nicht existiert, wird ein Fehler zurückgegeben.

    Args:
        key: Secret-Key (darf / enthalten)
        request: Request-Body mit neuem value
        session: SQLModel Session

    Returns:
        Dictionary mit aktualisiertem Secret (entschlüsselt)

    Raises:
        HTTPException: Wenn Secret nicht existiert oder Fehler bei Verschlüsselung auftritt
    """
    from datetime import datetime

    _validate_secret_key(key)
    try:
        # Secret abrufen
        statement = select(Secret).where(Secret.key == key)
        secret = session.exec(statement).first()
        if secret is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Secret mit Key '{key}' nicht gefunden. Verwende POST für Erstellung."
            )
        
        # Verschlüssele neuen Value nur wenn es kein Parameter ist
        if request.is_parameter is not None:
            secret.is_parameter = request.is_parameter
        
        if secret.is_parameter:
            secret.value = request.value  # Parameter werden nicht verschlüsselt
        else:
            secret.value = encrypt(request.value)  # Secrets werden verschlüsselt
        
        secret.updated_at = datetime.utcnow()
        
        session.add(secret)
        session.commit()
        session.refresh(secret)
        
        # Entschlüsselten Wert für Response zurückgeben
        return {
            "key": secret.key,
            "value": request.value,  # Original-Wert (nicht verschlüsselt)
            "created_at": secret.created_at.isoformat(),
            "updated_at": secret.updated_at.isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        logger.exception("Fehler beim Aktualisieren des Secrets")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=get_500_detail(e),
        ) from e


@router.delete("/{key:path}")
async def delete_secret(
    key: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_write),
) -> Dict[str, Any]:
    """
    Löscht ein Secret. Key darf / enthalten (z.B. "env/DATABASE_URL").

    Args:
        key: Secret-Key (darf / enthalten)
        session: SQLModel Session

    Returns:
        Dictionary mit Bestätigung der Löschung

    Raises:
        HTTPException: Wenn Secret nicht existiert
    """
    _validate_secret_key(key)
    try:
        # Secret abrufen
        statement = select(Secret).where(Secret.key == key)
        secret = session.exec(statement).first()
        if secret is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Secret mit Key '{key}' nicht gefunden."
            )
        
        # Secret löschen
        session.delete(secret)
        session.commit()
        
        return {
            "message": f"Secret '{key}' erfolgreich gelöscht.",
            "key": key
        }
        
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        logger.exception("Fehler beim Löschen des Secrets")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=get_500_detail(e),
        ) from e
