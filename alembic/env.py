"""
Alembic Environment Configuration.

Dieses Modul konfiguriert Alembic für Migrationen mit SQLModel.
Unterstützt SQLite (mit render_as_batch=True) und PostgreSQL.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Import SQLModel und Models für Metadaten-Registrierung
from sqlmodel import SQLModel
from app.models import Pipeline, PipelineRun, ScheduledJob, Secret, User  # noqa: F401
from app.config import config as app_config

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# SQLModel Metadata für autogenerate
target_metadata = SQLModel.metadata

# Database URL aus app.config verwenden
# Überschreibe sqlalchemy.url in config, falls DATABASE_URL gesetzt ist
if app_config.DATABASE_URL is not None:
    database_url = app_config.DATABASE_URL
else:
    # SQLite Standard-URL
    database_url = f"sqlite:///{app_config.DATA_DIR}/fastflow.db"

config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    """
    Führt Migrationen im 'offline' Modus durch.
    
    Konfiguriert den Context nur mit URL (ohne Engine).
    SQLite-batch-Mode wird hier nicht benötigt, da offline-Mode
    nur für SQL-Generierung verwendet wird.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Führt Migrationen im 'online' Modus durch.
    
    Erstellt Engine und verbindet mit Datenbank.
    Aktiviert render_as_batch=True für SQLite (verwendet
    "Tabelle kopieren, ändern, Original löschen"-Strategie).
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # SQLite: render_as_batch=True für Batch-Operationen
        # Verhindert Fehler bei Spalten-Löschen/Umbenennen (SQLite-Limitation)
        use_batch_mode = database_url.startswith("sqlite")
        
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=use_batch_mode,  # Batch-Mode für SQLite
            compare_type=True,  # Spalten-Typ-Änderungen erkennen
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
