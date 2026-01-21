---
sidebar_position: 1
---

# Pipelines – Übersicht

Das Pipeline-Repository wird als Volume in den Orchestrator-Container gemountet (oder per Git-Sync bereitgestellt). Pipelines werden **automatisch erkannt** – **Zero-Config Discovery**: keine Registrierung in DB oder UI, Code pushen reicht.

:::tip
Nutze das **[fastflow-pipeline-template](https://github.com/ttuhin03/fastflow-pipeline-template)** für einen schnellen Einstieg, vorgefertigte Beispiele und eine saubere Struktur.
:::

## Pipeline hinzufügen (Zero-Config Discovery)

Du musst Pipelines **nicht** in einer Datenbank oder der UI anlegen. Vier Schritte:

1. **Ordner anlegen:** Neues Verzeichnis unter `pipelines/` (z.B. `pipelines/data_sync/`). Der **Ordnername** = **Pipeline-Name** in der UI.
2. **`main.py`:** Einstiegspunkt. Fast-Flow führt diese Datei aus.
3. **`requirements.txt` (optional):** Externe Pakete. Standard-Python-Format.
4. **`pipeline.json` (optional):** Limits, Retries, Timeout, Beschreibung, Tags, `python_version` (beliebig pro Pipeline, z.B. 3.10, 3.11, 3.12), `webhook_key`. [Referenz](/docs/pipelines/referenz).

Nach Sync bzw. Neustart erscheint die Pipeline in der UI. Kein `docker build`, kein manueller Upload.

---

## Verzeichnisstruktur

```
pipelines/
├── pipeline_a/              # Standard: main.py + requirements.txt + pipeline.json
│   ├── main.py
│   ├── requirements.txt
│   └── pipeline.json
├── pipeline_b/              # Eigenes JSON: {pipeline_name}.json statt pipeline.json
│   ├── main.py
│   └── data_processor.json
├── pipeline_c/              # Minimal: nur main.py
│   └── main.py
└── failing_pipeline/        # Beispiel: bewusst fehlerschlagend (für UI/Retry-Tests)
    ├── main.py
    └── pipeline.json
```

Weitere typische Szenarien (z.B. mit Verzögerung, OOM-Test, Retry-Demo) findest du im [Pipeline-Template](https://github.com/ttuhin03/fastflow-pipeline-template).

---

## Lokal testen: „If it runs, it runs“

Ein häufiges Problem bei Orchestratoren: **Lokal läuft alles, in der Produktionsumgebung nicht** – weil Images, Python-Versionen oder Pfade abweichen.

Fast-Flow nutzt **uv** und eine einheitliche Laufzeitumgebung. **Lokal ist identisch mit dem Orchestrator.**

Test in Sekunden:

```bash
cd pipelines/pipeline_a
uv pip install -r requirements.txt   # oder: pip install -r requirements.txt
python main.py
```

:::important
**Wenn das Skript hier erfolgreich durchläuft, läuft es auch im Fast-Flow-Orchestrator.** Kein separates Docker-Image für deine Pipeline nötig.
:::

Entsprechender Befehl wie im Container: `uv run --with-requirements requirements.txt main.py` (ohne vorheriges `pip install`).

---

## JIT-Effekt (Just-In-Time)

Fast-Flow nutzt **keine** eigenen Docker-Images pro Pipeline, sondern JIT-Containerisierung:

| Aspekt | Beschreibung |
|--------|--------------|
| **Sofort live** | Kein 5‑Minuten-`docker build` und `docker push`. Nach `git push` und Sync ist der Code lauffähig. |
| **uv** | Dependencies werden zur Laufzeit mit `uv` installiert. |
| **Python-Version** | Beliebig pro Pipeline (z.B. 3.10, 3.11, 3.12) über `python_version` in pipeline.json. |
| **Caching** | Projektweiter, geteilter uv-Cache → Installation oft **&lt; 500 ms** bei gecachten Paketen. |
| **Isolation** | Jeder Run läuft in einem **sauberen, isolierten** Docker-Container (Sicherheit, Ressourcenbegrenzung). |

---

## Beispiel-Galerie (Typische Szenarien)

| Szenario | Beschreibung | Typische Dateien |
|----------|--------------|------------------|
| **Standard** | Env-Vars, Dependencies, Limits | `main.py`, `requirements.txt`, `pipeline.json` |
| **Minimal** | Nur Python, keine Deps | `main.py` |
| **Eigenes JSON** | Metadaten unter anderem Namen | `main.py`, `{pipeline_name}.json` |
| **Fehler-Test** | Bewusst `FAILED` (z.B. für UI/Retry) | `main.py` mit `sys.exit(1)` oder Exception, optional `pipeline.json` |
| **Laufzeit-Test** | Verzögerung (z.B. `time.sleep(20)`) zum Prüfen von Status/Logs | `main.py`, ggf. `pipeline.json` (timeout) |
| **Retry-Demo** | Zufälliger Erfolg/Fehler zur Erprobung von `retry_attempts`/`retry_strategy` | `main.py`, `pipeline.json` |
| **Ressourcen-Limits** | OOM- oder CPU-Test mit `mem_hard_limit`/`cpu_hard_limit` | `main.py` (z.B. Speicher allokieren), `pipeline.json` |
| **Verschiedene Python-Versionen** | Jede Pipeline mit eigener Version (z.B. A mit 3.11, B mit 3.12) | `main.py`, `pipeline.json` mit `python_version` |

Viele davon sind im [fastflow-pipeline-template](https://github.com/ttuhin03/fastflow-pipeline-template) vorkonfiguriert.

## `main.py` (erforderlich)

Jede Pipeline braucht eine `main.py` im eigenen Verzeichnis.

**Ausführung:** `uv run --python {version} --with-requirements {requirements.txt} {main.py}` – `{version}` kommt aus `python_version` in pipeline.json (beliebig pro Pipeline: 3.10, 3.11, 3.12, …) oder `DEFAULT_PYTHON_VERSION` (z.B. 3.11).

- Code kann von oben nach unten laufen (keine `main()` nötig).
- Optional: `main()` mit `if __name__ == "__main__"`.

**Einfaches Skript:**

```python
# main.py
import os
print("Pipeline gestartet")
data = os.getenv("MY_SECRET")
print(f"Verarbeite Daten: {data}")
```

**Mit `main()` (optional):**

```python
# main.py
def main():
    print("Pipeline gestartet")
    # ... Logik ...

if __name__ == "__main__":
    main()
```

**Fehler:** Unbehandelte Exceptions → Exit-Code ≠ 0 → Run wird als `FAILED` markiert.

## `requirements.txt` (optional)

Standard-Python-Format. Dependencies werden von `uv` beim Start installiert.

```
requests==2.31.0
pandas==2.1.0
numpy==1.24.3
```

- Shared uv-Cache: bei gecachten Paketen oft < 1 Sekunde.
- Beim Git-Sync können Dependencies vorgeladen werden (`UV_PRE_HEAT`).

## `pipeline.json` (optional)

Metadaten für Limits, Timeout, Retries, Beschreibung, Tags, `python_version` (beliebig pro Pipeline konfigurierbar) und `default_env`.

- **Dateinamen:** `pipeline.json` (bevorzugt) oder `{pipeline_name}.json` (z.B. `data_processor.json`).

Vollständige Feldbeschreibung: [pipeline.json Referenz](/docs/pipelines/referenz).

## Pipeline-Erkennung

- **Discovery:** Automatisch beim Git-Sync (oder beim Start, wenn Verzeichnis gemountet ist).
- **Name:** Verzeichnisname = Pipeline-Name (z.B. `pipeline_a/` → `pipeline_a`).
- **Pflicht:** Ordner muss `main.py` enthalten, sonst wird er ignoriert.
- **Keine manuelle Registrierung** nötig.

## Vollständiges Beispiel

```
pipelines/
└── data_processor/
    ├── main.py
    ├── requirements.txt
    └── data_processor.json
```

**`main.py`:**

```python
import os
import requests
import json

def process_data():
    api_key = os.getenv("API_KEY")
    data = fetch_data(api_key)
    result = transform_data(data)
    save_result(result)

def fetch_data(api_key):
    response = requests.get("https://api.example.com/data", headers={"Authorization": f"Bearer {api_key}"})
    return response.json()

def transform_data(data):
    return data  # ...

def save_result(result):
    with open("/tmp/result.json", "w") as f:
        json.dump(result, f)

if __name__ == "__main__":
    process_data()
```

**`requirements.txt`:**

```
requests==2.31.0
```

**`data_processor.json`:** Siehe [Referenz](/docs/pipelines/referenz).

## Nächste Schritte

- [**Erste Pipeline**](/docs/pipelines/erste-pipeline) – Tutorial: Von null zur ersten laufenden Pipeline
- [**Erweiterte Pipelines**](/docs/pipelines/erweiterte-pipelines) – Retries, Timeout, Scheduling, Webhooks, Struktur
- [**pipeline.json Referenz**](/docs/pipelines/referenz) – Alle Felder und das Verhalten von Limits
- [**Konfiguration**](/docs/deployment/CONFIGURATION) – `PIPELINES_DIR`, `UV_CACHE_DIR`, Git-Sync
