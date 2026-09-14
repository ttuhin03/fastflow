"""Align schema with models: composite index and ondelete rules

Revision ID: 041_align_schema_with_models
Revises: 040_add_user_last_login
Create Date: 2026-09-14

Frische Installationen bauen ihr Schema nicht über diese Migrationen, sondern über
SQLModel.create_all und werden anschließend auf head gestempelt (siehe
scripts/init_db_for_migrations.py — die Kette lässt sich gar nicht von Null
ausführen, Migration 001 setzt bestehende Tabellen voraus). Alles, was nur in einer
Migration stand und nicht im Modell, fehlte solchen Datenbanken deshalb dauerhaft:

- ix_pipeline_runs_pipeline_name_started_at (Migration 014). Ohne den Index muss
  "letzte N Runs einer Pipeline" alle Treffer erst in einen temporären B-Baum
  sortieren, bevor das LIMIT greift.
- ondelete-Regeln auf run_cell_logs.run_id, pipeline_daily_stats.pipeline_name und
  audit_log.user_id (Migrationen 012, 025, 028). Auf PostgreSQL sind die Constraints
  scharf: Ohne die Regeln scheitert das Löschen eines Runs, einer Pipeline oder eines
  Users an IntegrityError.

Die Modelle tragen beides jetzt selbst, sodass create_all ein vollständiges Schema
erzeugt. Diese Migration holt es für bereits bestehende Datenbanken nach.
"""
from alembic import op
import sqlalchemy as sa

revision = "041_align_schema_with_models"
down_revision = "040_add_user_last_login"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_pipeline_runs_pipeline_name_started_at"

# Tabelle, Spalte, Zieltabelle, Zielspalte, Regel
FOREIGN_KEYS = [
    ("run_cell_logs", "run_id", "pipeline_runs", "id", "CASCADE"),
    ("pipeline_daily_stats", "pipeline_name", "pipelines", "pipeline_name", "CASCADE"),
    ("audit_log", "user_id", "users", "id", "SET NULL"),
]


def _inspector():
    return sa.inspect(op.get_bind())


def _index_anlegen(inspector) -> None:
    """Composite-Index nachziehen. Idempotent, weil Datenbanken aus der
    Migrationskette ihn seit 014 schon haben."""
    vorhanden = {i["name"] for i in inspector.get_indexes("pipeline_runs")}
    if INDEX_NAME not in vorhanden:
        op.create_index(INDEX_NAME, "pipeline_runs", ["pipeline_name", "started_at"])


def _ondelete_regel(fk) -> str:
    return (fk.get("options") or {}).get("ondelete") or ""


def _ondelete_nachziehen(
    inspector, tabelle: str, spalte: str, ziel_tabelle: str, ziel_spalte: str, regel: str
) -> None:
    """Ersetzt den Fremdschlüssel auf ``tabelle.spalte`` durch einen mit ``regel``."""
    for fk in inspector.get_foreign_keys(tabelle):
        if spalte not in fk["constrained_columns"]:
            continue
        if _ondelete_regel(fk) == regel:
            continue  # bereits korrekt (Datenbank aus der Migrationskette)
        if fk.get("name"):
            op.drop_constraint(fk["name"], tabelle, type_="foreignkey")
        op.create_foreign_key(
            f"fk_{tabelle}_{spalte}",
            tabelle,
            ziel_tabelle,
            [spalte],
            [ziel_spalte],
            ondelete=regel,
        )


def upgrade() -> None:
    inspector = _inspector()
    tabellen = set(inspector.get_table_names())

    if "pipeline_runs" in tabellen:
        _index_anlegen(inspector)

    # ondelete-Regeln bewusst nur auf PostgreSQL:
    # SQLite prüft Fremdschlüssel nur bei PRAGMA foreign_keys=ON, und Fast-Flow
    # setzt das nicht (es würde bestehende Datenbanken mit unpassenden Regeln beim
    # Löschen scheitern lassen). Dort hätte die Änderung also keine Wirkung, kostete
    # aber einen vollständigen Tabellen-Rebuild — inklusive Kopie der Base64-Bilder
    # in run_cell_logs.outputs. Verwaiste Zeilen verhindert unter SQLite stattdessen
    # app.services.cleanup, das Kindzeilen explizit löscht.
    if op.get_bind().dialect.name != "postgresql":
        return

    for tabelle, spalte, ziel_tabelle, ziel_spalte, regel in FOREIGN_KEYS:
        if tabelle in tabellen:
            _ondelete_nachziehen(
                inspector, tabelle, spalte, ziel_tabelle, ziel_spalte, regel
            )


def downgrade() -> None:
    # Die ondelete-Regeln werden nicht zurückgebaut: Sie sind der Zustand, den die
    # Migrationen 012/025/028 ohnehin vorsehen, und ein Rückbau würde auf
    # PostgreSQL das Löschen von Runs, Pipelines und Usern wieder brechen.
    inspector = _inspector()
    if "pipeline_runs" not in set(inspector.get_table_names()):
        return
    if INDEX_NAME in {i["name"] for i in inspector.get_indexes("pipeline_runs")}:
        op.drop_index(INDEX_NAME, table_name="pipeline_runs")
