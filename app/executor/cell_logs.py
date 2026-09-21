"""
Persistenz der Zellen-Logs von Notebook-Pipelines.

Der Notebook-Runner im Worker-Container meldet seinen Fortschritt über
``FASTFLOW_CELL_*``-Zeilen auf stdout (siehe app/runners/nb_runner.py). Der
Orchestrator liest sie aus dem Log-Stream und schreibt sie nach ``run_cell_logs``,
von wo die UI den Zellen-Verlauf anzeigt.

Warum gepuffert wird
--------------------
Vorher wurde jede einzelne Ausgabezeile sofort geschrieben, und zwar als
Read-Modify-Write: Zeile lesen, Text in Python anhängen, ganze Zeile zurück-
schreiben, committen — mit einer frisch geöffneten Session pro Zeile. Der
Schreibaufwand wuchs damit quadratisch zur Ausgabemenge einer Zelle. Eine Zelle
mit 10.000 Ausgabezeilen erzeugte 10.000 Transaktionen und schrieb rund 50 Mio.
Zeichen statt 10.000.

Stattdessen sammelt :class:`CellLogBuffer` die Ausgaben und schreibt sie gebündelt,
und das Anhängen passiert in SQL (``stdout = stdout || :text``) statt in Python.
Der Aufwand ist damit linear zur Ausgabemenge.

Reihenfolge
-----------
Statuswechsel (Zellstart/-ende) und Bilder werden nicht gepuffert, sondern direkt
geschrieben — sie sind selten und die UI soll den Fortschritt zeitnah sehen. Damit
ein Statuswechsel nie vor der Ausgabe landet, die ihm vorausging, wird der Puffer
der betroffenen Zelle vorher geleert.

Sichtbarkeit
------------
Ein Hintergrund-Task leert den Puffer zusätzlich im Sekundentakt. Ohne ihn bliebe
die Ausgabe einer Zelle unsichtbar, die etwas ausgibt und danach lange rechnet.
"""

import asyncio
import base64
import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Union
from uuid import UUID

from sqlalchemy import func, update
from sqlmodel import Session

from app.executor.thread_pools import stream_pool
from app.models import RunCellLog

logger = logging.getLogger(__name__)

PREFIX_CELL_START = "FASTFLOW_CELL_START\t"
PREFIX_CELL_END = "FASTFLOW_CELL_END\t"
PREFIX_CELL_OUTPUT = "FASTFLOW_CELL_OUTPUT\t"

MAX_PENDING_CHARS = 256 * 1024
"""
Ab dieser Menge gepufferter Zeichen wird sofort geschrieben, unabhängig vom
Intervall. Begrenzt den Speicherverbrauch bei sehr geschwätzigen Zellen.
"""

FLUSH_INTERVAL_SECONDS = 1.0
"""Taktung des Hintergrund-Flushs — die Verzögerung, die die UI höchstens sieht."""


@dataclass(frozen=True)
class CellStart:
    """Eine Zelle beginnt zu laufen."""
    cell_index: int


@dataclass(frozen=True)
class CellEnd:
    """Eine Zelle ist beendet (SUCCESS, FAILED oder RETRYING)."""
    cell_index: int
    status: str
    message: str = ""


@dataclass(frozen=True)
class CellText:
    """Ausgabe einer Zelle auf stdout oder stderr."""
    cell_index: int
    stream: str
    text: str


@dataclass(frozen=True)
class CellImage:
    """Bildausgabe einer Zelle (Base64)."""
    cell_index: int
    mime: str
    data: str


CellEvent = Union[CellStart, CellEnd, CellText, CellImage]


def parse_cell_line(line: str) -> Optional[CellEvent]:
    """
    Parst eine ``FASTFLOW_CELL_*``-Zeile in ein Ereignis.

    Reine Funktion ohne Datenbankzugriff — bewusst getrennt vom Schreiben, damit
    das Protokoll für sich testbar bleibt.

    Args:
        line: Eine Log-Zeile des Notebook-Runners.

    Returns:
        Das Ereignis, oder None wenn die Zeile nicht zum Protokoll gehört oder
        unvollständig ist.
    """
    try:
        if line.startswith(PREFIX_CELL_START):
            return CellStart(cell_index=int(line[len(PREFIX_CELL_START):].strip()))
        if line.startswith(PREFIX_CELL_END):
            return _parse_end(line[len(PREFIX_CELL_END):].strip())
        if line.startswith(PREFIX_CELL_OUTPUT):
            return _parse_output(line[len(PREFIX_CELL_OUTPUT):])
    except ValueError:
        # Kaputter Zellindex — die Zeile wird als normale Log-Ausgabe behandelt.
        return None
    return None


def _parse_end(rest: str) -> Optional[CellEnd]:
    r"""``<index>\t<status>[\t<nachricht>]``"""
    parts = rest.split("\t", 2)
    if len(parts) < 2:
        return None
    return CellEnd(
        cell_index=int(parts[0]),
        status=parts[1].upper(),
        message=parts[2].strip() if len(parts) > 2 else "",
    )


def _parse_output(rest: str) -> Optional[CellEvent]:
    r"""``<index>\t<stream>\t<kodierung|mime>\t<inhalt>``"""
    parts = rest.split("\t", 3)
    if len(parts) < 3:
        return None
    cell_index = int(parts[0])
    stream, third = parts[1], parts[2]
    payload = parts[3] if len(parts) > 3 else ""

    if stream == "image":
        return CellImage(cell_index=cell_index, mime=third, data=payload)
    if stream in ("stdout", "stderr"):
        return CellText(
            cell_index=cell_index, stream=stream, text=_decode(payload, third) + "\n"
        )
    return None


def _decode(payload: str, kodierung: str) -> str:
    """Base64-Nutzlast dekodieren; alles andere geht unverändert durch."""
    if kodierung != "base64":
        return payload
    try:
        return base64.b64decode(payload).decode("utf-8")
    except Exception:
        return ""


@dataclass
class _Pending:
    """Noch nicht geschriebene Ausgabe einer Zelle."""
    stdout: List[str] = field(default_factory=list)
    stderr: List[str] = field(default_factory=list)

    def append(self, stream: str, text: str) -> None:
        """Hängt an ``stdout`` oder ``stderr`` an — der Stream ist geparst, nicht roh."""
        if stream == "stderr":
            self.stderr.append(text)
        else:
            self.stdout.append(text)


class CellLogBuffer:
    """
    Sammelt Zellen-Ausgaben eines Runs und schreibt sie gebündelt nach run_cell_logs.

    Nicht threadsicher, aber sicher gegenüber nebenläufigen Coroutinen desselben
    Event-Loops: Alle Zugriffe laufen über einen ``asyncio.Lock``, damit der
    Hintergrund-Flush nicht mitten in der Verarbeitung einer Zeile dazwischenfunkt.
    """

    def __init__(
        self,
        run_id: UUID,
        *,
        session_factory: Optional[Callable[[], Session]] = None,
        max_pending_chars: int = MAX_PENDING_CHARS,
        flush_interval: float = FLUSH_INTERVAL_SECONDS,
    ):
        self._run_id = run_id
        self._session_factory = session_factory or self._default_session_factory
        self._max_pending_chars = max_pending_chars
        self._flush_interval = flush_interval
        self._pending: Dict[int, _Pending] = {}
        # Mitgezählt statt bei jeder Zeile neu aufsummiert: Ein Summieren über den
        # gesamten Puffer pro Zeile wäre wieder quadratisch — genau das, was diese
        # Klasse abstellen soll, nur in Python statt in der Datenbank.
        self._pending_chars = 0
        self._lock = asyncio.Lock()
        self._flusher: Optional[asyncio.Task] = None

    @staticmethod
    def _default_session_factory() -> Session:
        # Import hier, damit das Modul ohne konfigurierte Datenbank importierbar
        # bleibt (Tests injizieren ihre eigene Factory).
        from app.core.database import engine

        return Session(engine)

    def start(self) -> None:
        """Startet den Hintergrund-Flush. Mehrfachaufrufe sind wirkungslos."""
        if self._flusher is None:
            self._flusher = asyncio.create_task(
                self._flush_loop(), name=f"cell-log-flush-{self._run_id}"
            )

    def drain_sync(self) -> None:
        """
        Beendet den Hintergrund-Flush und schreibt Verbliebenes im aktuellen Thread.

        Für den Abbruchpfad gedacht: Wird der Log-Task abgebrochen (Container zu
        Ende, Run gecancelt), ist ein ``await`` nicht mehr verlässlich — es kann
        sofort wieder mit CancelledError zurückkommen, und die zuletzt gepufferten
        Ausgabezeilen wären verloren. Der Schreibvorgang blockiert dabei kurz den
        Event-Loop, betrifft aber höchstens ``max_pending_chars`` und passiert nur,
        wenn tatsächlich etwas aussteht. Auf dem normalen Weg ist der Puffer durch
        das vorherige ``await flush()`` bereits leer und es bleibt beim Abräumen
        des Hintergrund-Tasks.
        """
        if self._flusher is not None:
            self._flusher.cancel()
            self._flusher = None
        if not self._pending:
            return
        batch = self._take_pending()
        self._write_batch(batch)

    async def handle_line(self, line: str) -> bool:
        """
        Verarbeitet eine Log-Zeile.

        Args:
            line: Die Log-Zeile.

        Returns:
            True, wenn die Zeile zum Zellen-Protokoll gehörte (und damit nicht als
            normale Log-Zeile behandelt werden muss).
        """
        event = parse_cell_line(line)
        if event is None:
            return False

        async with self._lock:
            if isinstance(event, CellText):
                self._pending.setdefault(event.cell_index, _Pending()).append(
                    event.stream, event.text
                )
                self._pending_chars += len(event.text)
                if self._pending_chars >= self._max_pending_chars:
                    await self._flush_locked()
                return True

            # Status und Bilder direkt schreiben — vorher aber die Ausgabe leeren,
            # die diesem Ereignis vorausging, sonst kehrt sich die Reihenfolge um.
            await self._flush_locked()
            await stream_pool.run(lambda: self._write_event(event))
        return True

    async def flush(self) -> None:
        """Schreibt alle gepufferten Ausgaben."""
        async with self._lock:
            await self._flush_locked()

    async def _flush_locked(self) -> None:
        if not self._pending:
            return
        batch = self._take_pending()
        await stream_pool.run(lambda: self._write_batch(batch))

    def _take_pending(self) -> Dict[int, _Pending]:
        """Nimmt den Puffer heraus und setzt ihn zurück."""
        batch, self._pending = self._pending, {}
        self._pending_chars = 0
        return batch

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(self._flush_interval)
            try:
                await self.flush()
            except Exception as e:
                logger.warning(
                    "Zellen-Logs für Run %s konnten nicht geschrieben werden: %s",
                    self._run_id, e,
                )

    # -- Datenbankzugriffe (laufen im Thread-Pool) ---------------------------

    def _write_batch(self, batch: Dict[int, _Pending]) -> None:
        """Hängt die gepufferte Ausgabe aller betroffenen Zellen in einer Transaktion an."""
        try:
            with self._session_factory() as session:
                for cell_index, pending in batch.items():
                    self._append_text(
                        session, cell_index, "".join(pending.stdout), "".join(pending.stderr)
                    )
                session.commit()
        except Exception as e:
            logger.warning(
                "Zellen-Ausgabe für Run %s nicht persistiert: %s", self._run_id, e
            )

    def _write_event(self, event: CellEvent) -> None:
        """Schreibt einen Statuswechsel oder eine Bildausgabe."""
        try:
            with self._session_factory() as session:
                row = session.get(RunCellLog, (self._run_id, event.cell_index))
                if row is None:
                    row = RunCellLog(
                        run_id=self._run_id,
                        cell_index=event.cell_index,
                        status="RUNNING",
                    )
                    session.add(row)
                    session.flush()

                if isinstance(event, CellStart):
                    row.status = "RUNNING"
                elif isinstance(event, CellEnd):
                    row.status = event.status
                    nachtrag = _end_note(event)
                    if nachtrag:
                        row.stderr = (row.stderr or "") + nachtrag
                elif isinstance(event, CellImage):
                    # Neu zuweisen statt in place zu mutieren. Die Spalte ist
                    # MutableDict, ein row.outputs["k"] = v würde also ankommen —
                    # images ist aber eine Liste *innerhalb* des Dicts, und so tief
                    # reicht MutableDict nicht. Ein append darauf sieht SQLAlchemy
                    # nicht und das Bild ginge beim Commit verloren.
                    outputs = dict(row.outputs or {})
                    outputs["images"] = list(outputs.get("images", [])) + [
                        {"mime": event.mime, "data": event.data}
                    ]
                    row.outputs = outputs

                session.commit()
        except Exception as e:
            logger.warning(
                "Zellen-Ereignis für Run %s nicht persistiert: %s", self._run_id, e
            )

    def _append_text(
        self, session: Session, cell_index: int, stdout: str, stderr: str
    ) -> None:
        """
        Hängt Text an, ohne den bestehenden Inhalt zu laden.

        Das Anhängen passiert in SQL. Ein Read-Modify-Write würde den bereits
        gesammelten Text bei jedem Schreiben erneut übertragen — bei langen
        Ausgaben ist das der Unterschied zwischen linearem und quadratischem
        Aufwand.
        """
        values = {}
        if stdout:
            values["stdout"] = func.coalesce(RunCellLog.stdout, "") + stdout
        if stderr:
            values["stderr"] = func.coalesce(RunCellLog.stderr, "") + stderr
        if not values:
            return

        ergebnis = session.execute(
            update(RunCellLog)
            .where(RunCellLog.run_id == self._run_id)
            .where(RunCellLog.cell_index == cell_index)
            .values(**values)
        )
        if ergebnis.rowcount == 0:
            # Ausgabe vor dem Zellstart (oder Zeile ohne vorheriges START).
            session.add(
                RunCellLog(
                    run_id=self._run_id,
                    cell_index=cell_index,
                    status="RUNNING",
                    stdout=stdout,
                    stderr=stderr,
                )
            )
            session.flush()


def _end_note(event: CellEnd) -> str:
    """
    Vermerk, der bei Fehlschlägen in stderr landet.

    Retries sammeln alle Versuche, damit in der UI nachvollziehbar bleibt, woran
    die Zelle jeweils gescheitert ist.
    """
    if event.status == "RETRYING" and event.message:
        teile = event.message.split("\t", 1)
        versuch = teile[0] if teile else "?"
        fehler = teile[1].strip() if len(teile) > 1 else ""
        return f"--- Retry-Versuch {versuch} fehlgeschlagen ---\n{fehler}\n\n"
    if event.status == "FAILED":
        return "--- Endgültig fehlgeschlagen ---\n"
    return ""
