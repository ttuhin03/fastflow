"""Tests für die Fehlerübersetzung des HTTP-Clients.

Ein Agent reagiert auf den Text einer Fehlermeldung. "403 Forbidden" führt zu
Wiederholungen, "dem Token fehlt der Scope 'logs', eine Wiederholung hilft
nicht" führt dazu, dass er aufhört und den Nutzer informiert. Diese Texte sind
deshalb Verhalten, nicht Kosmetik.
"""

import httpx
import pytest

from fastflow_mcp.client import FastFlowError


async def test_successful_json_request(make_client, routes):
    routes.json("/api/pipelines", [{"name": "etl"}])
    client = make_client(routes.handler)

    result = await client.get_json("/pipelines", what="die Pipeline-Liste")

    assert result == [{"name": "etl"}]


async def test_none_params_are_dropped(make_client, routes):
    routes.json("/api/runs", {"runs": []})
    client = make_client(routes.handler)

    await client.get_json(
        "/runs", what="die Runs", params={"limit": 20, "pipeline_name": None}
    )

    params = routes.params_for("/api/runs")
    assert params == {"limit": "20"}


async def test_401_explains_how_to_get_a_new_token(make_client, routes):
    routes.json("/api/runs", {"detail": "Ungültiges Token"}, status=401)
    client = make_client(routes.handler)

    with pytest.raises(FastFlowError) as exc:
        await client.get_json("/runs", what="die Runs")

    message = str(exc.value)
    assert "401" in message
    assert "Einstellungen → API-Tokens" in message
    assert "FASTFLOW_TOKEN" in message


async def test_403_names_the_scopes_and_discourages_retry(make_client, routes):
    routes.json("/api/runs/x/logs", {"detail": "Fehlende Berechtigung: logs"}, status=403)
    client = make_client(routes.handler)

    with pytest.raises(FastFlowError) as exc:
        await client.get_text("/runs/x/logs", what="das Log")

    message = str(exc.value)
    assert "Fehlende Berechtigung: logs" in message
    assert "'logs'" in message
    # Entscheidend: der Agent soll es nicht erneut versuchen.
    assert "Wiederholung" in message


async def test_404_mentions_what_was_missing(make_client, routes):
    client = make_client(routes.handler)

    with pytest.raises(FastFlowError) as exc:
        await client.get_json("/runs/unbekannt", what="den Run unbekannt")

    assert "Nicht gefunden: den Run unbekannt" in str(exc.value)


async def test_429_asks_for_a_pause(make_client, routes):
    routes.json("/api/runs", {"detail": "zu viele"}, status=429)
    client = make_client(routes.handler)

    with pytest.raises(FastFlowError) as exc:
        await client.get_json("/runs", what="die Runs")

    assert "429" in str(exc.value)
    assert "warten" in str(exc.value)


async def test_429_passes_through_the_concurrency_reason(make_client, routes):
    """Beim Pipeline-Start bedeutet 429 die Nebenläufigkeitsgrenze, nicht das
    Rate-Limit. Der Grund aus der API gehört deshalb in die Meldung."""
    routes.json(
        "/api/pipelines/etl/run",
        {"detail": "Maximale Anzahl gleichzeitiger Runs erreicht (5)"},
        status=429,
    )
    client = make_client(routes.handler)

    with pytest.raises(FastFlowError) as exc:
        await client.post_json("/pipelines/etl/run", what="den Pipeline-Start")

    assert "gleichzeitiger Runs" in str(exc.value)


async def test_500_does_not_leak_the_response_body(make_client, routes):
    routes.json(
        "/api/runs",
        {"detail": "Traceback ... /srv/app/secrets.py line 12 ... DB_PASSWORD=hunter2"},
        status=500,
    )
    client = make_client(routes.handler)

    with pytest.raises(FastFlowError) as exc:
        await client.get_json("/runs", what="die Runs")

    message = str(exc.value)
    assert "Serverfehler (500)" in message
    # Interne Pfade und Werte aus einem 5xx gehören nicht in den Agent-Kontext.
    assert "hunter2" not in message
    assert "secrets.py" not in message


async def test_timeout_names_the_limit(make_client, config):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("zu langsam", request=request)

    client = make_client(handler)

    with pytest.raises(FastFlowError) as exc:
        await client.get_json("/runs", what="die Runs")

    assert "Zeitüberschreitung" in str(exc.value)
    assert "5s" in str(exc.value)


async def test_connection_error_is_reported_without_the_token(make_client, config):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Name oder Dienst nicht bekannt", request=request)

    client = make_client(handler)

    with pytest.raises(FastFlowError) as exc:
        await client.get_json("/runs", what="die Runs")

    message = str(exc.value)
    assert "fehlgeschlagen" in message
    assert config.token not in message


async def test_token_never_appears_in_any_error(make_client, routes, config):
    """Querschnittszusage: keine Fehlermeldung enthält je das Token."""
    for status in (401, 403, 404, 429, 500, 503):
        routes.json("/api/runs", {"detail": f"status {status}"}, status=status)
        client = make_client(routes.handler)
        with pytest.raises(FastFlowError) as exc:
            await client.get_json("/runs", what="die Runs")
        assert config.token not in str(exc.value)


async def test_get_text_returns_raw_body_not_json(make_client, routes):
    """Logs kommen als PlainTextResponse – der Body darf nicht geparst werden."""
    routes.text("/api/runs/abc/logs", "Zeile 1\nZeile 2\n{ kein json }")
    client = make_client(routes.handler)

    result = await client.get_text("/runs/abc/logs", what="das Log")

    assert result == "Zeile 1\nZeile 2\n{ kein json }"


async def test_auth_header_is_sent(make_client, routes, config):
    routes.json("/api/pipelines", [])
    client = make_client(routes.handler)

    await client.get_json("/pipelines", what="die Pipelines")

    assert routes.calls[0].headers["authorization"] == f"Bearer {config.token}"


def test_fastflow_error_is_passed_through_by_the_sdk():
    """FastFlowError muss von ToolError *und* ResourceError erben.

    Das SDK reicht nur diese beiden Typen im Klartext an den Client weiter;
    jede andere Exception gilt als Absturz und wird zu "Error executing tool
    <name>" maskiert. Ohne diesen Erbgang erreichen die Hinweise zu Token,
    Scopes und Rate-Limits das Modell nie – und der Agent wiederholt den
    aussichtslosen Aufruf, statt den Nutzer zu informieren.

    Dieser Test ist die Begründung dafür, dass die Basisklassen nicht wie
    unnötiger Ballast aussehen und beim Aufräumen entfernt werden.
    """
    from mcp.server.mcpserver.exceptions import ResourceError, ToolError

    assert issubclass(FastFlowError, ToolError)
    assert issubclass(FastFlowError, ResourceError)
