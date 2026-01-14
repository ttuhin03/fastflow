"""
Pytest Configuration und Fixtures.

Dieses Modul definiert gemeinsame Fixtures für alle Tests:
- Test-Datenbank (in-memory SQLite)
- Test-Client
- Test-Session
"""

import pytest
from pathlib import Path
from sqlmodel import SQLModel, create_engine, Session
from fastapi.testclient import TestClient

from app.config import config
from app.main import app


@pytest.fixture(scope="function")
def test_db():
    """
    Erstellt eine temporäre Test-Datenbank (in-memory SQLite).
    
    Yields:
        Engine: SQLModel Engine für Test-Datenbank
    """
    # In-Memory SQLite-Datenbank für Tests
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        echo=False
    )
    
    # Tabellen erstellen
    SQLModel.metadata.create_all(test_engine)
    
    # WAL-Mode aktivieren (für SQLite)
    with Session(test_engine) as session:
        from sqlmodel import text
        session.execute(text("PRAGMA journal_mode=WAL"))
        session.commit()
    
    yield test_engine
    
    # Cleanup
    SQLModel.metadata.drop_all(test_engine)
    test_engine.dispose()


@pytest.fixture(scope="function")
def test_session(test_db):
    """
    Erstellt eine Test-Datenbank-Session.
    
    Args:
        test_db: Test-Datenbank-Engine (Fixture)
    
    Yields:
        Session: SQLModel Session für Tests
    """
    with Session(test_db) as session:
        yield session


@pytest.fixture(scope="function")
def client(test_session):
    """
    Erstellt einen FastAPI Test-Client.
    
    Args:
        test_session: Test-Datenbank-Session (Fixture)
    
    Returns:
        TestClient: FastAPI Test-Client
    """
    # Dependency Override für get_session
    def override_get_session():
        yield test_session
    
    from app.database import get_session
    app.dependency_overrides[get_session] = override_get_session
    
    with TestClient(app) as test_client:
        yield test_client
    
    # Cleanup
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def temp_pipelines_dir(tmp_path):
    """
    Erstellt ein temporäres Pipelines-Verzeichnis für Tests.
    
    Args:
        tmp_path: Pytest tmp_path Fixture
    
    Returns:
        Path: Pfad zum temporären Pipelines-Verzeichnis
    """
    pipelines_dir = tmp_path / "pipelines"
    pipelines_dir.mkdir()
    
    # Original PIPELINES_DIR speichern
    original_pipelines_dir = config.PIPELINES_DIR
    
    # Temporäres Verzeichnis setzen
    config.PIPELINES_DIR = pipelines_dir
    
    yield pipelines_dir
    
    # Original wiederherstellen
    config.PIPELINES_DIR = original_pipelines_dir


@pytest.fixture(scope="function")
def temp_logs_dir(tmp_path):
    """
    Erstellt ein temporäres Logs-Verzeichnis für Tests.
    
    Args:
        tmp_path: Pytest tmp_path Fixture
    
    Returns:
        Path: Pfad zum temporären Logs-Verzeichnis
    """
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    
    # Original LOGS_DIR speichern
    original_logs_dir = config.LOGS_DIR
    
    # Temporäres Verzeichnis setzen
    config.LOGS_DIR = logs_dir
    
    yield logs_dir
    
    # Original wiederherstellen
    config.LOGS_DIR = original_logs_dir


@pytest.fixture(scope="function")
def temp_data_dir(tmp_path):
    """
    Erstellt ein temporäres Data-Verzeichnis für Tests.
    
    Args:
        tmp_path: Pytest tmp_path Fixture
    
    Returns:
        Path: Pfad zum temporären Data-Verzeichnis
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    
    # Original DATA_DIR speichern
    original_data_dir = config.DATA_DIR
    
    # Temporäres Verzeichnis setzen
    config.DATA_DIR = data_dir
    
    yield data_dir
    
    # Original wiederherstellen
    config.DATA_DIR = original_data_dir
