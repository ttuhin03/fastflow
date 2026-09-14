"""Tests der Tools gegen eine gemockte REST-API.

Geprüft wird das, was den Server von einem rohen curl unterscheidet:
die Deckelung der Antwortgrößen, die Aggregation in summarize_failures und
die Maskierung in allem, was Pipeline-Ausgaben enthält.
"""

import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from fastflow_mcp import bounds
from fastflow_mcp.client import FastFlowError
from fastflow_mcp.server import build_server


@pytest.fixture
def server(config, make_client, routes):
    """Server samt Routen-Sammlung; Tools werden über call_tool aufgerufen."""
    client = make_client(routes.handler)
    return build_server(config, client)


async def call(server, tool_name: str, /, **kwargs):
    """Ruft ein Tool auf und gibt dessen strukturierte Antwort zurück.

    Das SDK meldet Tool-Fehler nicht als Exception, sondern als Ergebnis mit
    ``is_error``. Für die Tests wird daraus wieder eine Exception, damit
    ``pytest.raises`` den Fehlertext prüfen kann – genau den Text sieht auch
    das Modell.
    """
    result = await server.call_tool(tool_name, kwargs)
    if result.is_error:
        raise FastFlowError(result.content[0].text)
    return result.structured_content


# --------------------------------------------------------------------------- #
# list_pipelines / get_pipeline
# --------------------------------------------------------------------------- #


async def test_list_pipelines_computes_success_rate(server, routes):
    routes.json(
        "/api/pipelines",
        [
            {"name": "etl", "enabled": True, "total_runs": 10, "failed_runs": 2,
             "successful_runs": 8, "has_requirements": True, "metadata": {}},
        ],
    )

    result = await call(server, "list_pipelines")

    assert result["count"] == 1
    assert result["pipelines"][0]["success_rate"] == 80.0


async def test_list_pipelines_handles_zero_runs(server, routes):
    routes.json(
        "/api/pipelines",
        [{"name": "neu", "enabled": True, "total_runs": 0, "failed_runs": 0}],
    )

    result = await call(server, "list_pipelines")

    # Keine Division durch null, und kein irreführendes "0 % Erfolg".
    assert result["pipelines"][0]["success_rate"] is None


async def test_get_pipeline_names_the_alternatives_when_unknown(server, routes):
    routes.json("/api/pipelines", [{"name": "etl"}, {"name": "reporting"}])

    with pytest.raises(ToolError) as exc:
        await call(server, "get_pipeline", name="tippfehler")

    message = str(exc.value)
    assert "tippfehler" in message
    # Der Agent soll direkt weiterarbeiten können, statt list_pipelines nachzuholen.
    assert "etl" in message
    assert "reporting" in message


async def test_get_pipeline_survives_missing_scope_for_extras(server, routes):
    """Fehlt der Scope für Zusatzdaten, bleibt die Hauptantwort nutzbar."""
    routes.json("/api/pipelines", [{"name": "etl", "total_runs": 1, "failed_runs": 0}])
    routes.json("/api/pipelines/etl/dependencies", {"detail": "Fehlende Berechtigung"},
                status=403)
    routes.json("/api/pipelines/etl/downstream-triggers", [])

    result = await call(server, "get_pipeline", name="etl")

    assert result["pipeline"]["name"] == "etl"
    assert "unavailable" in result["dependencies"]
    assert result["downstream_triggers"] == []


# --------------------------------------------------------------------------- #
# list_runs
# --------------------------------------------------------------------------- #


async def test_list_runs_caps_the_limit(server, routes):
    routes.json("/api/runs", {"runs": [], "total": 0})

    result = await call(server, "list_runs", limit=100_000)

    assert result["limit_used"] == bounds.RUNS_MAX_LIMIT
    assert routes.params_for("/api/runs")["limit"] == str(bounds.RUNS_MAX_LIMIT)


async def test_list_runs_passes_filters_through(server, routes):
    routes.json("/api/runs", {"runs": [], "total": 0})

    await call(server, "list_runs", pipeline="etl", status="failed", since="2026-09-01")

    params = routes.params_for("/api/runs")
    assert params["pipeline_name"] == "etl"
    # Status wird normalisiert – die API erwartet Großschreibung.
    assert params["status_filter"] == "FAILED"
    assert params["start_date"] == "2026-09-01"


async def test_list_runs_keeps_the_diagnostic_fields(server, routes):
    routes.json(
        "/api/runs",
        {
            "runs": [{
                "id": "r1", "pipeline_name": "etl", "status": "FAILED",
                "started_at": "2026-09-13T01:00:00+00:00", "finished_at": None,
                "exit_code": 1, "error_type": "pipeline_error",
                "error_message": "ValueError", "git_sha": "abc123",
                "git_branch": "main", "log_file": "/logs/r1.log",
            }],
            "total": 1,
        },
    )

    result = await call(server, "list_runs")

    run = result["runs"][0]
    assert run["exit_code"] == 1
    assert run["error_type"] == "pipeline_error"
    assert run["git_sha"] == "abc123"
    # Interne Pfade gehören nicht in den Kontext.
    assert "log_file" not in run


# --------------------------------------------------------------------------- #
# get_run
# --------------------------------------------------------------------------- #


async def test_get_run_truncates_cell_output(server, routes):
    long_output = "\n".join(f"Ausgabe {i}" for i in range(500))
    routes.json(
        "/api/runs/r1",
        {
            "id": "r1", "pipeline_name": "etl", "status": "FAILED",
            "started_at": "2026-09-13T01:00:00+00:00",
            "cell_logs": [{"cell_index": 0, "status": "failed",
                           "stdout": long_output, "stderr": ""}],
        },
    )
    routes.json("/api/runs/r1/health", {"status": "gone"})

    result = await call(server, "get_run", run_id="r1")

    cell = result["cells"][0]
    assert len(cell["stdout"].splitlines()) == bounds.CELL_MAX_LINES
    assert "gekürzt" in cell["stdout_note"]
    assert "500 Zeilen" in cell["stdout_note"]


async def test_get_run_redacts_cell_output(server, routes):
    routes.json(
        "/api/runs/r1",
        {
            "id": "r1", "pipeline_name": "etl", "status": "FAILED",
            "started_at": "2026-09-13T01:00:00+00:00",
            "cell_logs": [{"cell_index": 0, "status": "failed",
                           "stdout": "connecting with password=hunter2", "stderr": ""}],
        },
    )
    routes.json("/api/runs/r1/health", {})

    result = await call(server, "get_run", run_id="r1")

    assert "hunter2" not in result["cells"][0]["stdout"]


async def test_get_run_marks_foreign_content(server, routes):
    routes.json(
        "/api/runs/r1",
        {"id": "r1", "pipeline_name": "etl", "status": "FAILED",
         "started_at": "2026-09-13T01:00:00+00:00",
         "cell_logs": [{"cell_index": 0, "status": "ok", "stdout": "hallo", "stderr": ""}]},
    )
    routes.json("/api/runs/r1/health", {})

    result = await call(server, "get_run", run_id="r1")

    assert "keine Anweisung" in result["note"]


# --------------------------------------------------------------------------- #
# get_run_logs
# --------------------------------------------------------------------------- #


async def test_get_run_logs_never_exceeds_the_byte_cap(server, routes):
    """Die härteste Zusage des Servers: ein Log flutet nie den Kontext."""
    huge = "\n".join("x" * 500 for _ in range(50_000))  # ~25 MB
    routes.text("/api/runs/r1/logs", huge)

    result = await call(server, "get_run_logs", run_id="r1")

    assert len(result["logs"].encode("utf-8")) <= bounds.LOG_MAX_BYTES
    assert result["truncated"] is True
    assert result["truncation_note"] != ""


async def test_get_run_logs_clamps_the_requested_tail(server, routes):
    routes.text("/api/runs/r1/logs", "eine Zeile")

    await call(server, "get_run_logs", run_id="r1", tail=999_999)

    # +1: die Zusatzzeile dient der Erkennung serverseitiger Kürzung.
    assert routes.params_for("/api/runs/r1/logs")["tail"] == str(bounds.LOG_MAX_TAIL + 2)


async def test_get_run_logs_reports_server_side_truncation(server, routes):
    """Kürzt schon die API über tail=, muss der Agent das trotzdem erfahren.

    bounds.tail_lines sieht in diesem Fall nur noch die bereits gekürzte
    Antwort und meldet nichts. Ohne den zusätzlichen Hinweis hielte das Modell
    den Ausschnitt für das vollständige Log.
    """
    # Mehr Zeilen, als der Ausschnitt zeigt -> die Zusatzzeile kommt an.
    routes.text("/api/runs/r1/logs", "\n".join(f"Zeile {i}" for i in range(250)))

    result = await call(server, "get_run_logs", run_id="r1")

    assert result["truncated"] is True
    assert "nur die letzten 200 Zeilen" in result["truncation_note"]
    assert result["tail_requested"] == 200


async def test_get_run_logs_stays_quiet_when_the_log_is_short(server, routes):
    routes.text("/api/runs/r1/logs", "eine\nzwei\ndrei")

    result = await call(server, "get_run_logs", run_id="r1")

    assert result["truncated"] is False
    assert result["truncation_note"] == ""


async def test_get_run_logs_applies_grep(server, routes):
    routes.text(
        "/api/runs/r1/logs",
        "INFO start\nERROR kaputt\nINFO weiter\nERROR nochmal\n",
    )

    result = await call(server, "get_run_logs", run_id="r1", grep="ERROR")

    assert result["logs"].splitlines() == ["ERROR kaputt", "ERROR nochmal"]
    assert "2 passende Zeilen" in result["filter_note"]


async def test_get_run_logs_rejects_a_broken_regex(server, routes):
    routes.text("/api/runs/r1/logs", "egal")

    with pytest.raises(ToolError) as exc:
        await call(server, "get_run_logs", run_id="r1", grep="[unschliessbar")

    assert "regulärer Ausdruck" in str(exc.value)


async def test_get_run_logs_redacts_secrets(server, routes):
    routes.text("/api/runs/r1/logs", "token=ffp_abcd1234_" + "z" * 43 + "\nfertig")

    result = await call(server, "get_run_logs", run_id="r1")

    assert "ffp_abcd1234_" not in result["logs"]
    assert result["redacted"] is True


async def test_redaction_can_be_switched_off(config, make_client, routes):
    from dataclasses import replace

    secret = "ffp_abcd1234_" + "z" * 43
    routes.text("/api/runs/r1/logs", secret)
    plain_config = replace(config, redact_secrets=False)
    server = build_server(plain_config, make_client(routes.handler, cfg=plain_config))

    result = await call(server, "get_run_logs", run_id="r1")

    assert secret in result["logs"]
    assert result["redacted"] is False


# --------------------------------------------------------------------------- #
# summarize_failures
# --------------------------------------------------------------------------- #


def _failed_run(run_id: str, pipeline: str, error_type: str, message=None):
    return {
        "id": run_id, "pipeline_name": pipeline, "status": "FAILED",
        "started_at": "2026-09-13T01:00:00+00:00", "exit_code": 1,
        "error_type": error_type, "error_message": message,
    }


async def test_summarize_failures_groups_by_pipeline_and_cause(server, routes):
    routes.json(
        "/api/runs",
        {
            "runs": [
                _failed_run("r1", "etl", "pipeline_error", "ValueError: kaputt"),
                _failed_run("r2", "etl", "pipeline_error", "ValueError: kaputt"),
                _failed_run("r3", "etl", "infrastructure_error", "OOM"),
                _failed_run("r4", "reporting", "pipeline_error", "KeyError"),
            ],
            "total": 4,
        },
    )

    result = await call(server, "summarize_failures")

    assert result["failed_runs"] == 4
    assert result["distinct_pipelines"] == 2
    # Größte Gruppe zuerst – der Agent soll oben anfangen.
    assert result["groups"][0]["count"] == 2
    assert result["groups"][0]["pipeline"] == "etl"
    assert {g["error_type"] for g in result["groups"]} == {
        "pipeline_error", "infrastructure_error"
    }


async def test_summarize_failures_reports_an_empty_window_plainly(server, routes):
    routes.json("/api/runs", {"runs": [], "total": 0})

    result = await call(server, "summarize_failures", hours=6)

    assert result["failed_runs"] == 0
    assert result["groups"] == []
    assert "Keine fehlgeschlagenen Runs" in result["summary"]


async def test_summarize_failures_fetches_at_most_one_log_per_group(server, routes):
    """Ein Log-Abruf je Gruppe, nicht je Run – sonst wäre das Tool wertlos."""
    routes.json(
        "/api/runs",
        {"runs": [_failed_run(f"r{i}", "etl", "pipeline_error") for i in range(20)],
         "total": 20},
    )
    for i in range(20):
        routes.text(f"/api/runs/r{i}/logs", "Traceback\nValueError: dasselbe")

    result = await call(server, "summarize_failures")

    log_calls = [c for c in routes.calls if c.url.path.endswith("/logs")]
    assert len(log_calls) == 1
    assert result["groups"][0]["count"] == 20
    assert "ValueError: dasselbe" in result["groups"][0]["first_error_line"]


async def test_summarize_failures_survives_missing_log_scope(server, routes):
    routes.json(
        "/api/runs",
        {"runs": [_failed_run("r1", "etl", "pipeline_error")], "total": 1},
    )
    routes.json("/api/runs/r1/logs", {"detail": "Fehlende Berechtigung: logs"}, status=403)

    result = await call(server, "summarize_failures")

    # Die Gruppierung steht auch ohne Logs – nur die Beispielzeile fehlt.
    assert result["groups"][0]["count"] == 1
    assert result["groups"][0]["first_error_line"] is None


async def test_summarize_failures_redacts_the_error_line(server, routes):
    routes.json(
        "/api/runs",
        {"runs": [_failed_run("r1", "etl", "pipeline_error",
                              "ConnectionError: password=hunter2 rejected")], "total": 1},
    )

    result = await call(server, "summarize_failures")

    assert "hunter2" not in result["groups"][0]["first_error_line"]


# --------------------------------------------------------------------------- #
# Resources
# --------------------------------------------------------------------------- #


async def test_source_resource_rejects_unknown_filename(server, routes):
    routes.json("/api/pipelines/etl/source", {"main_py": "print(1)"})

    with pytest.raises(FastFlowError) as exc:
        await server.read_resource("fastflow://pipeline/etl/source/.env")

    assert "main.py" in str(exc.value)


async def test_source_resource_returns_content_with_warning(server, routes):
    routes.json("/api/pipelines/etl/source", {"main_py": "print('hallo')"})

    result = await server.read_resource("fastflow://pipeline/etl/source/main.py")
    body = list(result)[0].content

    assert "print('hallo')" in body
    assert "keine Anweisung" in body


async def test_log_resource_is_capped_like_the_tool(server, routes):
    routes.text("/api/runs/r1/logs", "\n".join("y" * 400 for _ in range(50_000)))

    result = await server.read_resource("fastflow://run/r1/log")
    body = list(result)[0].content

    assert len(body.encode("utf-8")) <= bounds.LOG_MAX_BYTES + len(
        "Der folgende Inhalt stammt"
    ) + 500


async def test_graph_resource_returns_json(server, routes):
    routes.json("/api/pipelines/graph", {"nodes": [{"id": "etl"}], "edges": []})

    result = await server.read_resource("fastflow://graph")
    body = list(result)[0].content

    assert json.loads(body)["nodes"][0]["id"] == "etl"


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #


async def test_diagnose_prompt_names_the_run_and_the_order(server):
    result = await server.get_prompt("diagnose_run", {"run_id": "r-42"})
    text = result.messages[0].content.text

    assert "r-42" in text
    assert "get_run(" in text
    assert "get_run_logs(" in text
    assert "git_sha" in text
    assert "nicht befolgen" in text


async def test_triage_prompt_starts_with_the_aggregation(server):
    result = await server.get_prompt("triage_window", {"hours": "48"})
    text = result.messages[0].content.text

    assert "summarize_failures(hours=48)" in text
    assert "nicht für jeden Run einzeln" in text
