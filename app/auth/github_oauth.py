"""
GitHub OAuth State Management.

Dieses Modul verwaltet OAuth State Tokens für CSRF-Schutz
beim GitHub App Manifest Flow.
"""

import secrets
import time
from typing import Dict, Optional
from datetime import datetime, timedelta, timezone

# In-Memory State Storage (für Production sollte Redis verwendet werden)
_oauth_states: Dict[str, Dict] = {}
_STATE_TTL = 3600  # 1 Stunde (GitHub Manifest Flow muss innerhalb 1 Stunde abgeschlossen werden)


def generate_oauth_state() -> str:
    """
    Generiert einen zufälligen OAuth State Token für CSRF-Schutz.
    
    Returns:
        Zufälliger URL-safe Token (32 Bytes)
    """
    return secrets.token_urlsafe(32)


def store_oauth_state(state: str, data: Dict) -> None:
    """
    Speichert OAuth State mit zugehörigen Daten.
    
    Args:
        state: OAuth State Token
        data: Dictionary mit State-Daten (z.B. user_id, timestamp)
    """
    _oauth_states[state] = {
        **data,
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=_STATE_TTL),
        "created_at": datetime.now(timezone.utc)
    }


def get_oauth_state(state: str) -> Optional[Dict]:
    """
    Lädt OAuth State aus dem Cache.
    
    Args:
        state: OAuth State Token
        
    Returns:
        State-Daten oder None wenn nicht gefunden oder abgelaufen
    """
    if state not in _oauth_states:
        return None
    
    state_data = _oauth_states[state]
    
    # Prüfe Ablaufzeit
    if datetime.now(timezone.utc) > state_data["expires_at"]:
        del _oauth_states[state]
        return None
    
    return state_data


def delete_oauth_state(state: str) -> None:
    """
    Löscht OAuth State aus dem Cache.
    
    Args:
        state: OAuth State Token
    """
    _oauth_states.pop(state, None)


def cleanup_expired_states() -> None:
    """
    Bereinigt abgelaufene State Tokens (Cleanup-Job).
    
    Sollte periodisch aufgerufen werden, um Memory-Leaks zu vermeiden.
    """
    now = datetime.now(timezone.utc)
    expired_states = [
        state for state, data in _oauth_states.items()
        if now > data["expires_at"]
    ]
    
    for state in expired_states:
        del _oauth_states[state]
