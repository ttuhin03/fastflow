---
sidebar_position: 6
---

# Abhängigkeiten und Sicherheitsprüfung

Fast-Flow zeigt alle **Libraries und Versionen** pro Pipeline (aus `requirements.txt` und optional `requirements.txt.lock`) und kann **automatisch auf bekannte Schwachstellen (CVE)** prüfen. Bei Fund: **E-Mail- und/oder Teams-Benachrichtigung**.

## Abhängigkeiten-Seite im Frontend

![Abhängigkeiten – Pipelines, Pakete, Sicherheitsprüfung](../img/pipelines-abhaengigkeiten.png)

Unter **Abhängigkeiten** in der Navigation siehst du:

- **Alle Pipelines mit requirements.txt** – pro Pipeline die Liste der Pakete inkl. Version (aus Lock-Datei, falls vorhanden).
- **Sicherheitsprüfung (pip-audit)** – Button **„Sicherheitsprüfung ausführen“** startet einen Scan mit [pip-audit](https://github.com/pypa/pip-audit) pro Pipeline. Gefundene CVE werden angezeigt; Links führen zu NVD (National Vulnerability Database).

Filter:

- **Pipeline** – nur eine bestimmte Pipeline anzeigen.
- **Nur mit Schwachstellen** – nur Pipelines mit gefundenen CVE.
- **Paket suchen** – Paketname filtern.

:::tip
Die Sicherheitsprüfung nutzt **pip-audit** und muss im Backend installiert sein (`pip install pip-audit` bzw. in `requirements.txt`). Fehlt pip-audit, wird ein Hinweis angezeigt; die Paketliste wird trotzdem angezeigt.
:::

## Automatische Sicherheitsprüfung (täglich)

Du kannst eine **tägliche Prüfung** einrichten, die nachts läuft und **nur bei Fund** E-Mail bzw. Teams benachrichtigt.

### Einstellungen (nur für Admins)

Unter **Einstellungen** → Bereich **„Abhängigkeiten – automatische Sicherheitsprüfung“**:

| Einstellung | Beschreibung |
|-------------|--------------|
| **Automatische Sicherheitsprüfung (täglich in der Nacht)** | Aktiviert/Deaktiviert den geplanten Job. |
| **Zeitpunkt (Cron)** | Cron-Ausdruck mit 5 Feldern: **Minute Stunde Tag Monat Wochentag**. Standard: `0 3 * * *` = täglich um 3:00 Uhr. |

Die Werte werden in der Datenbank (SystemSettings) gespeichert und beim App-Start sowie nach Speichern der Einstellungen für den Scheduler übernommen.

### Ablauf

1. Zur konfigurierten Zeit führt der Scheduler **pip-audit** für jede Pipeline mit `requirements.txt` aus.
2. Werden **Schwachstellen gefunden**: Es werden **E-Mail** (an die unter Einstellungen konfigurierten Empfänger) und/oder **Microsoft Teams** (an den konfigurierten Webhook) gesendet – dieselben Kanäle wie bei Pipeline-Fehlern und S3-Backup-Fehlern.
3. Werden **keine** Schwachstellen gefunden: Es erfolgt **keine** Benachrichtigung.

:::important
**Benachrichtigungen** nutzen die bestehende Konfiguration unter Einstellungen (E-Mail: SMTP, Empfänger; Teams: Webhook-URL). Diese müssen korrekt eingerichtet sein, damit du bei Schwachstellen informiert wirst.
:::

### Cron-Beispiele

| Cron | Bedeutung |
|------|-----------|
| `0 3 * * *` | Täglich um 3:00 Uhr (Standard) |
| `0 2 * * *` | Täglich um 2:00 Uhr |
| `30 4 * * *` | Täglich um 4:30 Uhr |
| `0 0 * * 0` | Sonntags um Mitternacht |

Format: Minute (0–59), Stunde (0–23), Tag des Monats (1–31), Monat (1–12), Wochentag (0–6, 0 = Sonntag). `*` = jeden.

## Technik (Backend)

- **Parsing:** `requirements.txt` und optional `requirements.txt.lock` (uv-Format) werden gelesen; Paketnamen und aufgelöste Versionen werden angezeigt.
- **Scan:** [pip-audit](https://github.com/pypa/pip-audit) wird pro Pipeline mit `-r requirements.txt -f json` ausgeführt; das Ergebnis wird für die API und die Benachrichtigung ausgewertet.
- **Job:** Der geplante Job ist im APScheduler mit fester ID (`dependency_audit_job`) registriert; bei Änderung von Aktivierung oder Cron wird er neu geplant (nach Speichern der System-Einstellungen oder beim App-Start).

Weitere Details zur Konfiguration von E-Mail und Teams: [Konfiguration (Deployment)](/docs/deployment/CONFIGURATION.md).
