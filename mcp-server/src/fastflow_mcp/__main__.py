"""Einstiegspunkt: ``fastflow-mcp`` bzw. ``python -m fastflow_mcp``.

Der Server spricht stdio. stdout gehört damit vollständig dem MCP-Protokoll –
jede Diagnoseausgabe muss nach stderr, sonst zerstört sie den Transport.
"""

from __future__ import annotations

import sys

from .client import FastFlowClient
from .config import ConfigError, load_config
from .server import build_server


def main() -> int:
    """Startet den Server auf stdio. Gibt einen Exit-Code zurück."""
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"fastflow-mcp: {exc}", file=sys.stderr)
        return 2

    client = FastFlowClient(config)
    server = build_server(config, client)

    print(
        f"fastflow-mcp: verbunden mit {config.base_url} "
        f"(Redaktion: {'an' if config.redact_secrets else 'AUS'})",
        file=sys.stderr,
    )

    try:
        server.run(transport="stdio")
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
