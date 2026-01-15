# Pipeline-Repository-Dokumentation

Diese Dokumentation beschreibt detailliert, wie ein Pipeline-Repository strukturiert sein muss und welche Konfigurationsmöglichkeiten in der `pipeline.json` verfügbar sind.

## Repository-Struktur

Ein Pipeline-Repository ist ein Git-Repository, das Pipeline-Definitionen enthält. Jede Pipeline ist ein eigenes Verzeichnis mit mindestens einer `main.py` Datei.

### Verzeichnisstruktur

```
pipelines/
├── pipeline_a/
│   ├── main.py              # Haupt-Pipeline-Skript (ERFORDERLICH)
│   ├── requirements.txt     # Python-Dependencies (optional)
│   └── pipeline.json        # Metadaten (optional)
├── pipeline_b/
│   ├── main.py
│   ├── requirements.txt
│   └── data_processor.json  # Alternative: {pipeline_name}.json
└── pipeline_c/
    └── main.py              # Minimal: Nur main.py
```

### Pipeline-Erkennung

- **Automatische Discovery**: Pipelines werden automatisch beim Git-Sync erkannt
- **Pipeline-Name**: Entspricht dem Verzeichnisnamen (z.B. `pipeline_a/` → Pipeline-Name: `pipeline_a`)
- **Validierung**: Pipeline muss `main.py` Datei enthalten, sonst wird sie ignoriert
- **Keine manuelle Registrierung**: Pipelines werden automatisch verfügbar

## Pipeline-Dateien

### 1. `main.py` (ERFORDERLICH)

Das Haupt-Pipeline-Skript. Jede Pipeline muss eine `main.py` Datei im eigenen Verzeichnis haben.

#### Ausführungsweise

Pipelines werden mit `uv run --with-requirements {requirements.txt} {main.py}` ausgeführt.

**Option 1: Einfaches Skript (von oben nach unten)**
```python
# main.py
import os
print("Pipeline gestartet")
data = os.getenv("MY_SECRET")
print(f"Verarbeite Daten: {data}")
# ... weiterer Code ...
```

**Option 2: Mit main() Funktion (optional)**
```python
# main.py
def main():
    print("Pipeline gestartet")
    # ... Logik ...

if __name__ == "__main__":
    main()
```

#### Error-Handling

- Bei uncaught Exceptions gibt Python automatisch Exit-Code != 0 zurück
- Pipeline wird als `FAILED` markiert
- Logs werden automatisch erfasst

#### Environment-Variablen

Pipeline kann auf Environment-Variablen zugreifen:
```python
import os

api_key = os.getenv("API_KEY")
log_level = os.getenv("LOG_LEVEL", "INFO")  # Mit Default-Wert
```

### 2. `requirements.txt` (OPTIONAL)

Python-Dependencies für die Pipeline. Werden von `uv` dynamisch installiert.

#### Format

Standard Python requirements.txt Format:
```
requests==2.31.0
pandas==2.1.0
numpy==1.24.3
```

#### Hinweise

- Dependencies werden beim Pipeline-Start automatisch installiert (via `uv`)
- Shared Cache ermöglicht schnelle Installation (< 1 Sekunde bei Cached-Dependencies)
- Pre-Heating: Dependencies können beim Git-Sync vorgeladen werden (UV_PRE_HEAT)
- Pipelines ohne `requirements.txt` haben keine externen Dependencies

### 3. `pipeline.json` oder `{pipeline_name}.json` (OPTIONAL)

Metadaten-Datei für Resource-Limits und Konfiguration.

#### Dateinamen

- `pipeline.json` (Standard, wird bevorzugt)
- `{pipeline_name}.json` (Alternative, z.B. `data_processor.json`)

## Pipeline-JSON-Konfiguration

Die `pipeline.json` Datei enthält alle konfigurierbaren Metadaten für eine Pipeline. Alle Felder sind optional.

### Vollständiges JSON-Schema

```json
{
  "cpu_hard_limit": 1.0,
  "mem_hard_limit": "1g",
  "cpu_soft_limit": 0.8,
  "mem_soft_limit": "800m",
  "timeout": 3600,
  "retry_attempts": 3,
  "description": "Prozessiert täglich eingehende Daten",
  "tags": ["data-processing", "daily"],
  "enabled": true,
  "default_env": {
    "LOG_LEVEL": "INFO",
    "DEBUG": "false"
  },
  "webhook_key": "my-secret-webhook-key"
}
```

### Felder im Detail

#### Resource-Limits

##### `cpu_hard_limit` (Float, optional)

CPU-Limit in Kernen. Wird beim Container-Start als Docker-Limit gesetzt.

**Beispiele:**
- `1.0` = 1 vollständiger CPU-Kern
- `0.5` = halber CPU-Kern
- `2.0` = 2 CPU-Kerne

**Verhalten:**
- Überschreitung führt zu CPU-Throttling
- Wird von Docker durchgesetzt
- Standard: Kein Limit (verwendet System-Default)

##### `mem_hard_limit` (String, optional)

Memory-Limit. Wird beim Container-Start als Docker-Limit gesetzt.

**Format:**
- `"512m"` = 512 Megabyte
- `"1g"` = 1 Gigabyte
- `"2g"` = 2 Gigabyte

**Verhalten:**
- Überschreitung führt zu OOM-Kill (Exit-Code 137)
- Wird von Docker durchgesetzt
- Standard: Kein Limit (verwendet System-Default)

##### `cpu_soft_limit` (Float, optional)

CPU-Soft-Limit für Monitoring. Wird nur überwacht, keine Limitierung.

**Verwendung:**
- Nützlich für frühe Erkennung von Resource-Problemen
- Überschreitung wird im Frontend angezeigt (Warnung)
- Keine tatsächliche Limitierung

**Beispiele:**
- `0.8` = Warnung bei > 80% CPU-Verbrauch
- `1.5` = Warnung bei > 150% CPU-Verbrauch

##### `mem_soft_limit` (String, optional)

Memory-Soft-Limit für Monitoring. Wird nur überwacht, keine Limitierung.

**Format:** Gleich wie `mem_hard_limit`

**Verwendung:**
- Nützlich für frühe Erkennung von Resource-Problemen
- Überschreitung wird im Frontend angezeigt (Warnung)
- Keine tatsächliche Limitierung

#### Pipeline-Konfiguration

##### `timeout` (Integer, optional)

Timeout in Sekunden. Pipeline wird abgebrochen, wenn sie länger läuft.

**Beispiele:**
- `60` = 1 Minute
- `3600` = 1 Stunde
- `86400` = 1 Tag

**Verhalten:**
- Pipeline-spezifisch, überschreibt globales `CONTAINER_TIMEOUT`
- Wenn nicht gesetzt: Verwendet globales `CONTAINER_TIMEOUT`
- Bei Überschreitung: Container wird gestoppt, Run wird als `FAILED` markiert

##### `retry_attempts` (Integer, optional)

Anzahl Retry-Versuche bei Fehlern.

**Beispiele:**
- `0` = Keine Retries
- `3` = 3 Retry-Versuche
- `5` = 5 Retry-Versuche

**Verhalten:**
- Pipeline-spezifisch, überschreibt globales `RETRY_ATTEMPTS`
- Retries werden nur bei fehlgeschlagenen Runs durchgeführt
- Wenn nicht gesetzt: Verwendet globales `RETRY_ATTEMPTS`

##### `enabled` (Boolean, optional)

Pipeline aktiviert/deaktiviert.

**Werte:**
- `true` = Pipeline ist aktiviert (Standard)
- `false` = Pipeline ist deaktiviert

**Verhalten:**
- Deaktivierte Pipelines können nicht gestartet werden
- Deaktivierte Pipelines werden in der UI angezeigt, aber als "deaktiviert" markiert
- Scheduler-Jobs für deaktivierte Pipelines werden nicht ausgeführt

#### Dokumentation

##### `description` (String, optional)

Beschreibung der Pipeline. Wird in der UI angezeigt.

**Beispiele:**
- `"Prozessiert täglich eingehende Daten"`
- `"Extrahiert Daten aus API und speichert in Datenbank"`
- `"Führt Machine-Learning-Modell-Training durch"`

**Verwendung:**
- Wird in Pipeline-Liste und Pipeline-Details angezeigt
- Hilft bei der Identifikation der Pipeline-Funktion

##### `tags` (Array[String], optional)

Tags für Kategorisierung/Filterung in der UI.

**Beispiele:**
```json
{
  "tags": ["data-processing", "daily", "reports"]
}
```

**Verwendung:**
- Filterung in der Pipeline-Liste
- Kategorisierung von Pipelines
- Suche nach Pipelines

#### Environment-Variablen

##### `default_env` (Object, optional)

Pipeline-spezifische Default-Environment-Variablen.

**Beispiel:**
```json
{
  "default_env": {
    "LOG_LEVEL": "INFO",
    "DEBUG": "false",
    "API_ENDPOINT": "https://api.example.com"
  }
}
```

**Verhalten:**
- Diese werden bei jedem Pipeline-Start gesetzt
- Können in der UI durch zusätzliche Env-Vars ergänzt werden (werden zusammengeführt)
- UI-Werte haben Vorrang bei Konflikten
- Nützlich für Pipeline-spezifische Konfiguration

**Wichtige Hinweise:**
- Secrets sollten NICHT hier gespeichert werden (verwende stattdessen Secrets-Management in der UI)
- Sensible Daten gehören in Secrets, nicht in `default_env`
- `default_env` ist für nicht-sensible Konfiguration gedacht

#### Webhooks

##### `webhook_key` (String, optional)

Webhook-Schlüssel für HTTP-Trigger.

**Beispiel:**
```json
{
  "webhook_key": "my-secret-webhook-key"
}
```

**Verwendung:**
- Pipeline kann via HTTP-Webhook getriggert werden
- URL-Format: `POST /api/webhooks/{pipeline_name}/{webhook_key}`
- Beispiel: `POST /api/webhooks/pipeline_a/my-secret-webhook-key`

**Sicherheit:**
- Webhook-Key sollte ein zufälliger, sicherer String sein
- Nur Pipelines mit gesetztem `webhook_key` können via Webhook getriggert werden
- Webhook-Key wird validiert (muss exakt übereinstimmen)

**Beispiel-Request:**
```bash
curl -X POST http://localhost:8000/api/webhooks/pipeline_a/my-secret-webhook-key
```

## Beispiele

### Minimales Beispiel

**Verzeichnisstruktur:**
```
pipelines/
└── simple_pipeline/
    └── main.py
```

**`main.py`:**
```python
print("Hello, World!")
```

### Beispiel mit Dependencies

**Verzeichnisstruktur:**
```
pipelines/
└── api_processor/
    ├── main.py
    └── requirements.txt
```

**`main.py`:**
```python
import requests
import os

def main():
    api_key = os.getenv("API_KEY")
    response = requests.get(
        "https://api.example.com/data",
        headers={"Authorization": f"Bearer {api_key}"}
    )
    data = response.json()
    print(f"Verarbeitet {len(data)} Datensätze")

if __name__ == "__main__":
    main()
```

**`requirements.txt`:**
```
requests==2.31.0
```

### Vollständiges Beispiel

**Verzeichnisstruktur:**
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
from datetime import datetime

def process_data():
    api_key = os.getenv("API_KEY")
    api_endpoint = os.getenv("API_ENDPOINT", "https://api.example.com")
    log_level = os.getenv("LOG_LEVEL", "INFO")
    
    print(f"[{log_level}] Pipeline gestartet um {datetime.now()}")
    
    # Daten abrufen
    response = requests.get(
        f"{api_endpoint}/data",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30
    )
    response.raise_for_status()
    data = response.json()
    
    # Daten verarbeiten
    processed = []
    for item in data:
        processed.append({
            "id": item["id"],
            "processed_at": datetime.now().isoformat(),
            "value": item["value"] * 2
        })
    
    # Ergebnis speichern
    output_file = "/tmp/result.json"
    with open(output_file, "w") as f:
        json.dump(processed, f, indent=2)
    
    print(f"[{log_level}] {len(processed)} Datensätze verarbeitet")
    print(f"[{log_level}] Ergebnis gespeichert in {output_file}")

if __name__ == "__main__":
    process_data()
```

**`requirements.txt`:**
```
requests==2.31.0
```

**`data_processor.json`:**
```json
{
  "enabled": true,
  "description": "Prozessiert eingehende Daten von API und erstellt Reports",
  "tags": ["data-processing", "reports", "api"],
  "timeout": 1800,
  "retry_attempts": 2,
  "cpu_hard_limit": 1.0,
  "mem_hard_limit": "512m",
  "cpu_soft_limit": 0.8,
  "mem_soft_limit": "400m",
  "default_env": {
    "LOG_LEVEL": "INFO",
    "API_ENDPOINT": "https://api.example.com"
  },
  "webhook_key": "data-processor-secret-key-12345"
}
```

## Best Practices

1. **Resource-Limits**: Setze realistische Limits basierend auf tatsächlichem Verbrauch
2. **Timeouts**: Setze Timeouts, die ausreichend Zeit für die Pipeline lassen, aber nicht zu groß sind
3. **Retries**: Verwende Retries für Pipelines, die temporäre Fehler haben können
4. **Description**: Schreibe aussagekräftige Beschreibungen für bessere Übersicht
5. **Tags**: Verwende konsistente Tags für bessere Kategorisierung
6. **Secrets**: Verwende Secrets-Management in der UI, nicht `default_env` für sensible Daten
7. **Webhook-Keys**: Verwende sichere, zufällige Webhook-Keys
8. **Requirements**: Piniere Dependency-Versionen für Reproduzierbarkeit

## Troubleshooting

### Pipeline wird nicht erkannt

- Prüfe, ob `main.py` im Pipeline-Verzeichnis existiert
- Prüfe, ob das Verzeichnis im Git-Repository ist
- Führe Git-Sync aus, um Pipelines zu aktualisieren

### Pipeline schlägt fehl

- Prüfe Logs in der Run-Detail-Ansicht
- Prüfe Exit-Code (0 = Erfolg, != 0 = Fehler)
- Prüfe, ob alle Dependencies in `requirements.txt` vorhanden sind
- Prüfe, ob Environment-Variablen korrekt gesetzt sind

### Resource-Limits werden überschritten

- Prüfe Soft-Limits im Frontend (Warnungen)
- Erhöhe Hard-Limits in `pipeline.json` wenn nötig
- Prüfe System-Ressourcen (CPU, RAM)

### Webhook funktioniert nicht

- Prüfe, ob `webhook_key` in `pipeline.json` gesetzt ist
- Prüfe, ob Webhook-Key in URL exakt übereinstimmt
- Prüfe, ob Pipeline aktiviert ist (`enabled: true`)
