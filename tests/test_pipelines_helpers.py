"""
Unit-Tests für Pipeline-API-Hilfsfunktionen (app.api.pipelines).

Testet _path_within_pipelines_dir und _parse_date_range.
"""

import pytest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException

from app.api.pipelines import _path_within_pipelines_dir, _parse_date_range
from app.core.config import config


def test_path_within_pipelines_dir_inside(temp_pipelines_dir):
    """Pfad innerhalb von PIPELINES_DIR: True."""
    subdir = temp_pipelines_dir / "my_pipeline"
    subdir.mkdir()
    assert _path_within_pipelines_dir(subdir) is True
    assert _path_within_pipelines_dir(subdir / "main.py") is True


def test_path_within_pipelines_dir_outside(temp_pipelines_dir):
    """Pfad außerhalb von PIPELINES_DIR: False."""
    outside = Path("/tmp/other")
    assert _path_within_pipelines_dir(outside) is False
    # Path Traversal-Versuch
    traversal = temp_pipelines_dir / ".." / "etc" / "passwd"
    assert _path_within_pipelines_dir(traversal) is False


def test_path_within_pipelines_dir_root(temp_pipelines_dir):
    """Root-Pfad außerhalb: False."""
    assert _path_within_pipelines_dir(Path("/")) is False


def test_parse_date_range_start_and_end():
    """start_date und end_date: liefert (start_dt, end_dt)."""
    start_dt, end_dt = _parse_date_range(
        start_date="2024-01-15",
        end_date="2024-01-20",
        days=7,
    )
    assert start_dt.year == 2024 and start_dt.month == 1 and start_dt.day == 15
    assert end_dt.year == 2024 and end_dt.month == 1 and end_dt.day == 20
    assert end_dt.hour == 23 and end_dt.minute == 59 and end_dt.second == 59


def test_parse_date_range_start_only():
    """nur start_date: end_dt = now (UTC)."""
    start_dt, end_dt = _parse_date_range(
        start_date="2024-01-01",
        end_date=None,
        days=7,
    )
    assert start_dt.year == 2024 and start_dt.month == 1 and start_dt.day == 1
    assert end_dt.tzinfo == timezone.utc
    # end sollte jetzt oder kurz danach sein
    assert (datetime.now(timezone.utc) - end_dt).total_seconds() >= -2


def test_parse_date_range_end_only():
    """nur end_date: start_dt = end - days."""
    start_dt, end_dt = _parse_date_range(
        start_date=None,
        end_date="2024-01-31",
        days=7,
    )
    assert end_dt.year == 2024 and end_dt.month == 1 and end_dt.day == 31
    assert (end_dt - start_dt).days == 7


def test_parse_date_range_neither():
    """weder start noch end: Standardbereich (days)."""
    now = datetime.now(timezone.utc)
    start_dt, end_dt = _parse_date_range(
        start_date=None,
        end_date=None,
        days=14,
    )
    assert (end_dt - start_dt).days == 14
    assert end_dt.hour == 23 and end_dt.minute == 59 and end_dt.second == 59
    assert start_dt.hour == 0 and start_dt.minute == 0 and start_dt.second == 0


def test_parse_date_range_invalid_start():
    """Ungültiges start_date: HTTPException 400."""
    with pytest.raises(HTTPException) as exc_info:
        _parse_date_range(start_date="invalid", end_date="2024-01-20", days=7)
    assert exc_info.value.status_code == 400
    assert "Ungültiges Datumsformat" in exc_info.value.detail


def test_parse_date_range_invalid_end():
    """Ungültiges end_date: HTTPException 400."""
    with pytest.raises(HTTPException) as exc_info:
        _parse_date_range(start_date=None, end_date="2024-13-99", days=7)
    assert exc_info.value.status_code == 400


def test_parse_date_range_start_after_end():
    """start_date nach end_date: HTTPException 400."""
    with pytest.raises(HTTPException) as exc_info:
        _parse_date_range(
            start_date="2024-01-20",
            end_date="2024-01-15",
            days=7,
        )
    assert exc_info.value.status_code == 400
    assert "Startdatum muss vor Enddatum" in exc_info.value.detail


def test_parse_date_range_iso_datetime():
    """ISO-Format mit Zeit wird akzeptiert."""
    start_dt, end_dt = _parse_date_range(
        start_date="2024-01-15T10:00:00",
        end_date="2024-01-20T18:30:00",
        days=7,
    )
    assert start_dt.month == 1 and start_dt.day == 15
    assert end_dt.hour == 23 and end_dt.minute == 59  # end wird auf Tagesende gesetzt
