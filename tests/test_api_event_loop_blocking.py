"""
Tests gegen das Blockieren des Event-Loops durch synchrone Datenbankzugriffe.

Vorher war jeder Endpoint ``async def``, führte darin aber synchrones SQLModel-I/O
aus. Weil der Orchestrator als einzelner uvicorn-Worker läuft, serialisierte damit
jede Query sämtliche gleichzeitigen Requests — inklusive der beiden Queries, die
``get_current_user`` bei *jedem* authentifizierten Request ausführt.

Der Umbau hat zwei Hälften, die nur zusammen tragen:

1. Endpoints ohne ``await`` sind ``def``. FastAPI führt sie dann in AnyIOs
   Threadpool aus, der Event-Loop bleibt frei.
2. Der Verbindungspool ist auf diese Parallelität dimensioniert. Ohne das wäre
   lediglich das Nadelöhr verschoben: Statt am Event-Loop warteten die Threads
   am Pool, dessen SQLite-Default bei 5 Verbindungen liegt.

Dazu kommt die Freigabe der Verbindung in den SSE-Streams: FastAPI schließt eine
``yield``-Dependency erst nach der Response, bei einem Stream also erst beim
Verbindungsabbruch des Clients. Ohne die Freigabe belegte jeder offene Log- oder
Metrics-Stream eine Poolverbindung über seine gesamte Laufzeit.
"""

import asyncio
import inspect
import pathlib
import re
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import anyio.to_thread
import pytest
from sqlalchemy import text
from sqlmodel import Session, create_engine

from app.api.logs import stream_run_logs
from app.api.metrics import stream_run_metrics
from app.auth.auth import get_current_user
from app.core import database as database_module
from app.core.config import config
from app.core.database import (
    BACKGROUND_CONNECTION_HEADROOM,
    _is_memory_sqlite,
    release_connection,
    resolved_pool_size,
)
from app.models import PipelineRun
from app.startup import _configure_api_threadpool

API_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "api"

# Zugriffe, die eine Session synchron benutzen und damit den Loop blockieren würden.
_SYNC_DB_CALLS = (
    "session.exec",
    "session.commit",
    "session.get",
    "session.add",
    "session.query",
    "session.delete",
)

# Konstrukte, die einen Endpoint zwingend ``async def`` machen.
_NEEDS_ASYNC = re.compile(
    r"\bawait\b|\basync with\b|\basync for\b"
    r"|asyncio\.(get_running_loop|create_task|get_event_loop|to_thread|sleep|gather)"
)


def _iter_endpoints():
    """
    Liest die Endpoint-Funktionen unter app/api aus dem Quelltext.

    Bewusst statisch statt über ``app.routes``: Die Dekoratoren von slowapi und
    FastAPI verpacken die Funktion, sodass zur Laufzeit nicht mehr zuverlässig
    erkennbar ist, wie sie ursprünglich definiert wurde.

    Yields:
        Tuple aus Dateiname, Zeilennummer, Funktionsname, "ist async", Rumpf.
    """
    for path in sorted(API_DIR.glob("*.py")):
        lines = path.read_text().split("\n")
        for index, line in enumerate(lines):
            match = re.match(r"(async )?def (\w+)\(", line)
            if not match:
                continue
            if "@router." not in "\n".join(lines[max(0, index - 8):index]):
                continue
            end = index + 1
            while end < len(lines) and not re.match(r"^(@router|def |async def )", lines[end]):
                end += 1
            yield (
                path.name,
                index + 1,
                match.group(2),
                bool(match.group(1)),
                "\n".join(lines[index + 1:end]),
            )


def test_endpoints_mit_synchronem_db_zugriff_sind_nicht_async():
    """
    Ein Endpoint, der synchron auf die Datenbank zugreift und kein ``await``
    braucht, muss ``def`` sein — sonst blockiert seine Query den Event-Loop und
    damit alle anderen Requests dieses Prozesses.

    Endpoints, die tatsächlich etwas erwarten (Datei-I/O über aiofiles,
    Executor-Aufrufe, SSE), bleiben zu Recht ``async def`` und sind hier nicht
    gemeint — die Regel greift nur, wenn nichts im Rumpf ein ``await`` verlangt.
    """
    verstoesse = [
        f"{datei}:{zeile} {name}"
        for datei, zeile, name, ist_async, rumpf in _iter_endpoints()
        if ist_async
        and any(call in rumpf for call in _SYNC_DB_CALLS)
        and not _NEEDS_ASYNC.search(rumpf)
    ]
    assert not verstoesse, (
        "Diese Endpoints blockieren mit synchronem DB-I/O den Event-Loop, "
        "obwohl sie kein await brauchen. Als 'def' definieren, dann führt "
        "FastAPI sie im Threadpool aus:\n  " + "\n  ".join(verstoesse)
    )


def test_es_gibt_ueberhaupt_endpoints_zu_pruefen():
    """
    Absicherung der Prüflogik selbst: Findet die Quelltext-Analyse keine
    Endpoints mehr (z. B. weil sich die Struktur unter app/api ändert), liefe der
    Test oben still grün und die Regressionssperre wäre wirkungslos.
    """
    endpoints = list(_iter_endpoints())
    assert len(endpoints) > 50, f"Nur {len(endpoints)} Endpoints gefunden"
    assert any(not ist_async for *_, ist_async, _ in endpoints), "Kein einziger sync-Endpoint"


def test_get_current_user_ist_synchron():
    """
    ``get_current_user`` hängt an praktisch jedem Request und macht zwei Queries
    (Session-Lookup und User-Lookup). Als Coroutine liefen beide auf dem
    Event-Loop und serialisierten alles andere gleich mit.
    """
    assert not inspect.iscoroutinefunction(get_current_user)


class TestPoolDimensionierung:
    """Der Verbindungspool muss zur Parallelität des Threadpools passen."""

    def test_hergeleitete_groesse_deckt_threadpool_plus_reserve(self, monkeypatch):
        monkeypatch.setattr(config, "DB_POOL_SIZE", 0)
        monkeypatch.setattr(config, "API_THREADPOOL_WORKERS", 40)
        assert resolved_pool_size() == 40 + BACKGROUND_CONNECTION_HEADROOM

    def test_expliziter_wert_hat_vorrang(self, monkeypatch):
        monkeypatch.setattr(config, "DB_POOL_SIZE", 12)
        monkeypatch.setattr(config, "API_THREADPOOL_WORKERS", 40)
        assert resolved_pool_size() == 12

    def test_pool_ist_nie_kleiner_als_der_threadpool(self, monkeypatch):
        """
        Die eigentliche Invariante: Jeder Endpoint-Thread kann eine Verbindung
        halten. Ist der Pool kleiner, warten Threads nur noch auf Verbindungen.
        """
        for workers in (1, 8, 40, 200):
            monkeypatch.setattr(config, "DB_POOL_SIZE", 0)
            monkeypatch.setattr(config, "API_THREADPOOL_WORKERS", workers)
            assert resolved_pool_size() >= workers

    def test_engine_nutzt_die_konfigurierte_groesse(self):
        """Die App-Engine wird tatsächlich mit den Pool-Argumenten gebaut."""
        pool = database_module.engine.pool
        assert pool.size() == database_module._POOL_KWARGS["pool_size"]

    @pytest.mark.parametrize(
        "url,erwartet",
        [
            ("sqlite:///:memory:", True),
            ("sqlite://", True),
            ("sqlite:///", True),
            # Dritte Schreibweise für In-Memory, die SQLAlchemy genauso behandelt.
            ("sqlite:///file:db1?mode=memory&cache=shared&uri=true", True),
            ("sqlite:////var/data/fastflow.db", False),
            ("postgresql://user:pw@host:5432/db", False),
        ],
    )
    def test_in_memory_sqlite_wird_erkannt(self, url, erwartet):
        """
        In-Memory-SQLite bekommt von SQLAlchemy einen Pool ohne Überlauf.
        Pool-Argumente wie max_overflow sind dort unzulässig und würden den
        Start mit einem TypeError abbrechen — die Erkennung verhindert das.
        """
        assert _is_memory_sqlite(url) is erwartet

    @pytest.mark.parametrize(
        "url",
        [
            "sqlite:///:memory:",
            "sqlite://",
            "sqlite:///file:db1?mode=memory&cache=shared&uri=true",
        ],
    )
    def test_erkannte_urls_vertragen_wirklich_keine_pool_argumente(self, url):
        """
        Die Gegenprobe zur Erkennung: Für jede als In-Memory erkannte URL muss
        create_engine mit den Pool-Argumenten tatsächlich scheitern. Sonst prüft
        der Test oben nur eine selbst erfundene Regel statt der von SQLAlchemy.
        """
        with pytest.raises(TypeError):
            create_engine(url, **database_module._POOL_KWARGS)


class TestVerbindungsfreigabe:
    """release_connection gibt die Verbindung zurück, ohne die Session zu zerstören."""

    def test_verbindung_geht_zurueck_in_den_pool(self, tmp_path):
        engine = create_engine(f"sqlite:///{tmp_path / 'release.db'}")
        try:
            with Session(engine) as session:
                session.exec(text("SELECT 1"))
                assert engine.pool.checkedout() == 1

                release_connection(session)
                assert engine.pool.checkedout() == 0

                # Die Session bleibt benutzbar und holt sich eine neue Verbindung.
                assert session.exec(text("SELECT 1")).one()[0] == 1
        finally:
            engine.dispose()


class _MitschreibendeSession:
    """Session-Attrappe, die festhält, wann die Verbindung freigegeben wurde."""

    def __init__(self, run: Optional[PipelineRun]):
        self._run = run
        self.geschlossen = False

    def get(self, _model, _pk):
        return self._run

    def close(self) -> None:
        self.geschlossen = True


def _fertiger_run(log_datei: pathlib.Path, metrics_datei: Optional[pathlib.Path] = None):
    return PipelineRun(
        id=uuid4(),
        pipeline_name="demo",
        log_file=str(log_datei),
        metrics_file=str(metrics_datei) if metrics_datei else None,
        started_at=datetime.now(timezone.utc),
    )


class TestStreamsHaltenKeineVerbindung:
    """
    Die SSE-Endpoints dürfen ihre Poolverbindung nicht über die Streamdauer halten.

    Ohne die Freigabe legen genügend gleichzeitig offene Streams die ganze App
    lahm: Sie belegen den Pool, und danach läuft jeder weitere Datenbankzugriff
    — auch der jedes anderen Requests — in den Pool-Timeout.
    """

    def test_log_stream_gibt_verbindung_vor_dem_streamen_frei(self, tmp_path, monkeypatch):
        log_datei = tmp_path / "run.log"
        log_datei.write_text("Zeile 1\nZeile 2\n", encoding="utf-8")
        monkeypatch.setattr(config, "LOGS_DIR", tmp_path)

        run = _fertiger_run(log_datei)
        session = _MitschreibendeSession(run)

        antwort = asyncio.run(
            stream_run_logs(run_id=run.id, session=session, current_user=None)
        )

        assert session.geschlossen, "Log-Stream hält die Verbindung über die Streamdauer"
        assert antwort.media_type == "text/event-stream"

    def test_metrics_stream_gibt_verbindung_vor_dem_streamen_frei(self, tmp_path, monkeypatch):
        metrics_datei = tmp_path / "run.metrics.jsonl"
        metrics_datei.write_text('{"cpu_percent": 1.0, "ram_mb": 2.0}\n', encoding="utf-8")
        monkeypatch.setattr(config, "LOGS_DIR", tmp_path)

        run = _fertiger_run(tmp_path / "run.log", metrics_datei)
        session = _MitschreibendeSession(run)

        antwort = asyncio.run(
            stream_run_metrics(run_id=run.id, session=session, current_user=None)
        )

        assert session.geschlossen, "Metrics-Stream hält die Verbindung über die Streamdauer"
        assert antwort.media_type == "text/event-stream"

    def test_freigabe_passiert_auch_wenn_der_run_fehlt(self, tmp_path, monkeypatch):
        """
        Fehlt der Run, endet der Request mit 404 — die Verbindung gibt in dem Fall
        FastAPI selbst frei. Geprüft wird hier nur, dass der Pfad nicht vorher an
        einer fehlenden Freigabe scheitert.
        """
        monkeypatch.setattr(config, "LOGS_DIR", tmp_path)
        session = _MitschreibendeSession(None)

        with pytest.raises(Exception) as fehler:
            asyncio.run(
                stream_run_logs(run_id=uuid4(), session=session, current_user=None)
            )
        assert getattr(fehler.value, "status_code", None) == 404


def test_configure_api_threadpool_setzt_den_limiter(monkeypatch):
    """
    Ohne diesen Startup-Schritt liefe die API auf AnyIOs Default. Der Wert wird
    hier explizit gesetzt, damit er zusammen mit der Pool-Größe konfigurierbar
    bleibt und beide nicht auseinanderlaufen.
    """
    monkeypatch.setattr(config, "API_THREADPOOL_WORKERS", 33)

    async def messen() -> float:
        _configure_api_threadpool()
        return anyio.to_thread.current_default_thread_limiter().total_tokens

    # Der Limiter hängt an einer RunVar, gilt also nur in diesem Loop.
    assert asyncio.run(messen()) == 33
