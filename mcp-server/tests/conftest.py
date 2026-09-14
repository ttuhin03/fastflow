"""Gemeinsame Fixtures: Konfiguration und Client gegen einen Mock-Transport."""

from __future__ import annotations

import httpx
import pytest

from fastflow_mcp.client import FastFlowClient
from fastflow_mcp.config import Config

BASE_URL = "https://fastflow.test"
API_URL = f"{BASE_URL}/api"

# Syntaktisch gültiges, aber offensichtlich erfundenes Token.
FAKE_TOKEN = "ffp_TESTonly_" + "T" * 43


@pytest.fixture
def config() -> Config:
    return Config(
        base_url=BASE_URL,
        token=FAKE_TOKEN,
        timeout_seconds=5.0,
        verify_tls=True,
        redact_secrets=True,
    )


@pytest.fixture
def make_client(config):
    """Baut einen Client, dessen Requests ein Handler beantwortet.

    Bewusst über httpx.MockTransport statt über echtes Netzwerk: die Tests
    sollen die Fehlerübersetzung und die Deckelung prüfen, nicht httpx.
    """

    def _make(handler, *, cfg: Config | None = None) -> FastFlowClient:
        effective = cfg or config
        transport = httpx.MockTransport(handler)
        http = httpx.AsyncClient(
            base_url=effective.api_url,
            transport=transport,
            headers={"Authorization": f"Bearer {effective.token}"},
        )
        return FastFlowClient(effective, client=http)

    return _make


@pytest.fixture
def routes():
    """Sammelt Pfad -> Antwort und liefert einen passenden Handler.

    Einfacher als respx für den hier nötigen Umfang und ohne zusätzliche
    Kopplung an dessen API.
    """

    class Routes:
        def __init__(self) -> None:
            self.responses: dict[str, httpx.Response] = {}
            self.calls: list[httpx.Request] = []

        def json(self, path: str, payload, status: int = 200) -> "Routes":
            self.responses[path] = httpx.Response(status, json=payload)
            return self

        def text(self, path: str, body: str, status: int = 200) -> "Routes":
            self.responses[path] = httpx.Response(
                status, text=body, headers={"content-type": "text/plain"}
            )
            return self

        def handler(self, request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            response = self.responses.get(request.url.path)
            if response is None:
                return httpx.Response(404, json={"detail": f"kein Mock für {request.url.path}"})
            return response

        def params_for(self, path: str) -> dict[str, str]:
            for call in self.calls:
                if call.url.path == path:
                    return dict(call.url.params)
            raise AssertionError(f"{path} wurde nicht aufgerufen")

    return Routes()
