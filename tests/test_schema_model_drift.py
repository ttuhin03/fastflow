"""
Tests gegen Drift zwischen Modellen und Migrationen.

Frische Installationen bauen ihr Schema über ``SQLModel.metadata.create_all`` und
werden danach auf head gestempelt (scripts/init_db_for_migrations.py). Die
Migrationskette lässt sich gar nicht von Null ausführen — Migration 001 setzt
bestehende Tabellen voraus. Die Modelle sind damit die einzige vollständige
Schemabeschreibung, und alles, was nur in einer Migration steht, fehlt jeder neuen
Datenbank dauerhaft.

Genau das war passiert:

- ``ix_pipeline_runs_pipeline_name_started_at`` (Migration 014) fehlte. Ohne den
  Index sortiert "letzte N Runs einer Pipeline" alle Treffer erst in einen
  temporären B-Baum, bevor das LIMIT greift.
- Die ondelete-Regeln aus den Migrationen 012, 025 und 028 fehlten. Auf PostgreSQL
  sind Fremdschlüssel scharf: Ohne sie scheitert das Löschen eines Runs, einer
  Pipeline oder eines Users mit IntegrityError.

Der Test prüft nicht diese vier Fälle einzeln ab, sondern die Regel dahinter:
Was eine Migration anlegt, muss auch im Modell stehen.
"""

import pathlib
import re

import pytest
from sqlalchemy import create_engine, inspect
from sqlmodel import SQLModel

import app.models  # noqa: F401  – füllt SQLModel.metadata

VERSIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "alembic" / "versions"

# op.create_index("name", "tabelle", ["spalte", ...])  /  op.create_index(op.f("name"), ...)
_INDEX_RE = re.compile(
    r"""op\.create_index\(\s*(?:op\.f\(\s*)?["']([^"']+)["']\)?\s*,\s*["']([^"']+)["']\s*,\s*\[([^\]]*)\]""",
    re.VERBOSE,
)
# sa.ForeignKeyConstraint(["spalte"], ["ziel.spalte"], ondelete="REGEL")
_FK_RE = re.compile(
    r"""ForeignKeyConstraint\(\s*\[([^\]]*)\]\s*,\s*\[([^\]]*)\]\s*,\s*ondelete\s*=\s*["']([^"']+)["']""",
)


def _namen(gruppe: str):
    return [t.strip().strip("\"'") for t in gruppe.split(",") if t.strip()]


def _migrationsdateien():
    return sorted(VERSIONS_DIR.glob("[0-9]*.py"))


def _tabelle_aus_migration(text: str, spalten: list) -> str:
    """
    Ermittelt die Tabelle eines ForeignKeyConstraint aus dem create_table-Aufruf.

    Die Constraints stehen innerhalb von ``op.create_table("name", ...)``; die
    Zuordnung über den nächstgelegenen vorangehenden create_table-Aufruf reicht,
    weil die Migrationen je Datei höchstens eine Tabelle mit ondelete anlegen.
    """
    treffer = re.findall(r"""op\.create_table\(\s*["']([^"']+)["']""", text)
    return treffer[0] if treffer else ""


def _spalten_abgedeckt(modell_tabelle, spalten: list) -> bool:
    """
    Prüft, ob das Modell die Spaltenfolge bereits indexiert.

    Verglichen werden Spalten, nicht Indexnamen: Ein Index ist auch dann erfüllt,
    wenn ein anderer Index oder der Primärschlüssel dieselben Spalten als führendes
    Präfix hat. So verlangt der Test keine redundanten Indizes — bei
    pipeline_daily_stats etwa deckt der Primärschlüssel (pipeline_name, day) den
    Index aus Migration 025 vollständig ab, ein zweiter wäre reiner Ballast.
    """
    kandidaten = [list(i.columns.keys()) for i in modell_tabelle.indexes]
    if modell_tabelle.primary_key is not None:
        kandidaten.append(list(modell_tabelle.primary_key.columns.keys()))
    for constraint in modell_tabelle.constraints:
        spalten_der_constraint = getattr(constraint, "columns", None)
        if spalten_der_constraint is not None:
            kandidaten.append(list(spalten_der_constraint.keys()))
    return any(vorhanden[:len(spalten)] == spalten for vorhanden in kandidaten)


def test_migrationsdateien_werden_gefunden():
    """Absicherung der Prüflogik: Ohne gefundene Migrationen liefen die Tests leer grün."""
    dateien = _migrationsdateien()
    assert len(dateien) >= 40, f"Nur {len(dateien)} Migrationen gefunden"


def _erwartete_indizes():
    """Alle Indizes, die irgendeine Migration anlegt, als (tabelle, name, spalten)."""
    for datei in _migrationsdateien():
        for name, tabelle, spalten in _INDEX_RE.findall(datei.read_text()):
            yield datei.name, tabelle, name, _namen(spalten)


def test_alle_von_migrationen_angelegten_indizes_stehen_im_modell():
    """
    Was eine Migration als Index anlegt, muss das Modell ebenfalls kennen — sonst
    fehlt er jeder Datenbank, die über create_all entstanden ist.

    Übersprungen werden Indizes auf Tabellen oder Spalten, die es im Modell nicht
    mehr gibt: Solche Migrationen wurden später zurückgebaut (z. B. 006, das die
    Invitation-Spalten aus users entfernt hat).
    """
    tabellen = SQLModel.metadata.tables
    fehlend = []

    for datei, tabelle, name, spalten in _erwartete_indizes():
        if tabelle not in tabellen:
            continue
        modell_tabelle = tabellen[tabelle]
        if any(s not in modell_tabelle.columns for s in spalten):
            continue  # Spalte später entfernt

        if not _spalten_abgedeckt(modell_tabelle, spalten):
            fehlend.append(f"{tabelle}.{name} (aus {datei}, Spalten {spalten})")

    assert not fehlend, (
        "Diese Indizes legen Migrationen an, die Modelle aber nicht. Frische "
        "Installationen bekommen sie damit nie:\n  " + "\n  ".join(fehlend)
    )


def test_alle_ondelete_regeln_der_migrationen_stehen_im_modell():
    """
    Dasselbe für ondelete-Regeln. Fehlen sie im Modell, scheitern die
    entsprechenden DELETEs auf PostgreSQL mit IntegrityError.
    """
    tabellen = SQLModel.metadata.tables
    fehlend = []
    geprueft = 0

    for datei in _migrationsdateien():
        text = datei.read_text()
        for spalten_gruppe, _ziel, regel in _FK_RE.findall(text):
            spalten = _namen(spalten_gruppe)
            tabelle = _tabelle_aus_migration(text, spalten)
            if tabelle not in tabellen:
                continue
            modell_tabelle = tabellen[tabelle]
            if any(s not in modell_tabelle.columns for s in spalten):
                continue

            geprueft += 1
            passend = [
                fk for fk in modell_tabelle.foreign_keys
                if fk.parent.name in spalten and (fk.ondelete or "").upper() == regel.upper()
            ]
            if not passend:
                ist = {fk.parent.name: fk.ondelete for fk in modell_tabelle.foreign_keys
                       if fk.parent.name in spalten}
                fehlend.append(f"{tabelle}.{spalten}: erwartet {regel}, Modell hat {ist} ({datei.name})")

    assert geprueft >= 3, f"Nur {geprueft} ondelete-Regeln geprüft – Extraktion kaputt?"
    assert not fehlend, (
        "Diese ondelete-Regeln stehen nur in Migrationen, nicht im Modell:\n  "
        + "\n  ".join(fehlend)
    )


@pytest.fixture(scope="module")
def inspector(tmp_path_factory):
    """Inspector auf einer Datenbank, die ausschliesslich über create_all entstand."""
    pfad = tmp_path_factory.mktemp("schema") / "create_all.db"
    engine = create_engine(f"sqlite:///{pfad}")
    SQLModel.metadata.create_all(engine)
    yield inspect(engine)
    engine.dispose()


class TestCreateAllErzeugtVollstaendigesSchema:
    """Was create_all tatsächlich in eine leere Datenbank schreibt."""

    def test_composite_index_auf_pipeline_runs(self, inspector):
        """
        Trägt die häufigste Query der App: "letzte N Runs einer Pipeline".
        Ohne ihn braucht SQLite einen temporären B-Baum für das ORDER BY.
        """
        namen = {i["name"] for i in inspector.get_indexes("pipeline_runs")}
        assert "ix_pipeline_runs_pipeline_name_started_at" in namen

    @pytest.mark.parametrize(
        "tabelle,spalte,regel",
        [
            ("run_cell_logs", "run_id", "CASCADE"),
            ("pipeline_daily_stats", "pipeline_name", "CASCADE"),
            ("audit_log", "user_id", "SET NULL"),
        ],
    )
    def test_ondelete_regeln(self, inspector, tabelle, spalte, regel):
        treffer = [
            fk for fk in inspector.get_foreign_keys(tabelle)
            if spalte in fk["constrained_columns"]
        ]
        assert treffer, f"Kein Fremdschlüssel auf {tabelle}.{spalte}"
        assert (treffer[0].get("options") or {}).get("ondelete") == regel


class TestVerwaisteZellenLogs:
    """
    Beim Löschen eines Runs müssen seine Zellen-Logs mitgehen.

    Verlassen kann man sich dabei nicht auf ON DELETE CASCADE: SQLite prüft
    Fremdschlüssel nur bei ``PRAGMA foreign_keys=ON``, und Fast-Flow aktiviert das
    bewusst nicht — bestehende Datenbanken haben teils Constraints ohne passende
    Regel und würden dann beim Löschen scheitern. Ohne explizites Löschen blieben
    die Zeilen für immer liegen, inklusive der Base64-Bilder in ``outputs``.
    """

    def test_cleanup_loescht_die_zellen_logs_mit(self, tmp_path):
        from datetime import datetime, timezone
        from uuid import uuid4

        from sqlmodel import Session, select

        from app.models import PipelineRun, RunCellLog
        from app.services.cleanup import _delete_run_row

        engine = create_engine(f"sqlite:///{tmp_path / 'cleanup.db'}")
        SQLModel.metadata.create_all(engine)
        try:
            run_id = uuid4()
            with Session(engine) as session:
                session.add(PipelineRun(
                    id=run_id,
                    pipeline_name="demo",
                    log_file="/tmp/demo.log",
                    started_at=datetime.now(timezone.utc),
                ))
                session.add(RunCellLog(run_id=run_id, cell_index=0, stdout="a"))
                session.add(RunCellLog(run_id=run_id, cell_index=1, stdout="b"))
                session.commit()

            with Session(engine) as session:
                run = session.get(PipelineRun, run_id)
                _delete_run_row(session, run)
                session.commit()

            with Session(engine) as session:
                assert session.get(PipelineRun, run_id) is None
                uebrig = session.exec(
                    select(RunCellLog).where(RunCellLog.run_id == run_id)
                ).all()
                assert uebrig == [], f"{len(uebrig)} verwaiste Zellen-Logs geblieben"
        finally:
            engine.dispose()

    def test_zellen_logs_anderer_runs_bleiben(self, tmp_path):
        """Die Löschbedingung muss auf den Run eingeschränkt sein."""
        from datetime import datetime, timezone
        from uuid import uuid4

        from sqlmodel import Session, select

        from app.models import PipelineRun, RunCellLog
        from app.services.cleanup import _delete_run_row

        engine = create_engine(f"sqlite:///{tmp_path / 'cleanup2.db'}")
        SQLModel.metadata.create_all(engine)
        try:
            alt, neu = uuid4(), uuid4()
            with Session(engine) as session:
                for rid in (alt, neu):
                    session.add(PipelineRun(
                        id=rid, pipeline_name="demo", log_file="/tmp/x.log",
                        started_at=datetime.now(timezone.utc),
                    ))
                    session.add(RunCellLog(run_id=rid, cell_index=0, stdout="x"))
                session.commit()

            with Session(engine) as session:
                _delete_run_row(session, session.get(PipelineRun, alt))
                session.commit()

            with Session(engine) as session:
                assert session.exec(
                    select(RunCellLog).where(RunCellLog.run_id == neu)
                ).all()
        finally:
            engine.dispose()
