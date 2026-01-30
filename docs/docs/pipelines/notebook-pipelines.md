---
sidebar_position: 4
---

# Notebook-Pipelines (Jupyter)

Neben klassischen Python-Skripten (`main.py`) unterstützt Fast-Flow **Notebook-Pipelines**: Eine Pipeline wird als **Jupyter-Notebook** (`main.ipynb`) ausgeführt. Die Zellen laufen nacheinander; pro **Code-Zelle** kannst du **Retries** konfigurieren. Logs und Fehler siehst du **pro Zelle** in der Run-Detail-Ansicht – inklusive aller Retry-Versuche bei fehlgeschlagenen Zellen.

---

## Wann Notebook-Pipelines nutzen?

| Szenario | Empfehlung |
|----------|------------|
| **Explorative Auswertung, Prototyping** | Notebook: Zellen einzeln ausführbar, Ausgaben direkt sichtbar. |
| **Reproduzierbare Schritte (ETL, Reports)** | Notebook oder Skript: Beide laufen im Container; Notebook bietet Zellen-Logs und Zellen-Retries. |
| **Strikte Automatisierung, CI/CD** | Oft `main.py`: Ein Einstieg, klare Exit-Codes, weniger Laufzeit-Overhead. |

Notebook-Pipelines eignen sich gut, wenn du **Schritt für Schritt** arbeiten willst, **Zellen-Logs** und **Zellen-Retries** brauchst, oder bestehende Notebooks in Fast-Flow einbinden willst.

---

## Struktur einer Notebook-Pipeline

Eine Notebook-Pipeline wird erkannt, wenn im Pipeline-Ordner **`main.ipynb`** existiert und in der `pipeline.json` der Typ **`"type": "notebook"`** gesetzt ist.

### Minimale Verzeichnisstruktur

```
pipelines/meine_notebook_pipeline/
├── main.ipynb          # Einstieg – wird Zelle für Zelle ausgeführt
├── pipeline.json      # type: "notebook", optional: cells, timeout, …
└── requirements.txt   # nbclient, nbformat, ipykernel (mindestens)
```

### Pflicht in `requirements.txt`

Der Notebook-Runner nutzt **nbclient** und **nbformat**. Diese (und ein Kernel) müssen in der Pipeline-Umgebung verfügbar sein:

```
nbclient
nbformat
ipykernel
```

Ohne diese Pakete schlägt der Start der Notebook-Pipeline fehl.

---

## pipeline.json für Notebook-Pipelines

### Typ setzen

```json
{
  "type": "notebook",
  "enabled": true,
  "description": "Meine Notebook-Pipeline",
  "python_version": "3.12",
  "timeout": 120
}
```

- **`type`: `"notebook"`** – sorgt dafür, dass Fast-Flow `main.ipynb` findet und den Notebook-Runner verwendet (statt `main.py`).
- Alle anderen Felder (z. B. `timeout`, `python_version`, `description`, `tags`) funktionieren wie bei Skript-Pipelines. Siehe [pipeline.json Referenz](/docs/pipelines/referenz).

### Zellen-Retries: Das `cells`-Array

Du kannst **pro Code-Zelle** festlegen, wie oft bei einem Fehler wiederholt werden soll und wie lange zwischen den Versuchen gewartet wird.

**Format:** `cells` ist ein **Array**. Der Eintrag an Index **0** gilt für die **erste Code-Zelle**, Index **1** für die zweite, usw. (Markdown-Zellen zählen nicht – nur **Code-Zellen** werden nummeriert.)

| Feld pro Zelle | Typ | Beschreibung |
|----------------|-----|--------------|
| `retries` | Integer, optional | Anzahl **zusätzlicher** Versuche bei Fehlern (0 = kein Retry). |
| `delay_seconds` | Number, optional | Wartezeit in Sekunden zwischen zwei Versuchen (Standard: 1). |

**Beispiel:** 4 Code-Zellen; die dritte soll bis zu 3 Retries mit 1 Sekunde Pause haben:

```json
{
  "type": "notebook",
  "enabled": true,
  "python_version": "3.12",
  "cells": [
    { "retries": 2, "delay_seconds": 1 },
    { "retries": 0 },
    { "retries": 3, "delay_seconds": 1 },
    { "retries": 1, "delay_seconds": 2 }
  ]
}
```

- Zelle 0 (erste Code-Zelle): 2 Retries, 1 s Pause.
- Zelle 1: keine Retries.
- Zelle 2: 3 Retries, 1 s Pause.
- Zelle 3: 1 Retry, 2 s Pause.

Fehlt ein Eintrag für eine Zelle (oder ist das Array kürzer), gilt für diese Zelle **0 Retries** und **1 s** `delay_seconds`.

---

## Zellen-Metadaten (optional): Überschreiben pro Zelle

Zusätzlich zur `pipeline.json` kannst du **in jeder Zelle** des Notebooks Metadaten setzen. Wenn eine Zelle eigene Retry-Werte hat, **überschreiben** diese die Werte aus der `pipeline.json` für genau diese Zelle.

**Wo:** In Jupyter: Zelle auswählen → Metadaten bearbeiten (oder in der raw JSON-Darstellung der `.ipynb`).

**Format:** In den **Cell-Metadaten** ein Objekt **`fastflow`** mit optional **`retries`** und **`delay_seconds`**:

```json
"metadata": {
  "fastflow": {
    "retries": 3,
    "delay_seconds": 2
  }
}
```

**Zusammenführung:**

1. **Basis:** Werte aus `pipeline.json` → `cells[code_cell_index]` (z. B. `retries: 2`, `delay_seconds: 1`).
2. **Überschreibung:** Wenn die Zelle `metadata.fastflow.retries` oder `metadata.fastflow.delay_seconds` hat, werden **nur diese** Felder für die Zelle verwendet.

So kannst du z. B. in der `pipeline.json` sinnvolle Defaults für alle Zellen setzen und nur für wenige „kritische“ Zellen im Notebook höhere Retries oder längere Pausen vergeben.

---

## Ablauf: Wie wird das Notebook ausgeführt?

1. Fast-Flow startet einen Container mit dem Pipeline-Ordner (u. a. `main.ipynb`, `pipeline.json`, `requirements.txt`).
2. Der **Notebook-Runner** liest `main.ipynb` und `pipeline.json` (inkl. `cells`).
3. **Code-Zellen** werden der Reihe nach ausgeführt (Markdown-Zellen werden übersprungen).
4. Pro Code-Zelle:
   - **Retries** und **delay_seconds** kommen aus `pipeline.json` → `cells[code_cell_index]`, überschrieben durch `metadata.fastflow` der Zelle.
   - Bei **Fehler** (Exception, Timeout, Kernel-Absturz): Warte `delay_seconds`, dann erneuter Versuch, bis `retries` aufgebraucht sind.
   - Wenn nach allen Versuchen weiterhin Fehler: Run endet mit **FAILED**; die Zelle gilt als fehlgeschlagen.
5. **Logs** (stdout, stderr, Zellen-Ausgaben) werden pro Zelle gesammelt und in der Run-Detail-Ansicht angezeigt.

:::important
**Pipeline-Level-Retries** („ganzen Run neu starten“) sind für Notebook-Pipelines **deaktiviert**. Es zählen nur die **Zellen-Retries** innerhalb eines Laufs. So vermeidest du doppelte Retry-Logik und siehst alle Versuche pro Zelle an einem Ort.
:::

---

## Logs und Run-Detail-Ansicht

### Zellen-Logs

- In der **Run-Detail-Ansicht** (Tab **Logs**) siehst du bei Notebook-Pipelines die Ausgaben **gruppiert nach Zelle**.
- Pro Zelle: **stdout**, **stderr**, optional **Bilder** (display_data).
- **Status pro Zelle:** RUNNING, SUCCESS, RETRYING, FAILED.

### Fehlgeschlagene Zelle: Alle Versuche sichtbar

Bei einer Zelle mit Retries werden **alle Fehlerversuche** in **stderr** gesammelt:

- **Retry-Versuch 1 fehlgeschlagen:** &lt;Fehlermeldung&gt;
- **Retry-Versuch 2 fehlgeschlagen:** &lt;Fehlermeldung&gt;
- …
- **Endgültig fehlgeschlagen**

So siehst du in einer fehlgeschlagenen Zelle genau, was bei jedem Versuch schiefgelaufen ist – ohne die Logs mehrerer Runs zusammensuchen zu müssen.

### Log-Datei herunterladen

Der Button **„Download Logs“** lädt die **gesamte Run-Log-Datei** (Text) herunter. Enthalten sind u. a. die lesbaren Zusammenfassungen der Zellen (Start, Erfolg, Retry, Fehlgeschlagen). Bei Fehlern (z. B. Log-Datei nicht vorhanden) erscheint eine klare Fehlermeldung in der UI.

---

## Beispiel: Komplette Notebook-Pipeline

### Verzeichnis

```
pipelines/notebook_example/
├── main.ipynb
├── pipeline.json
└── requirements.txt
```

### `pipeline.json`

```json
{
  "type": "notebook",
  "enabled": true,
  "description": "Beispiel-Notebook mit Zellen-Retries",
  "tags": ["notebook", "example"],
  "python_version": "3.12",
  "timeout": 120,
  "cells": [
    { "retries": 2, "delay_seconds": 1 },
    { "retries": 0 },
    { "retries": 3, "delay_seconds": 1 },
    { "retries": 1, "delay_seconds": 2 }
  ]
}
```

### `requirements.txt`

```
nbclient
nbformat
ipykernel
```

### `main.ipynb` (inhaltlich)

- Zelle 0 (Markdown): Beschreibung.
- Zelle 1 (Code): `import sys`; `print('Python:', sys.version)` – 2 Retries aus `cells[0]`.
- Zelle 2 (Code): Einfache Berechnung – keine Retries aus `cells[1]`.
- Zelle 3 (Code): z. B. `raise Exception('Test-Fehler')` – 3 Retries aus `cells[2]`; nach 4 Versuchen endet die Zelle (und der Run) mit FAILED; alle 4 Fehlermeldungen erscheinen in der Zellen-stderr.
- Zelle 4 (Code): Abschluss-Text – 1 Retry aus `cells[3]`.

So kannst du das Verhalten von Zellen-Retries und die Anzeige aller Versuche in der UI direkt nachvollziehen.

---

## Lokal testen

Notebook lokal ausführen (z. B. in Jupyter oder VS Code): Wie gewohnt.  
Die **Retry-Logik** und die **strukturierten Logs** (FASTFLOW_CELL_*) laufen nur im Fast-Flow-Container; lokal siehst du „normales“ Notebook-Verhalten.

Für einen schnellen Check, ob die Umgebung stimmt:

```bash
cd pipelines/notebook_example
uv pip install -r requirements.txt
jupyter nbconvert --to notebook --execute main.ipynb
```

Wenn das durchläuft, sollte das Notebook auch im Orchestrator laufen – vorausgesetzt, die gleiche Python-Version und Abhängigkeiten werden verwendet (`python_version` in `pipeline.json` beachten).

---

## Kurzreferenz: Was wo konfigurieren?

| Ziel | Wo |
|------|-----|
| **Pipeline als Notebook erkennen** | `pipeline.json`: `"type": "notebook"` + `main.ipynb` im Ordner |
| **Retries pro Zelle (Default)** | `pipeline.json`: `"cells": [ { "retries", "delay_seconds" }, … ]` |
| **Retries für eine Zelle überschreiben** | In der Zelle: Cell-Metadaten → `fastflow`: `retries`, `delay_seconds` |
| **Timeout, Python-Version, Beschreibung** | Wie bei Skript-Pipelines in `pipeline.json` |
| **Logs pro Zelle + alle Retry-Versuche** | Run-Detail → Tab Logs (Zellen gruppiert); stderr einer fehlgeschlagenen Zelle enthält alle Versuche |
| **Gesamte Log-Datei** | Run-Detail → Tab Logs → Button „Download Logs“ |

---

## Siehe auch

- [pipeline.json Referenz](/docs/pipelines/referenz) – Felder `type` und `cells`, alle anderen Optionen
- [Pipelines – Übersicht](/docs/pipelines/uebersicht) – Grundstruktur, Skript vs. Notebook
- [Erweiterte Pipelines](/docs/pipelines/erweiterte-pipelines) – Retries, Timeout, Webhooks (für Pipeline-Ebene; bei Notebooks gelten Zellen-Retries wie oben)
