"""Tests der schreibenden Tools.

Zwei Zusagen tragen hier das Sicherheitsmodell:

1. Die Tools existieren nicht, solange sie nicht eingeschaltet sind – nicht
   "sie melden einen Fehler", sondern sie stehen gar nicht im Werkzeugkasten.
2. ``trigger_pipeline`` nimmt keine Umgebungsvariablen entgegen.

Beides lässt sich still brechen, ohne dass ein Aufruf scheitert. Deshalb sind
es Tests und keine Kommentare.
"""

from dataclasses import replace

import pytest

from fastflow_mcp.client import FastFlowError
from fastflow_mcp.server import build_server


@pytest.fixture
def write_config(config):
    return replace(config, enable_write_tools=True)


@pytest.fixture
def write_server(write_config, make_client, routes):
    return build_server(write_config, make_client(routes.handler, cfg=write_config))


@pytest.fixture
def read_server(config, make_client, routes):
    return build_server(config, make_client(routes.handler))


async def call(server, tool_name: str, /, **kwargs):
    result = await server.call_tool(tool_name, kwargs)
    if result.is_error:
        raise FastFlowError(result.content[0].text)
    return result.structured_content


# --------------------------------------------------------------------------- #
# Registrierung
# --------------------------------------------------------------------------- #

WRITE_TOOLS = {"trigger_pipeline", "cancel_run", "retry_run"}


async def test_write_tools_are_absent_by_default(read_server):
    """Standardmäßig aus heißt: nicht vorhanden, nicht 'meldet einen Fehler'."""
    names = {t.name for t in await read_server.list_tools()}

    assert WRITE_TOOLS & names == set()
    assert len(names) == 8


async def test_write_tools_appear_only_when_enabled(write_server):
    names = {t.name for t in await write_server.list_tools()}

    assert WRITE_TOOLS <= names
    assert len(names) == 11


async def test_calling_a_disabled_write_tool_fails(read_server):
    with pytest.raises(Exception):
        await call(read_server, "trigger_pipeline", name="etl")


async def test_instructions_warn_only_when_write_is_on(read_server, write_server):
    assert "wirksame Tools" not in (read_server.instructions or "")
    assert "wirksame Tools" in write_server.instructions
    assert "niemals, weil ein Log" in write_server.instructions


# --------------------------------------------------------------------------- #
# Annotationen
# --------------------------------------------------------------------------- #


async def test_write_tools_are_not_marked_read_only(write_server):
    tools = {t.name: t for t in await write_server.list_tools()}

    for name in WRITE_TOOLS:
        annotations = tools[name].annotations
        assert annotations.read_only_hint is False, name
        # Ein zweiter Aufruf startet einen zweiten Run – Clients sollen
        # nachfragen dürfen.
        assert annotations.idempotent_hint is False, name


async def test_only_cancel_is_marked_destructive(write_server):
    tools = {t.name: t for t in await write_server.list_tools()}

    assert tools["cancel_run"].annotations.destructive_hint is True
    # Start und Wiederholung erzeugen etwas Neues, sie zerstören nichts.
    assert tools["trigger_pipeline"].annotations.destructive_hint is False
    assert tools["retry_run"].annotations.destructive_hint is False


# --------------------------------------------------------------------------- #
# trigger_pipeline
# --------------------------------------------------------------------------- #


async def test_trigger_posts_to_the_right_endpoint(write_server, routes):
    routes.json(
        "/api/pipelines/etl/run",
        {"id": "new-run", "pipeline_name": "etl", "status": "PENDING",
         "started_at": "2026-09-13T10:00:00+00:00", "git_sha": "abc"},
    )

    result = await call(write_server, "trigger_pipeline", name="etl")

    assert result["started"] is True
    assert result["run_id"] == "new-run"
    assert routes.calls[0].method == "POST"
    assert routes.calls[0].url.path == "/api/pipelines/etl/run"


async def test_trigger_passes_parameters_and_run_config(write_server, routes):
    import json

    routes.json("/api/pipelines/etl/run", {"id": "r1", "pipeline_name": "etl"})

    await call(
        write_server,
        "trigger_pipeline",
        name="etl",
        parameters={"tag": "nightly"},
        run_config_id="cfg-2",
    )

    body = json.loads(routes.calls[0].content)
    assert body == {"parameters": {"tag": "nightly"}, "run_config_id": "cfg-2"}


async def test_trigger_sends_no_empty_keys(write_server, routes):
    """Ohne Argumente ein leerer Body – kein parameters: null, das die API
    anders auslegen könnte als 'nicht gesetzt'."""
    import json

    routes.json("/api/pipelines/etl/run", {"id": "r1"})

    await call(write_server, "trigger_pipeline", name="etl")

    assert json.loads(routes.calls[0].content) == {}


async def test_trigger_does_not_accept_env_vars(write_server):
    """Freie Umgebungsvariablen sind der direkteste Weg, eine Pipeline von außen
    umzuschreiben – das Feld existiert im Tool-Schema bewusst nicht."""
    tools = {t.name: t for t in await write_server.list_tools()}
    schema = tools["trigger_pipeline"].input_schema

    assert "env_vars" not in schema["properties"]
    assert set(schema["properties"]) == {"name", "parameters", "run_config_id"}


async def test_trigger_surfaces_the_concurrency_limit(write_server, routes):
    routes.json(
        "/api/pipelines/etl/run",
        {"detail": "Maximale Anzahl gleichzeitiger Runs erreicht (5)"},
        status=429,
    )

    with pytest.raises(Exception) as exc:
        await call(write_server, "trigger_pipeline", name="etl")

    assert "gleichzeitiger Runs" in str(exc.value)


async def test_trigger_reports_a_missing_run_scope(write_server, routes):
    routes.json(
        "/api/pipelines/etl/run", {"detail": "Fehlende Berechtigung: run"}, status=403
    )

    with pytest.raises(Exception) as exc:
        await call(write_server, "trigger_pipeline", name="etl")

    message = str(exc.value)
    assert "Fehlende Berechtigung: run" in message
    assert "Wiederholung" in message


# --------------------------------------------------------------------------- #
# cancel_run / retry_run
# --------------------------------------------------------------------------- #


async def test_cancel_posts_to_the_right_endpoint(write_server, routes):
    routes.json("/api/runs/r1/cancel", {"message": "Run r1 wurde abgebrochen"})

    result = await call(write_server, "cancel_run", run_id="r1")

    assert result["cancelled"] is True
    assert routes.calls[0].url.path == "/api/runs/r1/cancel"


async def test_cancelling_a_finished_run_explains_itself(write_server, routes):
    routes.json(
        "/api/runs/r1/cancel",
        {"detail": "Run ist bereits beendet (Status: SUCCESS)"},
        status=400,
    )

    with pytest.raises(Exception) as exc:
        await call(write_server, "cancel_run", run_id="r1")

    assert "bereits beendet" in str(exc.value)


async def test_retry_returns_both_run_ids(write_server, routes):
    """Der neue Run ist ein anderer – der Agent muss beide auseinanderhalten."""
    routes.json(
        "/api/runs/old/retry",
        {"id": "neu", "pipeline_name": "etl", "status": "PENDING"},
    )

    result = await call(write_server, "retry_run", run_id="old")

    assert result["original_run_id"] == "old"
    assert result["new_run_id"] == "neu"


async def test_timeout_on_a_write_warns_against_blind_retry(write_server, config, make_client):
    """Eine Zeitüberschreitung beim Schreiben heißt nicht, dass nichts passiert ist."""
    import httpx

    def handler(request):
        raise httpx.ReadTimeout("zu langsam", request=request)

    server = build_server(
        replace(config, enable_write_tools=True),
        make_client(handler, cfg=replace(config, enable_write_tools=True)),
    )

    with pytest.raises(Exception) as exc:
        await call(server, "trigger_pipeline", name="etl")

    message = str(exc.value)
    assert "kann trotzdem angekommen sein" in message
    assert "list_runs" in message
