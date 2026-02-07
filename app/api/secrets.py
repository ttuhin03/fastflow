"""
Secrets Management API Endpoints.

Dieses Modul enthält REST-API-Endpoints für Secrets:
- Secrets auflisten (nur Lesen)
- Klartext für pipeline.json encrypted_env verschlüsseln

Anlegen/Aktualisieren/Löschen von Secrets erfolgt manuell (z. B. Datenbank oder Konfiguration).
"""

from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from pydantic import BaseModel, Field

from app.core.database import get_session
from app.models import Secret, User
from app.services.secrets import encrypt, decrypt
from app.auth import require_write, get_current_user
from app.core.errors import get_500_detail

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/secrets", tags=["secrets"])


# Maximale Länge für zu verschlüsselnde Werte (64 KB) – Schutz vor Memory-DoS
ENCRYPT_VALUE_MAX_LENGTH = 65536


class EncryptForPipelineRequest(BaseModel):
    """Request: Klartext, der für pipeline.json encrypted_env verschlüsselt werden soll."""
    value: str = Field(..., max_length=ENCRYPT_VALUE_MAX_LENGTH)


class EncryptForPipelineResponse(BaseModel):
    """Response: Verschüsselter Wert zum manuellen Eintrag in pipeline.json unter encrypted_env.<KEY>."""
    encrypted: str


@router.post("/encrypt-for-pipeline", response_model=EncryptForPipelineResponse)
async def encrypt_for_pipeline(
    request: EncryptForPipelineRequest,
    current_user: User = Depends(require_write),
) -> EncryptForPipelineResponse:
    """
    Verschluesselt einen Klartext mit dem Server-ENCRYPTION_KEY.
    Der zurueckgegebene Ciphertext kann manuell in pipeline.json unter encrypted_env.<KEY> eingetragen werden.
    """
    try:
        encrypted = encrypt(request.value)
        return EncryptForPipelineResponse(encrypted=encrypted)
    except Exception as e:
        logger.exception("Fehler beim Verschluesseln fuer pipeline.json")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=get_500_detail(e),
        ) from e


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
                logger.warning(
                    "Secret '%s' konnte nicht entschlüsselt werden (übersprungen): %s",
                    secret.key,
                    str(e),
                )
                continue
        
        return result
        
    except Exception as e:
        logger.exception("Fehler beim Abrufen der Secrets")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=get_500_detail(e),
        ) from e
