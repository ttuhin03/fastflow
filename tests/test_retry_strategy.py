"""
Unit-Tests für Retry-Strategie (app.resilience.retry_strategy).

Testet calculate_retry_delay für alle Strategietypen:
- None / Default
- exponential_backoff
- fixed_delay
- custom_schedule
- Unbekannte Strategie (Fallback)
"""

import pytest

from app.resilience.retry_strategy import calculate_retry_delay


@pytest.mark.asyncio
async def test_calculate_retry_delay_none_returns_default():
    """Keine Strategie: gibt default_delay zurück."""
    result = await calculate_retry_delay(1, None, default_delay=60)
    assert result == 60


@pytest.mark.asyncio
async def test_calculate_retry_delay_exponential_backoff_basic():
    """Exponential Backoff: initial_delay * (multiplier ^ (attempt-1))."""
    strategy = {
        "type": "exponential_backoff",
        "initial_delay": 10,
        "multiplier": 2.0,
    }
    # attempt 1: 10 * 2^0 = 10
    assert await calculate_retry_delay(1, strategy, 60) == 10
    # attempt 2: 10 * 2^1 = 20
    assert await calculate_retry_delay(2, strategy, 60) == 20
    # attempt 3: 10 * 2^2 = 40
    assert await calculate_retry_delay(3, strategy, 60) == 40


@pytest.mark.asyncio
async def test_calculate_retry_delay_exponential_backoff_max_delay():
    """Exponential Backoff: delay wird durch max_delay begrenzt."""
    strategy = {
        "type": "exponential_backoff",
        "initial_delay": 100,
        "multiplier": 10.0,
        "max_delay": 500,
    }
    # attempt 3: 100 * 10^2 = 10000 -> gecappt auf 500
    assert await calculate_retry_delay(3, strategy, 60) == 500


@pytest.mark.asyncio
async def test_calculate_retry_delay_exponential_backoff_defaults():
    """Exponential Backoff mit Standardwerten."""
    strategy = {"type": "exponential_backoff"}
    # Defaults: initial_delay=60, max_delay=3600, multiplier=2.0
    assert await calculate_retry_delay(1, strategy, 99) == 60
    assert await calculate_retry_delay(2, strategy, 99) == 120


@pytest.mark.asyncio
async def test_calculate_retry_delay_fixed_delay():
    """Fixed Delay: immer gleiche Wartezeit."""
    strategy = {"type": "fixed_delay", "delay": 30}
    assert await calculate_retry_delay(1, strategy, 60) == 30
    assert await calculate_retry_delay(5, strategy, 60) == 30


@pytest.mark.asyncio
async def test_calculate_retry_delay_fixed_delay_uses_default_when_missing():
    """Fixed Delay ohne 'delay': nutzt default_delay."""
    strategy = {"type": "fixed_delay"}
    assert await calculate_retry_delay(1, strategy, 45) == 45


@pytest.mark.asyncio
async def test_calculate_retry_delay_custom_schedule():
    """Custom Schedule: Liste von Wartezeiten pro Versuch."""
    strategy = {"type": "custom_schedule", "delays": [5, 10, 20]}
    assert await calculate_retry_delay(1, strategy, 60) == 5
    assert await calculate_retry_delay(2, strategy, 60) == 10
    assert await calculate_retry_delay(3, strategy, 60) == 20


@pytest.mark.asyncio
async def test_calculate_retry_delay_custom_schedule_more_attempts_than_delays():
    """Custom Schedule: mehr Versuche als Wartezeiten -> letzte Wartezeit."""
    strategy = {"type": "custom_schedule", "delays": [10, 20]}
    assert await calculate_retry_delay(3, strategy, 60) == 20
    assert await calculate_retry_delay(5, strategy, 60) == 20


@pytest.mark.asyncio
async def test_calculate_retry_delay_custom_schedule_empty_delays():
    """Custom Schedule mit leerer Liste: default_delay."""
    strategy = {"type": "custom_schedule", "delays": []}
    assert await calculate_retry_delay(1, strategy, 60) == 60


@pytest.mark.asyncio
async def test_calculate_retry_delay_unknown_strategy_fallback():
    """Unbekannte Strategie: Fallback auf default_delay."""
    strategy = {"type": "unknown_strategy", "delay": 999}
    assert await calculate_retry_delay(1, strategy, 60) == 60


@pytest.mark.asyncio
async def test_calculate_retry_delay_empty_type_fallback():
    """Strategie ohne type (default fixed_delay): nutzt default_delay."""
    strategy = {}
    assert await calculate_retry_delay(1, strategy, 75) == 75
