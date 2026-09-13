"""HTTP-Client gegen die Fast-Flow-REST-API.

Der Client übersetzt HTTP-Fehler in Meldungen, mit denen ein Agent etwas
anfangen kann. Ein nacktes "403 Forbidden" führt dazu, dass ein Modell den
Aufruf mehrfach wiederholt; "dem Token fehlt der Scope 'logs'" führt dazu,
dass es aufhört und den Nutzer informiert.
"""

from __future__ import annotations

from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ResourceError, ToolError

from .config import Config


class FastFlowError(ToolError, ResourceError):
    """Fehler, dessen Text unverändert an den Agenten gehen darf.

    Erbt bewusst von ``ToolError`` **und** ``ResourceError``: das SDK reicht nur
    diese beiden Typen im Klartext an den Client weiter. Jede andere Exception
    gilt als Absturz und wird zu "Error executing tool <name>" maskiert – die
    sorgfältig formulierten Hinweise zu Token, Scopes und Rate-Limits kämen dann
    nie beim Modell an. Der Doppel-Erbgang deckt beide Aufrufwege ab, weil
    dieselben Client-Fehler sowohl aus Tools als auch aus Resources auftreten.

    Enthält nie das Token und nie den rohen Response-Body eines 5xx – nur die
    Ursache und, wo möglich, den nächsten sinnvollen Schritt.
    """


def _describe_http_error(response: httpx.Response, what: str) -> FastFlowError:
    """Bildet eine HTTP-Antwort auf eine handlungsleitende Meldung ab."""
    status = response.status_code
    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            raw = body.get("detail")
            detail = raw if isinstance(raw, str) else ""
    except Exception:
        detail = ""

    if status == 401:
        return FastFlowError(
            "Das API-Token wurde abgelehnt (401). Es ist ungültig, abgelaufen oder "
            "widerrufen. Ein neues Token gibt es in der Fast-Flow-UI unter "
            "Einstellungen → API-Tokens; danach FASTFLOW_TOKEN aktualisieren."
        )
    if status == 403:
        hint = detail or "Die Berechtigung reicht nicht aus."
        return FastFlowError(
            f"Zugriff verweigert (403) bei {what}. {hint} "
            "Prüfe die Scopes des Tokens – lesende Aufrufe brauchen 'read', "
            "Logs zusätzlich 'logs', Quelltext 'source'. Der Aufruf wird durch "
            "eine Wiederholung nicht erfolgreich."
        )
    if status == 404:
        return FastFlowError(f"Nicht gefunden: {what}." + (f" {detail}" if detail else ""))
    if status == 429:
        return FastFlowError(
            f"Rate-Limit erreicht (429) bei {what}. Bitte kurz warten und erst dann "
            "erneut versuchen."
        )
    if status >= 500:
        return FastFlowError(
            f"Die Fast-Flow-Instanz meldet einen Serverfehler ({status}) bei {what}."
        )
    return FastFlowError(f"Unerwartete Antwort {status} bei {what}." + (f" {detail}" if detail else ""))


class FastFlowClient:
    """Dünne Hülle um httpx mit Auth-Header und Fehlerübersetzung."""

    def __init__(self, config: Config, client: httpx.AsyncClient | None = None) -> None:
        self._config = config
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=config.api_url,
            timeout=config.timeout_seconds,
            verify=config.verify_tls,
            headers={
                "Authorization": f"Bearer {config.token}",
                "Accept": "application/json",
                "User-Agent": "fastflow-mcp",
            },
            follow_redirects=False,
        )

    @property
    def config(self) -> Config:
        return self._config

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_json(
        self,
        path: str,
        *,
        what: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """GET mit JSON-Antwort.

        Args:
            path: Pfad relativ zu ``/api``, z.B. ``/runs``.
            what: Klartext für Fehlermeldungen, z.B. "die Run-Liste".
            params: Query-Parameter; ``None``-Werte werden entfernt.
        """
        cleaned = {k: v for k, v in (params or {}).items() if v is not None}
        try:
            response = await self._client.get(path, params=cleaned)
        except httpx.TimeoutException as exc:
            raise FastFlowError(
                f"Zeitüberschreitung nach {self._config.timeout_seconds:.0f}s bei {what}. "
                "Die Instanz antwortet nicht oder die Abfrage ist zu groß."
            ) from exc
        except httpx.HTTPError as exc:
            # str(exc) enthält bei httpx die URL, aber keine Header – das Token
            # kann hier nicht durchschlagen.
            raise FastFlowError(
                f"Verbindung zu {self._config.base_url} fehlgeschlagen bei {what}: {exc}"
            ) from exc

        if response.status_code >= 400:
            raise _describe_http_error(response, what)

        try:
            return response.json()
        except ValueError as exc:
            raise FastFlowError(
                f"Antwort bei {what} war kein JSON (Status {response.status_code})."
            ) from exc

    async def get_text(
        self,
        path: str,
        *,
        what: str,
        params: dict[str, Any] | None = None,
    ) -> str:
        """GET mit roher Text-Antwort.

        ``GET /api/runs/{id}/logs`` liefert eine ``PlainTextResponse``, kein JSON –
        der Body darf deshalb nicht durch den JSON-Parser laufen.
        """
        cleaned = {k: v for k, v in (params or {}).items() if v is not None}
        try:
            response = await self._client.get(
                path, params=cleaned, headers={"Accept": "text/plain"}
            )
        except httpx.TimeoutException as exc:
            raise FastFlowError(
                f"Zeitüberschreitung nach {self._config.timeout_seconds:.0f}s bei {what}. "
                "Die Instanz antwortet nicht oder die Abfrage ist zu groß."
            ) from exc
        except httpx.HTTPError as exc:
            raise FastFlowError(
                f"Verbindung zu {self._config.base_url} fehlgeschlagen bei {what}: {exc}"
            ) from exc

        if response.status_code >= 400:
            raise _describe_http_error(response, what)
        return response.text
