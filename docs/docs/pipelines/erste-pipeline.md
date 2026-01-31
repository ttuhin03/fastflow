---
sidebar_position: 2
---

# Erste Pipeline schreiben

**~10 Min.** – Dieses Tutorial führt dich von null bis zur ersten lauffähigen Pipeline – mit Erklärungen zu jedem Schritt. Du brauchst ein laufendes Fast-Flow (siehe [Schnellstart](/docs/schnellstart) oder [Setup-Anleitung](/docs/setup)).

---

## Was ist eine Pipeline in Fast-Flow?

Eine **Pipeline** ist im Kern ein **Python-Skript** in einem eigenen Ordner. Fast-Flow:

- erkennt den Ordner automatisch (sobald er unter `PIPELINES_DIR` liegt oder per Git-Sync reinkommt),
- startet das Skript in einem **isolierten Docker-Container**,
- zeigt dir **Logs und Status** in der Oberfläche.

Du musst keine DAGs, Operatoren oder speziellen Frameworks lernen. Wenn das Skript lokal mit `python main.py` (bzw. `uv run main.py`) läuft, läuft es auch in Fast-Flow – vorausgesetzt, du nutzt eine `requirements.txt` für externe Pakete.

---

## Schritt 1: Ordner und `main.py` anlegen

### Wo liegen die Pipelines?

Der Standardpfad ist `./pipelines` (relativ zum Fast-Flow-Projektroot). Bei Docker wird dieser Ordner in der Regel per Volume eingebunden; in `docker-compose.yaml` siehst du, welcher Host-Pfad verwendet wird.

**Wichtig:** Der **Ordnername** = **Pipeline-Name** in der UI. Beispiel: `pipelines/hello_world/` → die Pipeline heißt `hello_world`.

### Minimale Struktur

Jede Pipeline braucht eine Datei **`main.py`** in ihrem Ordner. Alles andere ist optional.

Lege an:

```
pipelines/hello_world/main.py
```

Inhalt von `main.py`:

```python
# main.py
print("Hallo von Fast-Flow!")
```

Du kannst den Code **von oben nach unten** schreiben. Eine `main()`-Funktion oder `if __name__ == "__main__"` ist **nicht** nötig, aber erlaubt.

---

## Schritt 2: Pipeline in der UI sehen und starten

### Synchronisation

- **Lokales `pipelines/`-Verzeichnis:** Wenn du den Ordner direkt unter `PIPELINES_DIR` anlegst, erscheint die Pipeline nach dem nächsten **Sync** oder beim **Neustart** des Orchestrators. Bei einigen Setups wird beim Start automatisch gescannt.
- **Git-Sync:** Wenn Pipelines aus einem Git-Repo kommen, musst du einen **manuellen Sync** auslösen (UI: Sync/Repository) oder auf den nächsten Auto-Sync warten.

### In der UI

1. Öffne die Fast-Flow-Oberfläche (z.B. http://localhost:8000) und melde dich an.
2. Gehe zu **Pipelines**. Dort solltest du **`hello_world`** sehen.
3. Klicke auf **Run** (oder „Ausführen“), um die Pipeline einmalig zu starten.
4. Öffne den **Run** und schau dir die **Logs** an – dort steht `Hallo von Fast-Flow!`.

**Farben/Status:**  
- **RUNNING** = läuft gerade  
- **SUCCESS** = beendet mit Exit-Code 0  
- **FAILED** = Fehler (z.B. Exception oder Exit-Code ≠ 0)

---

## Schritt 3: Externe Pakete – `requirements.txt`

Sobald du Bibliotheken wie `requests`, `pandas` oder `numpy` brauchst, legst du im **gleichen Pipeline-Ordner** eine `requirements.txt` an – wie bei einem normalen Python-Projekt.

### Beispiel

```
pipelines/hello_world/
├── main.py
└── requirements.txt
```

Inhalt `requirements.txt`:

```
requests==2.31.0
```

Inhalt `main.py`:

```python
# main.py
import requests
print("Hallo von Fast-Flow!")
r = requests.get("https://httpbin.org/get")
print("Status:", r.status_code)
```

### Was passiert damit?

- Fast-Flow führt die Pipeline mit **`uv`** aus. `uv` liest die `requirements.txt` und stellt die Pakete bereit.
- Beim **ersten** Run können die Pakete kurz laden; danach landen sie im **gemeinsamen uv-Cache**. Weitere Runs sind oft in unter einer Sekunde startklar.
- Wenn du **Git-Sync** mit `UV_PRE_HEAT=true` nutzt, werden Abhängigkeiten beim Sync schon vorgeladen.

**Format:** Standard-`requirements.txt` (z.B. `paket==1.2.3` oder `paket>=1.0`).

---

## Schritt 4: Metadaten – `pipeline.json` (optional)

Mit einer `pipeline.json` (oder `{pipeline_name}.json`, z.B. `hello_world.json`) kannst du:

- eine **Beschreibung** angeben (wird in der UI angezeigt),
- **Ressourcen-Limits** (CPU, RAM) setzen,
- **Timeout** und **Retries** konfigurieren,
- die **Python-Version** setzen (`python_version`, z.B. `"3.12"`) – **beliebig pro Pipeline**, jede Pipeline kann 3.10, 3.11, 3.12 o. Ä. nutzen; fehlt es, gilt `DEFAULT_PYTHON_VERSION`,
- **Tags** vergeben.

### Einfaches Beispiel

`pipelines/hello_world/pipeline.json`:

```json
{
  "description": "Meine erste Pipeline – sagt Hallo und prüft httpbin.",
  "tags": ["tutorial", "test"]
}
```

Nach dem nächsten Sync erscheint die Beschreibung in der Pipeline-Liste. Eine vollständige Referenz aller Felder: [pipeline.json Referenz](/docs/pipelines/referenz).

---

## Schritt 5: Secrets und Umgebungsvariablen

Passwörter, API-Keys usw. gehören **nicht** in den Code und **nicht** in `pipeline.json`. Du trägst sie in der Fast-Flow-UI als **Secrets** (oder Parameter) ein; sie werden **verschlüsselt** gespeichert und der Pipeline beim Lauf als **Umgebungsvariablen** übergeben.

### In der UI

1. Gehe zu **Pipelines** → wähle `hello_world` (oder die entsprechende Pipeline).
2. Öffne den Bereich **Secrets** / **Parameter** (je nach UI-Benennung).
3. Lege z.B. ein Secret **`MEIN_API_KEY`** an und trage einen Wert ein (nur fürs Tutorial: `test-123`).

### Im Code

In `main.py` liest du Umgebungsvariablen mit `os.getenv`:

```python
# main.py
import os

api_key = os.getenv("MEIN_API_KEY")
if api_key:
    print("API-Key ist gesetzt (Länge):", len(api_key))
else:
    print("MEIN_API_KEY nicht gesetzt – bitte in der UI eintragen.")
```

Beim Start des Runs setzt Fast-Flow die in der UI konfigurierten Secrets/Parameter als Env-Vars. **Parameter** sind unverschlüsselt (für nicht sensible Werte), **Secrets** werden verschlüsselt gespeichert.

---

## Schritt 6: Fehler und Logs

- **Unbehandelte Exception** → Python beendet mit Exit-Code ≠ 0 → Run wird **FAILED**.
- **`print`-Ausgaben** erscheinen in den **Logs** des Runs. Nutze Logs für Debugging.
- Wenn ein **Import** fehlschlägt (z.B. Paket fehlt in `requirements.txt`), steht die Fehlermeldung in den Logs.

### Beispiel mit Fehlerbehandlung

```python
# main.py
import sys

def main():
    print("Starte ...")
    # ... deine Logik ...
    print("Fertig.")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("Fehler:", e, file=sys.stderr)
        sys.exit(1)
```

`sys.exit(0)` = Erfolg, `sys.exit(1)` (oder anderer Wert ≠ 0) = Fehler. Fast-Flow wertet den Exit-Code aus.

---

## Lokal testen (ohne UI)

Du kannst die Pipeline lokal **genau so** ausführen wie im Container – mit **`uv`** (oder `pip` + `python`):

```bash
cd pipelines/hello_world
uv run --with-requirements requirements.txt main.py
```

Falls keine `requirements.txt` existiert: `uv run main.py`. Alternative: `pip install -r requirements.txt` und `python main.py`.

:::important „If it runs, it runs“
**Wenn das Skript so lokal durchläuft, läuft es auch im Fast-Flow-Orchestrator.** Gleiche Laufzeit (uv), keine eigenen Pipeline-Images. Tritt trotzdem ein Fehler im Orchestrator auf: [Troubleshooting](/docs/troubleshooting#pipeline-lokal-orchestrator-fehlt).
:::

So findest du viele Fehler schon vor dem ersten Run in Fast-Flow.

---

## Kurz-Checkliste: Erste Pipeline

- [ ] Ordner unter `PIPELINES_DIR` (z.B. `pipelines/mein_name/`) mit **`main.py`**
- [ ] Optional: **`requirements.txt`** für externe Pakete
- [ ] Optional: **`pipeline.json`** für Beschreibung, Tags, Limits
- [ ] Secrets/Parameter in der **UI** anlegen und in `main.py` mit **`os.getenv("NAME")`** lesen
- [ ] Nach Sync/Neustart Pipeline in der UI prüfen und **Run** starten
- [ ] **Logs** ansehen bei Erfolg und bei Fehlern

---

## Nächste Schritte

- [**Pipelines – Übersicht**](/docs/pipelines/uebersicht) – Verzeichnisstruktur, Erkennung, alle Dateitypen
- [**Erweiterte Pipelines**](/docs/pipelines/erweiterte-pipelines) – Retries, Timeout, Scheduling, Webhooks, Struktur
- [**pipeline.json Referenz**](/docs/pipelines/referenz) – Alle Felder für Metadaten und Limits
