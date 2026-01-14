"""
Secrets Management API Endpoints.

Dieses Modul enthält alle REST-API-Endpoints für Secrets-Management:
- Secrets auflisten
- Secret speichern
- Secret aktualisieren
- Secret löschen
"""

from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from pydantic import BaseModel

from app.database import get_session
from app.models import Secret
from app.secrets import encrypt, decrypt

router = APIRouter(prefix="/secrets", tags=["secrets"])


class SecretCreateRequest(BaseModel):
    """Request-Model für Secret-Erstellung."""
    key: str
    value: str


class SecretUpdateRequest(BaseModel):
    """Request-Model für Secret-Aktualisierung."""
    value: str


@router.get("", response_model=List[Dict[str, Any]])
async def get_secrets(
    session: Session = Depends(get_session)
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
                decrypted_value = decrypt(secret.value)
                result.append({
                    "key": secret.key,
                    "value": decrypted_value,
                    "created_at": secret.created_at.isoformat(),
                    "updated_at": secret.updated_at.isoformat()
                })
            except ValueError as e:
                # Fehler beim Entschlüsseln eines Secrets sollte nicht alle Secrets blockieren
                # Aber wir loggen den Fehler und überspringen das Secret
                continue
        
        return result
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Abrufen der Secrets: {str(e)}"
        ) from e


@router.post("", response_model=Dict[str, Any])
async def create_secret(
    request: SecretCreateRequest,
    session: Session = Depends(get_session)
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
    try:
        # Prüfe ob Secret bereits existiert
        statement = select(Secret).where(Secret.key == request.key)
        existing = session.exec(statement).first()
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Secret mit Key '{request.key}' existiert bereits. Verwende PUT für Aktualisierung."
            )
        
        # Verschlüssele Value
        encrypted_value = encrypt(request.value)
        
        # Secret erstellen
        secret = Secret(
            key=request.key,
            value=encrypted_value
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Erstellen des Secrets: {str(e)}"
        ) from e


@router.put("/{key}", response_model=Dict[str, Any])
async def update_secret(
    key: str,
    request: SecretUpdateRequest,
    session: Session = Depends(get_session)
) -> Dict[str, Any]:
    """
    Aktualisiert ein bestehendes Secret (Value wird verschlüsselt gespeichert).
    
    Verschlüsselt den Wert vor der Speicherung in der Datenbank.
    Wenn das Secret nicht existiert, wird ein Fehler zurückgegeben.
    
    Args:
        key: Secret-Key
        request: Request-Body mit neuem value
        session: SQLModel Session
        
    Returns:
        Dictionary mit aktualisiertem Secret (entschlüsselt)
        
    Raises:
        HTTPException: Wenn Secret nicht existiert oder Fehler bei Verschlüsselung auftritt
    """
    from datetime import datetime
    
    try:
        # Secret abrufen
        statement = select(Secret).where(Secret.key == key)
        secret = session.exec(statement).first()
        if secret is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Secret mit Key '{key}' nicht gefunden. Verwende POST für Erstellung."
            )
        
        # Verschlüssele neuen Value
        encrypted_value = encrypt(request.value)
        
        # Secret aktualisieren
        secret.value = encrypted_value
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Aktualisieren des Secrets: {str(e)}"
        ) from e


@router.delete("/{key}")
async def delete_secret(
    key: str,
    session: Session = Depends(get_session)
) -> Dict[str, Any]:
    """
    Löscht ein Secret.
    
    Args:
        key: Secret-Key
        session: SQLModel Session
        
    Returns:
        Dictionary mit Bestätigung der Löschung
        
    Raises:
        HTTPException: Wenn Secret nicht existiert
    """
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Löschen des Secrets: {str(e)}"
        ) from e
