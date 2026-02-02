"""
Retry Strategy Module.

Dieses Modul implementiert verschiedene Retry-Strategien für Pipeline-Runs:
- Exponential Backoff
- Fixed Delay
- Custom Schedule
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


async def calculate_retry_delay(
    attempt: int,
    retry_strategy: Optional[Dict[str, Any]],
    default_delay: int = 60
) -> int:
    """
    Berechnet die Wartezeit vor einem Retry-Versuch basierend auf der Strategie.
    
    Args:
        attempt: Anzahl des aktuellen Versuchs (1 = erster Retry, 2 = zweiter Retry, etc.)
        retry_strategy: Retry-Strategie-Dictionary (None = Fixed Delay mit default_delay)
        default_delay: Standard-Wartezeit in Sekunden (wird verwendet wenn keine Strategie angegeben)
    
    Returns:
        Wartezeit in Sekunden
    """
    if retry_strategy is None:
        # Keine Strategie: Fixed Delay mit Standard-Wert
        return default_delay
    
    strategy_type = retry_strategy.get("type", "fixed_delay")
    
    if strategy_type == "exponential_backoff":
        # Exponential Backoff: initial_delay * (multiplier ^ attempt)
        initial_delay = retry_strategy.get("initial_delay", 60)
        max_delay = retry_strategy.get("max_delay", 3600)  # Max 1 Stunde
        multiplier = retry_strategy.get("multiplier", 2.0)
        
        delay = initial_delay * (multiplier ** (attempt - 1))
        delay = min(delay, max_delay)
        return int(delay)
    
    elif strategy_type == "fixed_delay":
        # Fixed Delay: Immer gleiche Wartezeit
        delay = retry_strategy.get("delay", default_delay)
        return int(delay)
    
    elif strategy_type == "custom_schedule":
        # Custom Schedule: Liste von Wartezeiten (ein Wert pro Retry-Versuch)
        delays = retry_strategy.get("delays", [])
        if not delays:
            return default_delay
        
        # Wenn mehr Versuche als Wartezeiten, verwende letzte Wartezeit
        if attempt > len(delays):
            return int(delays[-1])
        
        return int(delays[attempt - 1])
    
    else:
        logger.warning(f"Unbekannte Retry-Strategie: {strategy_type}. Verwende Fixed Delay.")
        return default_delay


async def wait_for_retry(
    attempt: int,
    retry_strategy: Optional[Dict[str, Any]],
    default_delay: int = 60
) -> None:
    """
    Wartet die berechnete Zeit vor einem Retry-Versuch.
    
    Args:
        attempt: Anzahl des aktuellen Versuchs
        retry_strategy: Retry-Strategie-Dictionary
        default_delay: Standard-Wartezeit in Sekunden
    """
    delay = await calculate_retry_delay(attempt, retry_strategy, default_delay)
    logger.info(f"Warte {delay} Sekunden vor Retry-Versuch {attempt} (Strategie: {retry_strategy.get('type', 'fixed_delay') if retry_strategy else 'default'})")
    await asyncio.sleep(delay)
