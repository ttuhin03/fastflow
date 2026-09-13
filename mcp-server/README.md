# fastflow-mcp

Lesender [MCP](https://modelcontextprotocol.io)-Server für den Fast-Flow-Orchestrator.
Gibt einem Agenten Zugriff auf Pipelines, Runs, Statistiken und Logs – ohne
Browser-Session, ohne OpenAPI-Dump im Kontext und ohne dass der Agent das
Credential zu sehen bekommt.

## Warum nicht einfach `curl`?

Weil eine ungedeckelte Antwort den Kontext zerstört, den man zum Diagnostizieren
braucht. Das Log eines gescheiterten ETL-Laufs kann megabytegroß sein. Dieser
Server deckelt jede Antwort **und sagt immer, wie viel er weggelassen hat** –
eine stillschweigend gekürzte Antwort sieht aus wie das ganze Bild und führt zu
falschen Schlüssen.

Dazu kommt `summarize_failures`: „was ist heute Nacht kaputtgegangen" kostet
sonst zwanzig Aufrufe, hier einen.

## Voraussetzung

Ein persönliches API-Token aus der Fast-Flow-UI unter **Einstellungen →
API-Tokens**. Die Scopes bestimmen, was der Server sehen kann:

| Scope | Öffnet | Risiko |
|---|---|---|
| `read` | Pipelines, Runs, Statistiken, Abhängigkeiten | niedrig |
| `logs` | Log-Inhalte und Zell-Ausgaben | mittel |
| `source` | Pipeline-Quelldateien | mittel |
| `run` | Runs starten/abbrechen – **von diesem Server nicht genutzt** | hoch |

Für den vollen Funktionsumfang genügen `read` + `logs`. `source` nur, wenn der
Agent Quelltext lesen können soll. `run` nicht vergeben: dieser Server ist
lesend, und ein Token mit Schreibrechten in einem Agenten, der fremde Log-Inhalte
liest, ist die Kombination, die man vermeiden will (siehe Sicherheit).

## Installation

```bash
uvx fastflow-mcp
```

Oder aus diesem Repository:

```bash
cd mcp-server
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Client-Konfiguration

```json
{
  "mcpServers": {
    "fastflow": {
      "command": "uvx",
      "args": ["fastflow-mcp"],
      "env": {
        "FASTFLOW_URL": "https://fastflow.example.com",
        "FASTFLOW_TOKEN": "ffp_..."
      }
    }
  }
}
```

| Variable | Default | Bedeutung |
|---|---|---|
| `FASTFLOW_URL` | – | Basis-URL der Instanz (**Pflicht**) |
| `FASTFLOW_TOKEN` | – | API-Token mit Präfix `ffp_` (**Pflicht**) |
| `FASTFLOW_TIMEOUT_SECONDS` | `30` | Zeitlimit je Request (1–300) |
| `FASTFLOW_VERIFY_TLS` | `true` | TLS-Zertifikat prüfen |
| `FASTFLOW_REDACT_SECRETS` | `true` | Zugangsdaten in Logs maskieren |

Fehlkonfiguration scheitert beim Start mit einer Meldung auf stderr, nicht später
an unklaren Tool-Fehlern.

## Tools

| Tool | Scope | Deckel |
|---|---|---|
| `list_pipelines` | `read` | – |
| `get_pipeline` | `read` | – |
| `list_runs` | `read` | 100 Runs |
| `get_run` | `read` (+`logs` für Zell-Ausgaben) | 40 Zeilen je Zelle |
| `get_run_logs` | `logs` | 200 Zeilen / 64 KB |
| `get_pipeline_stats` | `read` | 90 Tage |
| `get_dependency_report` | `read` | – |
| `summarize_failures` | `read` (+`logs` für Fehlerzeilen) | 20 Gruppen |

Alle Tools sind als `readOnlyHint` annotiert. Runs starten, abbrechen und
wiederholen ist bewusst nicht enthalten.

### Resources

- `fastflow://pipeline/{name}/source/{datei}` – `main.py`, `requirements.txt` oder `pipeline.json` (Scope `source`)
- `fastflow://run/{run_id}/log` – vollständiges Log, 64 KB (Scope `logs`)
- `fastflow://graph` – Abhängigkeitsgraph als JSON (Scope `read`)

### Prompts

- `diagnose_run` – Standard-Triage eines fehlgeschlagenen Runs
- `triage_window` – Überblick über ein Zeitfenster, beginnend mit der Aggregation

## Sicherheit

**Prompt Injection.** Logs und Quelltext sind Inhalte, die Fast-Flow nicht
kontrolliert. Eine Pipeline, die eine fremde API abfragt, kann eine Zeile ins Log
schreiben, die wie eine Anweisung aussieht. Jede Rückgabe mit solchem Inhalt
trägt deshalb einen Hinweis, dass es sich um Daten und nicht um Anweisungen
handelt. Gefährlich wird das erst in Kombination mit Schreibrechten – deshalb:
**kein `run`-Scope für dieses Token.**

**Maskierung ist unvollständig.** Der Redactor erkennt Werte mit
charakteristischer Form: `ffp_`, `ghp_`, `AKIA…`, `xox…`, JWTs, private
Schlüssel und Zuweisungen wie `password=`. Ein Passwort, das in einer
Fehlermeldung als gewöhnlicher Satz steht („login failed for hunter2"), sieht wie
normaler Text aus und bleibt stehen. Fast-Flow maskiert Logs serverseitig
nicht – wer Pipeline-Logs über einen Agenten liest, trifft eine bewusste
Entscheidung. `FASTFLOW_REDACT_SECRETS=false` schaltet die Maskierung ab.

**Das Token** wird ausschließlich als `Authorization`-Header verwendet. Es
erscheint in keiner Fehlermeldung, keinem Log und keinem Traceback – `Config`
maskiert es auch in `repr`.

## Entwicklung

```bash
.venv/bin/python -m pytest
```

Die Tests laufen gegen einen Mock-Transport, ohne laufende Fast-Flow-Instanz.
