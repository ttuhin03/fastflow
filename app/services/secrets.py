"""
Secrets Management Module.

Dieses Modul verwaltet die Verschlüsselung und Speicherung von Secrets:
- Fernet-Verschlüsselung für Secrets
- Secrets-Storage in Datenbank
- Integration in Pipeline-Execution
"""

import logging
from typing import Dict, List, Optional
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import config
from app.models import Secret
from app.core.database import get_session
from sqlmodel import Session, select

logger = logging.getLogger(__name__)

# Fernet-Instanz (wird beim ersten Aufruf initialisiert)
_fernet: Optional[Fernet] = None


def _get_fernet() -> Fernet:
    """
    Gibt die Fernet-Instanz zurück (lazy initialization).
    
    Initialisiert die Fernet-Instanz mit dem ENCRYPTION_KEY aus der
    Konfiguration. Der Key muss als Base64-kodierter String vorliegen.
    
    Returns:
        Fernet: Fernet-Instanz für Verschlüsselung/Entschlüsselung
        
    Raises:
        RuntimeError: Wenn ENCRYPTION_KEY nicht gesetzt ist oder ungültig ist
    """
    global _fernet
    
    if _fernet is not None:
        return _fernet
    
    if config.ENCRYPTION_KEY is None:
        raise RuntimeError(
            "ENCRYPTION_KEY ist nicht gesetzt. "
            "Bitte setze ENCRYPTION_KEY in der .env-Datei. "
            "Generierung: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    
    try:
        # ENCRYPTION_KEY sollte als Base64-kodierter String vorliegen
        _fernet = Fernet(config.ENCRYPTION_KEY.encode() if isinstance(config.ENCRYPTION_KEY, str) else config.ENCRYPTION_KEY)
        return _fernet
    except Exception as e:
        raise RuntimeError(
            f"ENCRYPTION_KEY ist ungültig: {str(e)}. "
            "Bitte generiere einen neuen Key: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        ) from e


def encrypt(plain_text: str) -> str:
    """
    Verschlüsselt Text mit Fernet.
    
    Args:
        plain_text: Klartext, der verschlüsselt werden soll
        
    Returns:
        str: Verschlüsselter Text (Base64-kodiert)
        
    Raises:
        RuntimeError: Wenn ENCRYPTION_KEY nicht gesetzt ist oder ungültig ist
    """
    fernet = _get_fernet()
    encrypted_bytes = fernet.encrypt(plain_text.encode())
    return encrypted_bytes.decode()


def decrypt(cipher_text: str) -> str:
    """
    Entschlüsselt Text mit Fernet.
    
    Args:
        cipher_text: Verschlüsselter Text (Base64-kodiert)
        
    Returns:
        str: Entschlüsselter Klartext
        
    Raises:
        RuntimeError: Wenn ENCRYPTION_KEY nicht gesetzt ist oder ungültig ist
        ValueError: Wenn der verschlüsselte Text ungültig ist (z.B. mit anderem Key verschlüsselt)
    """
    fernet = _get_fernet()
    try:
        decrypted_bytes = fernet.decrypt(cipher_text.encode())
        return decrypted_bytes.decode()
    except InvalidToken as e:
        raise ValueError(
            "Fehler beim Entschlüsseln. Der verschlüsselte Text ist ungültig "
            "oder wurde mit einem anderen Key verschlüsselt."
        ) from e


def get_all_secrets(session: Session) -> Dict[str, str]:
    """
    Ruft alle Secrets aus der Datenbank ab und entschlüsselt sie.

    ACHTUNG: Diese Funktion ist bewusst NICHT für die Pipeline-Execution gedacht -
    sie liefert jedes jemals gespeicherte Secret, unabhängig davon, welcher Pipeline
    es "gehört". Für die Env-Var-Injection beim Pipeline-Run muss stattdessen
    get_secrets_by_keys() mit der von pipeline.json deklarierten Allow-List verwendet
    werden (siehe app/executor/core.py), sonst erhält jede Pipeline Zugriff auf die
    Secrets aller anderen Pipelines (Cross-Tenant-Leak).

    Parameter (is_parameter=True) werden nicht entschlüsselt, da sie unverschlüsselt gespeichert werden.

    Args:
        session: SQLModel Session für Datenbankzugriffe

    Returns:
        Dict[str, str]: Dictionary mit allen Secrets (Key -> entschlüsselter Value)

    Raises:
        RuntimeError: Wenn ENCRYPTION_KEY nicht gesetzt ist oder ungültig ist
        ValueError: Wenn ein Secret nicht entschlüsselt werden kann
    """
    statement = select(Secret)
    secrets = session.exec(statement).all()
    return _decrypt_secrets(secrets)


def get_secrets_by_keys(session: Session, keys: List[str]) -> Dict[str, str]:
    """
    Ruft nur die namentlich angeforderten Secrets aus der Datenbank ab und entschlüsselt sie.

    Wird von der Pipeline-Execution genutzt, um jeder Pipeline ausschliesslich die
    Secrets bereitzustellen, die sie in pipeline.json (Feld "secrets") explizit als
    benoetigt deklariert hat (Least-Privilege statt globalem Zugriff auf alle Secrets).

    Args:
        session: SQLModel Session für Datenbankzugriffe
        keys: Liste der erlaubten Secret-Keys für die aufrufende Pipeline

    Returns:
        Dict[str, str]: Dictionary mit den angeforderten Secrets (Key -> entschlüsselter Value).
            Keys ohne passendes Secret in der Datenbank werden stillschweigend übersprungen.
    """
    if not keys:
        return {}
    statement = select(Secret).where(Secret.key.in_(keys))
    secrets = session.exec(statement).all()
    return _decrypt_secrets(secrets)


def _decrypt_secrets(secrets) -> Dict[str, str]:
    """Entschlüsselt eine Liste von Secret-Rows zu einem Key->Value-Dict."""
    result: Dict[str, str] = {}
    for secret in secrets:
        try:
            # Parameter werden nicht verschlüsselt, Secrets schon
            if secret.is_parameter:
                decrypted_value = secret.value  # Parameter sind bereits unverschlüsselt
            else:
                decrypted_value = decrypt(secret.value)  # Secrets müssen entschlüsselt werden
            result[secret.key] = decrypted_value
        except ValueError as e:
            logger.error(f"Fehler beim Entschlüsseln von Secret '{secret.key}': {e}")
            # Fehler beim Entschlüsseln eines Secrets sollte nicht alle Secrets blockieren
            # Aber wir loggen den Fehler und überspringen das Secret
            continue

    return result
