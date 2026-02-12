#!/usr/bin/env python3
"""
Initialisiert die Datenbank vor Alembic-Migrationen.

Bei frischer Datenbank (keine alembic_version): Erstellt Basistabellen via
SQLModel.create_all und stampt auf head. So werden Migrationen übersprungen,
da das aktuelle Schema bereits vollständig ist.

Bei bestehender Datenbank: Führt alembic upgrade head aus.
"""
import subprocess
import sys
from pathlib import Path

# Projekt-Root für app-Import (wichtig bei Ausführung aus scripts/)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

# Config/Engine müssen vor Model-Import geladen werden (wegen DATA_DIR etc.)
from app.core.database import engine
from app.models import (  # noqa: F401 - für SQLModel.metadata
    DownstreamTrigger,
    Invitation,
    OrchestratorSettings,
    Pipeline,
    PipelineRun,
    RunCellLog,
    ScheduledJob,
    Secret,
    SystemSettings,
    User,
)
from sqlmodel import SQLModel


def is_fresh_database() -> bool:
    """Prüft, ob die Datenbank frisch ist (keine alembic_version oder leer)."""
    try:
        with engine.connect() as conn:
            r = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
            return r.fetchone() is None
    except Exception:
        # Tabelle existiert nicht oder anderer Fehler → frische DB
        return True


def _ensure_alembic_version_table() -> None:
    """
    Erstellt alembic_version mit version_num VARCHAR(64).
    Alembic Standard ist VARCHAR(32), was für lange Revision-IDs (z.B.
    020_add_run_config_to_downstream_triggers) zu kurz ist (PostgreSQL).
    """
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS alembic_version "
                "(version_num VARCHAR(64) NOT NULL PRIMARY KEY)"
            )
        )
        conn.commit()


def main() -> int:
    if is_fresh_database():
        print("[init_db] Fresh database detected, creating schema and stamping...")
        SQLModel.metadata.create_all(engine)
        _ensure_alembic_version_table()
        return subprocess.run(["alembic", "stamp", "head"], check=False).returncode
    else:
        print("[init_db] Existing database, running migrations...")
        return subprocess.run(["alembic", "upgrade", "head"], check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
