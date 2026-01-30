---
sidebar_position: 3
---

# Erweiterte Pipelines

Sobald die erste Pipeline läuft, geht es um Robustheit, Planung und saubere Struktur. Dieser Abschnitt behandelt Retries, Timeouts, Secrets, Scheduling, Webhooks, Ressourcen-Limits und typische Muster für aufwendigere Pipelines.

---

## 1. Code strukturieren

### 1.1 `main()` und klare Schritte

Auch wenn ein „flat“ Skript (alles von oben nach unten) funktioniert, helfen **Funktionen** und eine `main()` beim Lesen und Testen:

```python
# main.py
import sys

def laden():
    # Daten holen
    pass

def transformieren(daten):
    # Verarbeiten
    pass

def speichern(ergebnis):
    # Ausgabe
    pass

def main():
    daten = laden()
    ergebnis = transformieren(daten)
    speichern(ergebnis)
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
```

**Vorteil:** Du kannst `laden()`, `transformieren()` usw. einzeln testen oder in anderen Pipelines wiederverwenden.

### 1.2 Mehrere Dateien im Pipeline-Ordner

Du darfst im selben Ordner weitere Module anlegen, z.B. `utils.py`, `config.py`. **Einstiegspunkt** ist immer `main.py`. Andere Dateien werden nur durch Imports von `main.py` aus geladen.

Beispiel:

```
pipelines/data_job/
├── main.py        # from utils import parse_date
├── utils.py
└── requirements.txt
```

Beachte: Der **Working Directory** im Container ist der Pipeline-Ordner. Relative Imports wie `from . import utils` oder `import utils` (wenn `utils.py` im gleichen Ordner liegt) funktionieren.

---

## 2. Retries und Timeout

### 2.1 Automatische Wiederholungen

Wenn eine Pipeline **FAILED** endet (Exit-Code ≠ 0), kann Fast-Flow sie automatisch erneut starten. Die Anzahl legst du fest.

**Global** (für alle Pipelines) in der [Konfiguration](/docs/deployment/CONFIGURATION): `RETRY_ATTEMPTS`.

**Pro Pipeline** in `pipeline.json`:

```json
{
  "retry_attempts": 3
}
```

Der Pipeline-Wert überschreibt den globalen. Bei z.B. `3` gibt es bis zu **3 Wiederholungsversuche** nach dem ersten Fehlschlag.

**Typischer Anwendungsfall:** Instabile externe APIs oder kurze Netzwerkaussetzer. Bei logischen Fehlern (falsche Daten, Bugs) bringen Retries oft wenig – hier Fehlerbehandlung im Code verbessern.

**Retry-Strategie (`retry_strategy`):** Zusätzlich zu `retry_attempts` kannst du in `pipeline.json` festlegen, **wie lange** vor jedem erneuten Versuch gewartet wird: z.B. **Exponential Backoff** (für flatternde APIs), **Fixed Delay** (feste Sekunden) oder **Custom Schedule** (Liste von Wartezeiten). Siehe [pipeline.json Referenz – Retry-Strategien](/docs/pipelines/referenz#retry-strategien).

### 2.2 Timeout

Läuft eine Pipeline zu lange, kannst du sie nach einer gewissen **Laufzeit** (Sekunden) abbrechen.

**Global:** `CONTAINER_TIMEOUT` (in Sekunden).

**Pro Pipeline** in `pipeline.json`:

```json
{
  "timeout": 3600
}
```

`3600` = 1 Stunde. Der Pipeline-Wert hat Vorrang vor dem globalen.

**Hinweis:** Beim Timeout wird der Container beendet. Die Pipeline endet als **FAILED** (oder vergleichbar). Große Timeouts nur setzen, wenn der Job wirklich lange laufen soll (z.B. große Dateien, viele API-Calls).

---

## 3. Secrets, Parameter und `default_env`

### 3.1 Secrets vs. Parameter

| | **Secrets** | **Parameter** |
|---|-------------|----------------|
| **Speicherung** | Verschlüsselt in der DB | Unverschlüsselt |
| **Einsatz** | API-Keys, Passwörter, Tokens | Endpunkte, Dateinamen, Flags |
| **In der Pipeline** | Beide als Umgebungsvariablen (`os.getenv("NAME")`) |

Beides wird in der **UI** pro Pipeline (oder global, je nach Fast-Flow-Version) verwaltet. Im Code unterscheidest du nicht – alles kommt als Env-Var.

### 3.2 `default_env` in `pipeline.json`

Für **nicht sensible** Defaults (z.B. `LOG_LEVEL`, `API_BASE`, `DRY_RUN=false`) kannst du `default_env` in `pipeline.json` nutzen:

```json
{
  "description": "ETL-Job",
  "default_env": {
    "LOG_LEVEL": "INFO",
    "API_BASE": "https://api.example.com",
    "DRY_RUN": "false"
  }
}
```

- Diese Werte werden bei **jedem** Run gesetzt.
- In der UI zusätzlich gesetzte Env-Vars (z.B. für einen einzelnen Run) **überschreiben** diese Defaults.
- **Secrets nicht** in `default_env` – dafür die UI verwenden. `pipeline.json` liegt typischerweise im Git und wäre sonst ein Sicherheitsrisiko.

---

## 4. Scheduling: Zeitgesteuerte Ausführung

Statt nur manuell oder per Webhook zu starten, kannst du Pipelines **nach Zeitplan** laufen lassen (Cron oder Intervall).

### In der UI

Unter der jeweiligen Pipeline (oder im Scheduler-Bereich) lassen sich **Cron-Ausdrücke** oder **Intervall** (z.B. alle 6 Stunden) einrichten. Die konkreten Felder hängen von der Fast-Flow-Version ab; typisch:

- **Cron:** z.B. `0 2 * * *` = täglich um 2:00 Uhr
- **Intervall:** z.B. alle 3600 Sekunden

### Wofür?

- **Täglich:** Reports, Daten-ETL, Aufräumen.
- **Stündlich:** Aggregationen, Prüfungen.
- **Wöchentlich:** Große Berechnungen, Archivistierung.

Die Terminplanung wird in der Datenbank (z.B. über den APScheduler) gespeichert. Details: [API](/docs/api/api) (Scheduler-Endpoints) und [Konfiguration](/docs/deployment/CONFIGURATION).

---

## 5. Webhooks: Externer Start

Über einen **Webhook** kann ein externes System (CI/CD, anderer Service, Cron auf anderem Rechner) eine Pipeline anstoßen, ohne in der Fast-Flow-UI zu sein.

### Aktivierung: `webhook_key` in `pipeline.json`

Webhooks sind **pro Pipeline** aktiv, wenn in `pipeline.json` ein **`webhook_key`** gesetzt ist (nicht leer). Ohne `webhook_key` sind Webhooks für diese Pipeline deaktiviert.

```json
{
  "description": "Sync-Job",
  "webhook_key": "dein-geheimer-schluessel"
}
```

**Wichtig:** Den Schlüssel **geheim** halten – jeder, der die Webhook-URL kennt, kann die Pipeline starten.

### Endpoint und Aufruf

- **Methode:** `POST`
- **URL:** `/api/webhooks/{pipeline_name}/{webhook_key}`
- **Body:** optional (leer oder `{}`). Der Schlüssel steht im Pfad, ein `{"webhook_key": "..."}` im Body ist nicht nötig.

Beispiel:

```bash
curl -X POST "https://deine-instanz.de/api/webhooks/data_sync/dein-geheimer-schluessel"
```

**Antworten:** 200 mit Run-Infos; **401** bei falschem `webhook_key`; **404** wenn die Pipeline nicht existiert, deaktiviert ist oder Webhooks für sie aus sind.

Die **komplette Webhook-URL** (mit deinem Key) siehst du in der Pipeline-Detailansicht der UI und kannst sie dort kopieren. Details: [pipeline.json Referenz – Webhooks](/docs/pipelines/referenz#webhooks-pipeline-per-http-auslösen) und [API](/docs/api/api).

### Typische Nutzung

- **CI/CD:** Nach Build oder Deploy einen Smoke-Test oder Daten-Import starten.
- **Externe Tools:** Wenn ein anderes System „fertig“ ist, triggert es die nächste Stufe in Fast-Flow.
- **Ereignisgesteuert:** In Kombination mit einem Message-Broker oder einer Queue (der Aufrufer liest die Queue und ruft den Webhook auf).

---

## 6. Ressourcen-Limits (CPU, RAM)

Damit eine Pipeline den Rest des Systems nicht überlastet, kannst du **CPU** und **RAM** begrenzen. Das passiert über die `pipeline.json` und wirkt als **Docker-Limits** im Container.

### Hard Limits

- **`cpu_hard_limit`:** CPU-Kerne (z.B. `1.0` = ein Kern, `0.5` = halber Kern). Wird der Container CPU-intensiver, wird er gedrosselt.
- **`mem_hard_limit`:** RAM, z.B. `"512m"`, `"1g"`, `"2g"`. Überschreitung führt zum **OOM-Kill** (Exit-Code 137) – die Pipeline ist **FAILED**.

Beispiel:

```json
{
  "cpu_hard_limit": 1.0,
  "mem_hard_limit": "1g"
}
```

### Soft Limits (nur Monitoring)

- **`cpu_soft_limit`** und **`mem_soft_limit`** werden **nicht** als harte Obergrenze durchgesetzt. Sie dienen der **Überwachung**; Überschreitungen können in der UI als Warnung erscheinen. Nützlich, um zu sehen, ob du die Hard-Limits anheben solltest.

Ausführlich: [pipeline.json Referenz](/docs/pipelines/referenz).

---

## 7. Fehlerbehandlung und Logging

### 7.1 Exceptions und Exit-Code

- **Unbehandelte Exception** → Python beendet mit Exit-Code ≠ 0 → Run **FAILED**.
- **`sys.exit(0)`** → Erfolg. **`sys.exit(1)`** (oder anderer Wert ≠ 0) → Fehler.

Für bessere Logs und Kontrolle:

```python
import sys
import traceback

def main():
    try:
        # ... Logik ...
        return 0
    except ConnectionError as e:
        print("Verbindungsfehler:", e, file=sys.stderr)
        traceback.print_exc()
        return 1
    except ValueError as e:
        print("Datenfehler:", e, file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main())
```

`traceback.print_exc()` erscheint in den **Logs** und hilft beim Debugging.

### 7.2 Logging-Modul

Statt nur `print` kannst du das Standard-**`logging`**-Modul nutzen:

```python
import logging
import os

# Optional: LOG_LEVEL aus Env (z.B. aus default_env oder UI)
level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, level, logging.INFO))
logger = logging.getLogger(__name__)

def main():
    logger.info("Starte Verarbeitung ...")
    # ...
    logger.warning("Keine neuen Daten.")
    logger.info("Fertig.")
    return 0
```

`logging` schreibt nach **stderr**, das in den Fast-Flow-Logs erscheint. So behältst du die Logs auch bei längeren Pipelines übersichtlich.

---

## 8. Längere und robustere Jobs

### 8.1 In kleinen Schritten (Chunks) arbeiten

Sehr große Datenmengen oder viele API-Calls solltest du in **Chunks** verarbeiten:

- Weniger Risiko, den Timeout zu treffen.
- Bei Fehlern ist der Schaden begrenzt; du kannst bei einem definierten Punkt neu ansetzen.

Beispiel-Idee: 100.000 Zeilen → je 1.000 verarbeiten, Fortschritt loggen. Optional einen **Checkpoint** (z.B. „bis Zeile X erledigt“) in einer Datei oder DB speichern und beim nächsten Run fortfahren.

### 8.2 Idempotenz

Wenn eine Pipeline **mehrmals** läuft (Retry, doppelter Webhook, geplanter Lauf), sollte das Ergebnis **idempotent** sein: Zweimal ausführen = gleicher Endzustand wie einmal. Typische Mittel:

- **„Upsert“** statt blindem Anhängen (z.B. in DB oder Dateisystem).
- **Deduplizierung** über IDs oder Zeitstempel.
- **Temporäre Dateien** mit eindeutigem Namen und Aufräumen am Ende.

### 8.3 Externe Dienste (APIs, Datenbanken, Objektstorage)

- **APIs:** `requests` oder `httpx`, Timeouts setzen, Retries im Code (z.B. `tenacity`) für kurze Netzeinbrüche. Secrets (API-Keys) aus `os.getenv`.
- **Datenbanken:** Treiber in `requirements.txt` (z.B. `psycopg2`, `pymysql`, `sqlalchemy`). Connection-Strings als Secrets/Parameter.
- **S3-ähnlicher Storage:** `boto3` oder passende Bibliothek, Credentials aus Env. Bei großen Dateien: Streaming oder Chunk-Transfer, um RAM-Limits zu beachten.

---

## 9. Übersicht: Wann was nutzen?

| Ziel | Wo / Wie |
|------|----------|
| **Wiederholungen bei Fehlern** | `retry_attempts` in `pipeline.json` oder `RETRY_ATTEMPTS` global |
| **Maximale Laufzeit** | `timeout` in `pipeline.json` oder `CONTAINER_TIMEOUT` |
| **Geheime Werte** | Secrets in der UI, `os.getenv("NAME")` im Code |
| **Unkritische Defaults** | `default_env` in `pipeline.json` |
| **Zeitplan** | Scheduling in der UI (Cron/Intervall) |
| **Start von außen** | Webhook-URL, `POST`-Request |
| **CPU/RAM begrenzen** | `cpu_hard_limit`, `mem_hard_limit` in `pipeline.json` |
| **Struktur und Wartbarkeit** | `main()`, Module, `logging` |
| **Große Daten / lange Läufe** | Chunks, Checkpoints, idempotente Logik |
| **Wartezeit zwischen Retries** | `retry_strategy` in `pipeline.json` (exponential_backoff, fixed_delay, custom_schedule) |
| **Webhook-Trigger** | `webhook_key` in `pipeline.json`, `POST /api/webhooks/{pipeline_name}/{webhook_key}` |
| **Notebook: Retries pro Zelle** | `type: "notebook"` + `cells` in `pipeline.json` und/oder Zellen-Metadaten `fastflow`. Siehe [Notebook-Pipelines](/docs/pipelines/notebook-pipelines). |

---

## 10. Best Practices

- **Sauberer Code:** Halte `main.py` modular. Nutze Hilfsfunktionen und gern weitere Module im gleichen Ordner.
- **Umgebungsvariablen:** Konfiguration und Secrets über `os.getenv("NAME")`. Geheime Werte in der **Fast-Flow-UI** als Secrets verwalten, nicht in `pipeline.json` oder im Code.
- **Logs:** Einfach `print()` nutzen. Fast-Flow erfasst **stdout** und **stderr** und streamt sie in die UI. Für strukturiertere Ausgaben: `logging` (siehe Abschnitt 7).

---

## 11. Support: „Wenn es lokal läuft, läuft es in Fast-Flow“

Fast-Flow steht dafür, dass **reines Python, das lokal läuft, auch im Orchestrator läuft** – gleiche Laufzeit (uv), keine eigenen Pipeline-Images.

Wenn dein Skript **lokal** durchläuft, im Orchestrator aber **nicht**, bitte melden:

- **Fast-Flow Issues:** [GitHub Issues](https://github.com/ttuhin03/fastflow/issues)

**Angaben, die helfen:**

- `main.py` (Code)
- `pipeline.json` und `requirements.txt`
- Logs aus der Orchestrator-UI (Run-Logs)

Weitere Schritte und typische Ursachen: [Troubleshooting – Pipeline läuft lokal, im Orchestrator nicht](/docs/troubleshooting#pipeline-lokal-orchestrator-fehlt).

---

## Siehe auch

- [pipeline.json Referenz](/docs/pipelines/referenz) – alle Felder inkl. Soft-Limits, Tags, `enabled`, `type`, `cells`
- [Notebook-Pipelines](/docs/pipelines/notebook-pipelines) – Jupyter-Notebooks, Zellen-Retries, Logs pro Zelle
- [Pipelines – Übersicht](/docs/pipelines/uebersicht) – Grundstruktur, `main.py`, `main.ipynb`, `requirements.txt`
- [Erste Pipeline](/docs/pipelines/erste-pipeline) – Einstieg von null
- [Konfiguration](/docs/deployment/CONFIGURATION) – globale Werte (`RETRY_ATTEMPTS`, `CONTAINER_TIMEOUT`, …)
- [API](/docs/api/api) – Scheduler, Webhooks, Runs
