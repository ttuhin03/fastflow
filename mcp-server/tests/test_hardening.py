"""Regressionstests für Befunde aus dem Code-Review.

Jeder Test hier hält eine Zusage fest, die sich still brechen lässt, ohne dass
ein Aufruf scheitert — genau die Sorte Fehler, die der Review gefunden hat.
"""

import asyncio
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from fastflow_mcp import bounds, redaction
from fastflow_mcp.client import FastFlowError, path_segment
from fastflow_mcp.server import build_server

SRC = Path(__file__).resolve().parent.parent / "src" / "fastflow_mcp"


async def call(server, tool_name: str, /, **kwargs):
    """Ruft ein Tool auf und macht aus jedem Fehler eine FastFlowError.

    Das SDK meldet einen erwarteten Fehler je nach Pfad entweder als Ergebnis
    mit ``is_error`` oder als ``ToolError`` mit vorangestelltem Präfix — beide
    tragen den Text, den auch das Modell sieht.
    """
    from mcp.server.mcpserver.exceptions import ToolError

    try:
        result = await server.call_tool(tool_name, kwargs)
    except ToolError as exc:
        raise FastFlowError(str(exc)) from None
    if result.is_error:
        raise FastFlowError(result.content[0].text)
    return result.structured_content


# --------------------------------------------------------------------------- #
# Syntax-Kompatibilität
# --------------------------------------------------------------------------- #


def test_every_module_compiles_on_the_lowest_supported_python():
    """pyproject.toml erlaubt 3.11 — dann muss das Paket dort auch importierbar sein.

    Ein mehrzeiliges Ersetzungsfeld in einem f-string ist erst ab 3.12 (PEP 701)
    gültig. pip installiert auf 3.11 trotzdem, und der Fehler schlägt erst beim
    ersten Import zu — also bei jedem Start.
    """
    import tomllib

    pyproject = tomllib.loads((SRC.parent.parent / "pyproject.toml").read_text())
    assert pyproject["project"]["requires-python"] == ">=3.11"

    for module in sorted(SRC.glob("*.py")):
        result = subprocess.run(
            [sys.executable, "-c",
             f"import ast,sys; ast.parse(open({str(module)!r}).read(), feature_version=(3,11))"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"{module.name} ist auf 3.11 ungültig:\n{result.stderr}"


# --------------------------------------------------------------------------- #
# ReDoS
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "name,payload",
    [
        # Punktketten: Hostnamen, Modulpfade, Versionsnummern.
        ("url-credentials", "a." * (32 * 1024)),
        # -eyJ-Folgen treffen die JWT-Regel an jeder Position.
        ("jwt", "-eyJ" * (16 * 1024)),
        # Abgebrochener Schlüsselblock – ein realer Fehlerfall bei Deploy-Keys.
        ("private-key", "-----BEGIN PRIVATE KEY-----\n" * 2_400),
    ],
)
def test_redaction_stays_fast_on_adversarial_input(name, payload):
    """Die Regexes laufen über 64 KB Log, das eine Pipeline frei bestimmt.

    Vor der Härtung: 2,2 s (url-credentials), 1,14 s (jwt), 0,62 s
    (private-key) — jeweils bei quadratischem Wachstum, auf dem einzigen
    Thread des stdio-Servers.
    """
    assert len(payload) >= 60 * 1024

    start = time.perf_counter()
    redaction.redact(payload)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.5, f"{name}: {elapsed:.2f}s für {len(payload)//1024}KB"


def test_redaction_scales_linearly_not_quadratically():
    """Verdoppelte Eingabe darf nicht das Vierfache kosten."""
    small = "a." * (16 * 1024)
    large = "a." * (32 * 1024)

    t0 = time.perf_counter(); redaction.redact(small); small_time = time.perf_counter() - t0
    t0 = time.perf_counter(); redaction.redact(large); large_time = time.perf_counter() - t0

    # Großzügige Schranke: quadratisch wäre Faktor 4, linear Faktor 2.
    assert large_time < small_time * 3 + 0.05


# --------------------------------------------------------------------------- #
# Pfad-Kodierung
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "hostile",
    ["../../secrets", "x/../../../admin", "a?b=c", "a#b", "a b", "..%2f.."],
)
def test_path_segment_neutralises_traversal(hostile):
    """httpx löst .. gegen die base_url auf und frisst dabei das /api-Präfix."""
    encoded = path_segment(hostile)

    # Entscheidend ist, dass kein Zeichen übrig bleibt, mit dem sich das
    # Pfadsegment verlassen lässt – ".." allein ist harmlos, "/" nicht.
    assert "/" not in encoded
    assert "?" not in encoded and "#" not in encoded and " " not in encoded
    assert "%" not in hostile or "%25" in encoded, "% muss selbst kodiert werden"


async def test_tools_do_not_escape_the_api_prefix(config, make_client, routes):
    """Ein bösartiger run_id darf keinen anderen Endpoint erreichen."""
    routes.json("/api/runs/..%2F..%2Fadmin", {"id": "x"})
    server = build_server(config, make_client(routes.handler))

    try:
        await call(server, "get_run", run_id="../../admin")
    except FastFlowError:
        pass

    for request in routes.calls:
        assert request.url.path.startswith("/api/"), f"entkommen: {request.url.path}"


# --------------------------------------------------------------------------- #
# Zeilenzählung mit \r
# --------------------------------------------------------------------------- #


async def test_exotic_separators_do_not_fake_a_truncation(config, make_client, routes):
    """splitlines() trennt auch bei \\v, \\f, \\u2028 und \\x85 — split("\\n") nicht.

    Folge vor dem Fix: ein vollständiges Log galt als gekürzt, und die Kürzung
    warf ausgerechnet den Traceback weg.

    \\r allein ist entschärft, weil die API die Datei im Text-Modus liest und
    Universal-Newlines es schon dort zu \\n machen. Die übrigen Trenner kommen
    unverändert an — und sich auf den Lesemodus der Gegenseite zu verlassen ist
    genau die Kopplung, die bounds.py vermeiden soll.
    """
    exotic = chr(11).join(f"Fortschritt {i}%" for i in range(1500))
    log = (
        "\\n".join(f"INFO Zeile {i}" for i in range(50))
        + "\\n"
        + exotic
        + "\\nTraceback (most recent call last):\\nValueError: der eigentliche Fehler\\n"
    )
    routes.text("/api/runs/r1/logs", log)
    server = build_server(config, make_client(routes.handler))

    result = await call(server, "get_run_logs", run_id="r1")

    assert result["truncated"] is False, "vollständiges Log fälschlich als gekürzt gemeldet"
    assert "ValueError: der eigentliche Fehler" in result["logs"]


# --------------------------------------------------------------------------- #
# grep-Zeitbudget
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("hostile", ["(a+)+b", "(a*)*c", "(?:x+)+", "((a)+)+", "(E|W)+"])
async def test_catastrophic_grep_is_rejected_before_it_runs(
    config, make_client, routes, hostile
):
    """(a+)+b läuft exponentiell; ohne Prüfung hängt die ganze Sitzung.

    Abgelehnt statt abgebrochen: ein Thread-Timeout ließe das Muster
    weiterlaufen, CPU verbrauchen und am Ende sogar das Prozessende blockieren.
    """
    routes.text("/api/runs/r1/logs", "a" * 60 + "!\n")
    server = build_server(config, make_client(routes.handler))

    start = time.perf_counter()
    with pytest.raises(FastFlowError) as exc:
        await call(server, "get_run_logs", run_id="r1", grep=hostile)
    elapsed = time.perf_counter() - start

    assert elapsed < 1, f"lief {elapsed:.1f}s statt sofort abzulehnen"
    assert "einfacheren Ausdruck" in str(exc.value)


@pytest.mark.parametrize(
    "harmless",
    ["Error|Traceback", "ERROR", r"\(a\)+", "[(]+", "(abc)+", r"^\d{4}-\d{2}"],
)
async def test_ordinary_filters_are_not_rejected(config, make_client, routes, harmless):
    """Die Prüfung ist konservativ, darf aber nicht das Alltägliche blockieren."""
    routes.text("/api/runs/r1/logs", "Error hier\n2026-09-13 abc\n(a)+\n")
    server = build_server(config, make_client(routes.handler))

    result = await call(server, "get_run_logs", run_id="r1", grep=harmless)

    assert "Filter" in result["filter_note"]


# --------------------------------------------------------------------------- #
# Zurückgehaltene Zell-Ausgaben
# --------------------------------------------------------------------------- #


async def test_withheld_cell_output_is_not_reported_as_absent(config, make_client, routes):
    """Zurückgehalten und 'gibt es nicht' dürfen nicht gleich aussehen."""
    routes.json(
        "/api/runs/r1",
        {"id": "r1", "pipeline_name": "etl", "status": "FAILED",
         "started_at": "2026-09-13T01:00:00+00:00",
         "cell_logs": [], "cell_logs_withheld": True},
    )
    routes.json("/api/runs/r1/health", {})
    server = build_server(config, make_client(routes.handler))

    result = await call(server, "get_run", run_id="r1")

    assert result["cells"] == []
    assert result["cells_withheld"] is True
    assert "logs" in result["cells_note"]
    assert "NICHT" in result["cells_note"]


async def test_present_cell_output_carries_no_withheld_flag(config, make_client, routes):
    routes.json(
        "/api/runs/r1",
        {"id": "r1", "pipeline_name": "etl", "status": "FAILED",
         "started_at": "2026-09-13T01:00:00+00:00",
         "cell_logs": [{"cell_index": 0, "status": "ok", "stdout": "hi", "stderr": ""}],
         "cell_logs_withheld": False},
    )
    routes.json("/api/runs/r1/health", {})
    server = build_server(config, make_client(routes.handler))

    result = await call(server, "get_run", run_id="r1")

    assert result.get("cells_withheld") is None


# --------------------------------------------------------------------------- #
# Byte-Deckel für Zell-Ausgaben
# --------------------------------------------------------------------------- #


def test_head_lines_caps_a_single_huge_line():
    """Vierzig Zeilen sind keine vierzig begrenzten Dinge."""
    one_giant_line = "x" * (4 * 1024 * 1024)

    result = bounds.head_lines(one_giant_line, bounds.CELL_MAX_LINES)

    assert result.returned_bytes <= bounds.CELL_MAX_BYTES
    assert result.truncated is True
    assert result.as_note() != ""


async def test_get_run_does_not_leak_a_megabyte_cell(config, make_client, routes):
    routes.json(
        "/api/runs/r1",
        {"id": "r1", "pipeline_name": "etl", "status": "FAILED",
         "started_at": "2026-09-13T01:00:00+00:00",
         "cell_logs": [{"cell_index": 0, "status": "failed",
                        "stdout": "y" * (2 * 1024 * 1024), "stderr": ""}]},
    )
    routes.json("/api/runs/r1/health", {})
    server = build_server(config, make_client(routes.handler))

    result = await call(server, "get_run", run_id="r1")

    assert len(result["cells"][0]["stdout"].encode()) <= bounds.CELL_MAX_BYTES
    assert result["cells"][0]["stdout_note"] != ""
