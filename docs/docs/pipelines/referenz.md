---
sidebar_position: 5
---

# pipeline.json – Referenz

Optionale Metadaten-Datei für Resource-Limits, Timeout, Retries, Beschreibung, Tags und Environment-Variablen.

**Dateinamen:** `pipeline.json` (bevorzugt) oder `{pipeline_name}.json` (z.B. `data_processor.json`).

## JSON-Format (Beispiel)

**Skript-Pipeline:**

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
  "python_version": "3.12",
  "default_env": {
    "LOG_LEVEL": "INFO",
    "DEBUG": "false"
  }
}
```

**Notebook-Pipeline** (mit Zellen-Retries):

```json
{
  "type": "notebook",
  "enabled": true,
  "description": "Notebook mit Zellen-Retries",
  "python_version": "3.12",
  "timeout": 120,
  "cells": [
    { "retries": 2, "delay_seconds": 1 },
    { "retries": 0 },
    { "retries": 3, "delay_seconds": 1 }
  ]
}
```

## Felder

### Resource-Limits

| Feld | Standard | Beschreibung |
|------|----------|--------------|
| `cpu_hard_limit` | – | CPU-Limit in Kernen (z.B. `0.5`, `1.0`, `2.0`). **Strikt** durchgesetzt (Throttling). |
| `mem_hard_limit` | – | RAM (z.B. `"512m"`, `"1g"`, `"2g"`). **OOM-Kill** bei Überschreitung. |
| `cpu_soft_limit` | – | CPU-Schwelle nur für **Monitoring/Warnungen** in der UI, keine Limitierung. |
| `mem_soft_limit` | – | RAM-Schwelle nur für **Monitoring/Warnungen** in der UI, keine Limitierung. |

### Pipeline-Typ

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `type` | String, optional | **`"script"`** (Standard) oder **`"notebook"`**. Bei `"notebook"` muss im Pipeline-Ordner **`main.ipynb`** existieren; dann wird das Notebook Zelle für Zelle ausgeführt (siehe [Notebook-Pipelines](/docs/pipelines/notebook-pipelines)). Bei `"script"` wird **`main.py`** ausgeführt. |

### Pipeline-Konfiguration

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `timeout` | Integer, optional | Timeout in Sekunden (überschreibt globales `CONTAINER_TIMEOUT`). |
| `retry_attempts` | Integer, optional | Anzahl Retries bei Fehlern (überschreibt globales `RETRY_ATTEMPTS`). **Hinweis:** Bei Notebook-Pipelines werden **Pipeline-Level-Retries** nicht ausgeführt; es gelten nur die [Zellen-Retries](/docs/pipelines/notebook-pipelines#zellen-retries-das-cells-array) in `cells` bzw. Zellen-Metadaten. |
| `retry_strategy` | Object, optional | Wartezeit-Strategie zwischen Retries. Siehe [Retry-Strategien](#retry-strategien). Gilt nur für Skript-Pipelines. |
| `enabled` | Boolean, optional | Pipeline aktiviert/deaktiviert (Standard: `true`). |
| `python_version` | String, optional | Python-Version für `uv run --python` – **beliebig pro Pipeline** (z.B. `"3.10"`, `"3.11"`, `"3.12"`). Jede Pipeline kann eine andere Version nutzen. Fehlt: `DEFAULT_PYTHON_VERSION` (Standard 3.11). |

### Notebook-Pipelines: Zellen-Retries (`cells`)

Nur relevant, wenn **`type`** = **`"notebook"`**. Siehe ausführlich [Notebook-Pipelines – Zellen-Retries](/docs/pipelines/notebook-pipelines#zellen-retries-das-cells-array).

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `cells` | Array, optional | Pro **Code-Zelle** ein Eintrag (Index 0 = erste Code-Zelle, 1 = zweite, …). Jeder Eintrag kann **`retries`** (Integer) und **`delay_seconds`** (Number) enthalten. Fehlt ein Eintrag oder das Array: 0 Retries, 1 s Pause. Zellen-Metadaten im Notebook (`metadata.fastflow`) überschreiben die Werte für die jeweilige Zelle. |

### Schedule (Cron / Intervall in pipeline.json)

Du kannst den Zeitplan **direkt in der pipeline.json** definieren. Beim Start des Orchestrators und nach Git-Sync werden daraus automatisch Scheduler-Jobs angelegt (Quelle: `pipeline_json`). Entweder **Cron** oder **Intervall** angeben, nicht beide. Optionale Start-/Endzeit begrenzen den aktiven Zeitraum.

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `schedule_cron` | String, optional | 5-Teile-Cron (z. B. `"0 9 * * *"` = täglich 09:00). Format: Minute Stunde Tag Monat Wochentag. |
| `schedule_interval_seconds` | Integer, optional | Intervall in Sekunden (z. B. `3600` = stündlich). Entweder dies oder `schedule_cron`. |
| `schedule_start` | String, optional | ISO-Datum/Zeit – Start des Zeitraums, in dem der Schedule läuft (inklusiv). |
| `schedule_end` | String, optional | ISO-Datum/Zeit – Ende des Zeitraums (inklusiv). |

Wenn beide `schedule_cron` und `schedule_interval_seconds` gesetzt sind, hat Cron Vorrang. Ohne `schedule_start`/`schedule_end` läuft der Schedule unbefristet.

**Beispiel:**

```json
{
  "description": "Täglicher Report um 09:00",
  "schedule_cron": "0 9 * * *",
  "schedule_start": "2025-01-01",
  "schedule_end": "2025-12-31T23:59:59"
}
```

### Webhooks

| Feld | Beschreibung |
|------|--------------|
| `webhook_key` | Webhook-Schlüssel (String). Wenn gesetzt und nicht leer: Pipeline per `POST /api/webhooks/{pipeline_name}/{webhook_key}` auslösbar. **Nicht setzen oder leer** = Webhooks deaktiviert. |

### Dokumentation

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `description` | String, optional | Beschreibung, wird in der UI angezeigt. |
| `tags` | Array[String], optional | Tags für Kategorisierung/Filterung. |

### Environment-Variablen

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `default_env` | Object, optional | Default-Env-Vars bei jedem Run. Werden mit UI-Env-Vars zusammengeführt (UI hat Vorrang). **Secrets nicht hier** – über [Secrets-Management](/docs/deployment/CONFIGURATION) in der UI. |

### Retry-Strategien

`retry_strategy` steuert, **wie lange** vor jedem erneuten Versuch gewartet wird. Ohne `retry_strategy` gilt ein fester Standardabstand (z.B. 60 s).

| `type` | Zusatzfelder | Beschreibung |
|--------|--------------|--------------|
| `exponential_backoff` | `initial_delay`, `max_delay`, `multiplier` | Wartezeit wächst: `initial_delay * (multiplier ^ Versuch)`, begrenzt auf `max_delay`. Geeignet für instabile APIs. |
| `fixed_delay` | `delay` | Immer dieselbe Wartezeit (Sekunden). Geeignet für interne Dienste. |
| `custom_schedule` | `delays` | Liste von Wartezeiten in Sekunden, ein Wert pro Retry (z.B. `[60, 300, 3600]`). |

**Beispiel: Exponential Backoff**

```json
{
  "retry_attempts": 3,
  "retry_strategy": {
    "type": "exponential_backoff",
    "initial_delay": 60,
    "max_delay": 3600,
    "multiplier": 2.0
  }
}
```

**Beispiel: Fixed Delay**

```json
{
  "retry_attempts": 3,
  "retry_strategy": {
    "type": "fixed_delay",
    "delay": 120
  }
}
```

**Beispiel: Custom Schedule**

```json
{
  "retry_attempts": 3,
  "retry_strategy": {
    "type": "custom_schedule",
    "delays": [60, 300, 3600]
  }
}
```

---

## Webhooks: Pipeline per HTTP auslösen

Wenn `webhook_key` in `pipeline.json` gesetzt ist, kann die Pipeline per **HTTP POST** getriggert werden:

- **Endpoint:** `POST /api/webhooks/{pipeline_name}/{webhook_key}`
- **Body:** optional (z.B. `{}` oder leer). Ein Body mit `{"webhook_key": "..."}` ist **nicht** nötig – der Schlüssel steht im Pfad.
- **Antwort:** 200 mit Run-Infos; 401 bei falschem Key, 404 wenn Pipeline nicht existiert oder Webhooks deaktiviert.

Beispiel:

```bash
curl -X POST "https://deine-instanz.de/api/webhooks/data_sync/mein-geheimer-key"
```

Die Webhook-URL (mit deinem Schlüssel) wird in der Pipeline-Detailansicht der UI angezeigt und kann dort kopiert werden. **`webhook_key` geheim halten** – jeder mit der URL kann die Pipeline starten.

---

## Verhalten

- **Hard Limits:** Werden als Docker-Limits gesetzt.  
  - Memory-Überschreitung → OOM-Kill (Exit-Code 137).  
  - CPU → Throttling.
- **Soft Limits:** Nur Überwachung, keine Limitierung; Überschreitung erscheint im Frontend als Warnung.
- **Fehlende Metadaten:** Globale/Standard-Limits werden genutzt (falls konfiguriert).
- **Timeout & Retry:** Pipeline-Werte überschreiben die globale Konfiguration.

## Minimales Beispiel

```json
{
  "cpu_hard_limit": 2.0,
  "mem_hard_limit": "2g",
  "cpu_soft_limit": 1.5,
  "mem_soft_limit": "1.5g"
}
```

## Siehe auch

- [Pipelines – Übersicht](/docs/pipelines/uebersicht)
- [Notebook-Pipelines](/docs/pipelines/notebook-pipelines) – `type: "notebook"`, `cells`, Zellen-Retries, Logs pro Zelle
- [Erweiterte Pipelines](/docs/pipelines/erweiterte-pipelines) – Webhooks, Best Practices
- [API](/docs/api/api) – Webhook-Endpoint `POST /api/webhooks/{pipeline_name}/{webhook_key}`
- [Konfiguration](/docs/deployment/CONFIGURATION) – globale Limits, `CONTAINER_TIMEOUT`, `RETRY_ATTEMPTS`
