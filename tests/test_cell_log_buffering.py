"""
Tests für die gepufferte Persistenz der Notebook-Zellen-Logs.

Vorher wurde jede Ausgabezeile einzeln geschrieben, als Read-Modify-Write mit
eigener Session und eigenem Commit: Zeile laden, Text in Python anhängen, alles
zurückschreiben. Der Schreibaufwand wuchs damit quadratisch zur Ausgabemenge einer
Zelle — 10.000 Ausgabezeilen bedeuteten 10.000 Transaktionen und rund 50 Mio.
geschriebene Zeichen statt 10.000.

Geprüft werden die Eigenschaften, die das ablösen:
1. Das Protokoll wird korrekt geparst (reine Funktion, ohne Datenbank).
2. Ausgaben landen gebündelt in der Datenbank statt einzeln.
3. Angehängt wird in SQL, der Aufwand bleibt linear zur Ausgabemenge.
4. Ein Statuswechsel überholt die Ausgabe nicht, die ihm vorausging.
5. Der Abbruchpfad verliert die zuletzt gepufferten Zeilen nicht.
6. Die Log-Datei wird zeitgetaktet geflusht statt nach jeder Zeile.
"""

import asyncio
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from app.executor.cell_logs import (
    PREFIX_CELL_END,
    PREFIX_CELL_OUTPUT,
    PREFIX_CELL_START,
    CellEnd,
    CellImage,
    CellLogBuffer,
    CellStart,
    CellText,
    parse_cell_line,
)
from app.models import RunCellLog


class TestProtokollParsen:
    """parse_cell_line ist eine reine Funktion — das Protokoll für sich testbar."""

    def test_zellstart(self):
        assert parse_cell_line(PREFIX_CELL_START + "3") == CellStart(cell_index=3)

    def test_zellende_mit_status(self):
        ereignis = parse_cell_line(PREFIX_CELL_END + "2\tSUCCESS")
        assert ereignis == CellEnd(cell_index=2, status="SUCCESS", message="")

    def test_zellende_mit_retry_nachricht(self):
        ereignis = parse_cell_line(PREFIX_CELL_END + "1\tRETRYING\t2\tValueError: kaputt")
        assert ereignis.status == "RETRYING"
        assert "ValueError" in ereignis.message

    def test_stdout_bekommt_zeilenumbruch(self):
        ereignis = parse_cell_line(PREFIX_CELL_OUTPUT + "0\tstdout\tplain\thallo")
        assert ereignis == CellText(cell_index=0, stream="stdout", text="hallo\n")

    def test_base64_wird_dekodiert(self):
        ereignis = parse_cell_line(PREFIX_CELL_OUTPUT + "0\tstdout\tbase64\taGFsbG8=")
        assert ereignis.text == "hallo\n"

    def test_bild(self):
        ereignis = parse_cell_line(PREFIX_CELL_OUTPUT + "0\timage\timage/png\tBASE64DATA")
        assert ereignis == CellImage(cell_index=0, mime="image/png", data="BASE64DATA")

    @pytest.mark.parametrize("zeile", [
        "ganz normale Log-Zeile",
        "",
        PREFIX_CELL_END + "5",                      # Status fehlt
        PREFIX_CELL_OUTPUT + "0\tstdout",           # zu wenige Felder
        PREFIX_CELL_START + "keine-zahl",           # kaputter Index
        PREFIX_CELL_OUTPUT + "0\tunbekannt\tx\ty",  # unbekannter Stream
    ])
    def test_nicht_verwertbare_zeilen_ergeben_none(self, zeile):
        assert parse_cell_line(zeile) is None


@pytest.fixture
def db(tmp_path):
    """Echte SQLite-Datei plus Zähler für ausgeführte Schreib-Statements."""
    engine = create_engine(f"sqlite:///{tmp_path / 'cells.db'}")
    SQLModel.metadata.create_all(engine)
    statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def _mitzaehlen(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE")):
            statements.append(statement)

    engine.statements = statements
    yield engine
    engine.dispose()


def _buffer(engine, run_id, **kwargs):
    return CellLogBuffer(
        run_id,
        session_factory=lambda: Session(engine),
        flush_interval=kwargs.pop("flush_interval", 3600),  # Hintergrund-Flush aus
        **kwargs,
    )


def _zelle(engine, run_id, index=0):
    with Session(engine) as session:
        return session.exec(
            select(RunCellLog)
            .where(RunCellLog.run_id == run_id)
            .where(RunCellLog.cell_index == index)
        ).first()


class TestBuendelung:
    """Ausgaben werden gesammelt statt einzeln geschrieben."""

    @pytest.mark.parametrize("zeilen", [100, 1000])
    def test_zahl_der_schreibvorgaenge_haengt_nicht_an_der_zeilenzahl(self, db, zeilen):
        """
        Die entscheidende Eigenschaft: Ein Flush ist ein Schreibvorgang, egal wie
        viele Zeilen er bündelt. Vorher war es einer pro Zeile.

        Zwei Statements sind es, weil das UPDATE ohne vorheriges CELL_START keine
        Zeile trifft und einmalig ein INSERT folgt — konstant, nicht pro Zeile.
        """
        run_id = uuid4()
        puffer = _buffer(db, run_id, max_pending_chars=10**9)

        async def ablauf():
            for i in range(zeilen):
                await puffer.handle_line(
                    PREFIX_CELL_OUTPUT + f"0\tstdout\tplain\tZeile {i}"
                )
            await puffer.flush()

        asyncio.run(ablauf())

        assert len(db.statements) == 2, (
            f"{len(db.statements)} Schreib-Statements für {zeilen} Zeilen – "
            "die Bündelung greift nicht"
        )
        zelle = _zelle(db, run_id)
        assert zelle.stdout.count("\n") == zeilen
        assert zelle.stdout.startswith("Zeile 0\n")
        assert zelle.stdout.endswith(f"Zeile {zeilen - 1}\n")

    def test_aufwand_waechst_linear_nicht_quadratisch(self, db):
        """
        Der eigentliche Punkt: Beim Read-Modify-Write wuchs die geschriebene
        Datenmenge quadratisch. Zehnmal so viele Zeilen dürfen daher nicht
        hundertmal so viel Arbeit bedeuten.
        """
        laengen = {}
        for anzahl in (50, 500):
            run_id = uuid4()
            puffer = _buffer(db, run_id, max_pending_chars=10**9)
            db.statements.clear()

            async def ablauf():
                for i in range(anzahl):
                    await puffer.handle_line(
                        PREFIX_CELL_OUTPUT + f"0\tstdout\tplain\tZeile {i}"
                    )
                await puffer.flush()

            asyncio.run(ablauf())
            laengen[anzahl] = sum(len(s) for s in db.statements)

        # Zehnfache Zeilenzahl -> höchstens etwa zehnfache Statement-Länge.
        # Quadratisch wären es rund hundertfach.
        assert laengen[500] < laengen[50] * 20, laengen

    def test_grosse_ausgabe_wird_zwischendurch_geschrieben(self, db):
        """Der Puffer darf nicht unbegrenzt wachsen."""
        run_id = uuid4()
        puffer = _buffer(db, run_id, max_pending_chars=200)

        async def ablauf():
            for i in range(100):
                await puffer.handle_line(
                    PREFIX_CELL_OUTPUT + f"0\tstdout\tplain\t{'x' * 20}"
                )
            await puffer.flush()

        asyncio.run(ablauf())
        assert len(db.statements) > 1, "Schwellwert löst keinen Zwischen-Flush aus"
        assert _zelle(db, run_id).stdout.count("\n") == 100

    def test_text_wird_angehaengt_nicht_ersetzt(self, db):
        """Mehrere Flush-Runden derselben Zelle müssen sich aufaddieren."""
        run_id = uuid4()
        puffer = _buffer(db, run_id)

        async def ablauf():
            for text in ("erste", "zweite", "dritte"):
                await puffer.handle_line(PREFIX_CELL_OUTPUT + f"0\tstdout\tplain\t{text}")
                await puffer.flush()

        asyncio.run(ablauf())
        assert _zelle(db, run_id).stdout == "erste\nzweite\ndritte\n"

    def test_stdout_und_stderr_bleiben_getrennt(self, db):
        run_id = uuid4()
        puffer = _buffer(db, run_id)

        async def ablauf():
            await puffer.handle_line(PREFIX_CELL_OUTPUT + "0\tstdout\tplain\traus")
            await puffer.handle_line(PREFIX_CELL_OUTPUT + "0\tstderr\tplain\tfehler")
            await puffer.flush()

        asyncio.run(ablauf())
        zelle = _zelle(db, run_id)
        assert zelle.stdout == "raus\n"
        assert zelle.stderr == "fehler\n"


class TestReihenfolge:
    """Ein Statuswechsel darf die Ausgabe nicht überholen, die ihm vorausging."""

    def test_ausgabe_vor_zellende_ist_persistiert(self, db):
        run_id = uuid4()
        puffer = _buffer(db, run_id)

        async def ablauf():
            await puffer.handle_line(PREFIX_CELL_START + "0")
            await puffer.handle_line(PREFIX_CELL_OUTPUT + "0\tstdout\tplain\tletzte Ausgabe")
            # Kein flush() dazwischen: das Zellende muss den Puffer selbst leeren.
            await puffer.handle_line(PREFIX_CELL_END + "0\tSUCCESS")

        asyncio.run(ablauf())
        zelle = _zelle(db, run_id)
        assert zelle.status == "SUCCESS"
        assert zelle.stdout == "letzte Ausgabe\n"

    def test_fehlschlag_wird_in_stderr_vermerkt(self, db):
        run_id = uuid4()
        puffer = _buffer(db, run_id)

        async def ablauf():
            await puffer.handle_line(PREFIX_CELL_START + "0")
            await puffer.handle_line(PREFIX_CELL_END + "0\tFAILED")

        asyncio.run(ablauf())
        zelle = _zelle(db, run_id)
        assert zelle.status == "FAILED"
        assert "Endgültig fehlgeschlagen" in zelle.stderr

    def test_retry_versuche_sammeln_sich(self, db):
        run_id = uuid4()
        puffer = _buffer(db, run_id)

        async def ablauf():
            await puffer.handle_line(PREFIX_CELL_START + "0")
            await puffer.handle_line(PREFIX_CELL_END + "0\tRETRYING\t1\terster Fehler")
            await puffer.handle_line(PREFIX_CELL_END + "0\tRETRYING\t2\tzweiter Fehler")

        asyncio.run(ablauf())
        stderr = _zelle(db, run_id).stderr
        assert "erster Fehler" in stderr and "zweiter Fehler" in stderr

    def test_ausgabe_ohne_vorherigen_zellstart_legt_die_zeile_an(self, db):
        """Robustheit: Das UPDATE trifft dann keine Zeile, es muss eingefügt werden."""
        run_id = uuid4()
        puffer = _buffer(db, run_id)

        async def ablauf():
            await puffer.handle_line(PREFIX_CELL_OUTPUT + "7\tstdout\tplain\tverwaist")
            await puffer.flush()

        asyncio.run(ablauf())
        assert _zelle(db, run_id, index=7).stdout == "verwaist\n"


class TestBilder:
    def test_mehrere_bilder_gehen_nicht_verloren(self, db):
        """
        Vorher wurde das outputs-JSON in place mutiert. SQLAlchemy erkennt das
        nicht als Änderung, sodass ab dem zweiten Bild nichts mehr ankam.
        """
        run_id = uuid4()
        puffer = _buffer(db, run_id)

        async def ablauf():
            await puffer.handle_line(PREFIX_CELL_START + "0")
            await puffer.handle_line(PREFIX_CELL_OUTPUT + "0\timage\timage/png\tERSTES")
            await puffer.handle_line(PREFIX_CELL_OUTPUT + "0\timage\timage/png\tZWEITES")

        asyncio.run(ablauf())
        bilder = _zelle(db, run_id).outputs["images"]
        assert [b["data"] for b in bilder] == ["ERSTES", "ZWEITES"]


class TestAbbruchpfad:
    def test_drain_sync_schreibt_den_rest(self, db):
        """
        Wird der Log-Task abgebrochen, ist kein verlässliches await mehr möglich.
        Die zuletzt gepufferten Zeilen dürfen trotzdem nicht verloren gehen.
        """
        run_id = uuid4()
        puffer = _buffer(db, run_id)

        async def ablauf():
            puffer.start()
            await puffer.handle_line(PREFIX_CELL_OUTPUT + "0\tstdout\tplain\tkurz vor Abbruch")
            puffer.drain_sync()

        asyncio.run(ablauf())
        assert _zelle(db, run_id).stdout == "kurz vor Abbruch\n"

    def test_drain_sync_ohne_inhalt_macht_nichts(self, db):
        run_id = uuid4()
        puffer = _buffer(db, run_id)
        puffer.drain_sync()
        assert db.statements == []

    def test_hintergrund_flush_macht_ausgabe_ohne_folgezeile_sichtbar(self, db):
        """
        Eine Zelle, die etwas ausgibt und danach lange rechnet, darf nicht
        unsichtbar bleiben, bis zufällig die nächste Zeile kommt.
        """
        run_id = uuid4()
        puffer = _buffer(db, run_id, flush_interval=0.05)

        async def ablauf():
            puffer.start()
            await puffer.handle_line(PREFIX_CELL_OUTPUT + "0\tstdout\tplain\teinsam")
            await asyncio.sleep(0.2)  # nichts weiter passiert
            puffer.drain_sync()

        asyncio.run(ablauf())
        assert _zelle(db, run_id).stdout == "einsam\n"


class _ZaehlendeDatei:
    """aiofiles-Ersatz, der Schreib- und Flush-Aufrufe mitzählt."""

    def __init__(self, pfad):
        self._datei = open(pfad, "a", encoding="utf-8")
        self.schreibvorgaenge = 0
        self.flushes = 0

    async def write(self, text):
        self._datei.write(text)
        self.schreibvorgaenge += 1

    async def flush(self):
        self._datei.flush()
        self.flushes += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self._datei.close()
        return False


def test_logdatei_wird_nicht_pro_zeile_geflusht(tmp_path, monkeypatch):
    """
    Punkt 6: Über aiofiles ist jedes flush() ein Thread-Hop plus Syscall. Bei einer
    geschwätzigen Pipeline waren das zehntausende pro Sekunde. Der Live-Pfad der UI
    ist ohnehin die SSE-Queue, nicht die Datei.
    """
    import aiofiles

    from app.executor import core as executor_core

    ZEILEN = 500
    dateien = []

    def gefaelschtes_open(pfad, *_args, **_kwargs):
        datei = _ZaehlendeDatei(pfad)
        dateien.append(datei)
        return datei

    monkeypatch.setattr(aiofiles, "open", gefaelschtes_open)

    container = MagicMock()
    container.id = "abc123"
    container.logs.return_value = iter(
        [f"Zeile {i}\n".encode() for i in range(ZEILEN)]
    )

    log_datei = tmp_path / "run.log"
    log_datei.touch()

    asyncio.run(
        executor_core._stream_logs(
            container, log_datei, asyncio.Queue(maxsize=ZEILEN * 2), uuid4()
        )
    )

    assert len(dateien) == 1
    datei = dateien[0]
    assert datei.schreibvorgaenge == ZEILEN, "Es wurden nicht alle Zeilen geschrieben"
    assert datei.flushes <= 10, (
        f"{datei.flushes} Flushes für {ZEILEN} Zeilen – die Drosselung greift nicht"
    )
    assert datei.flushes >= 1, "Am Ende muss einmal geflusht werden"
    assert log_datei.read_text().count("\n") == ZEILEN
