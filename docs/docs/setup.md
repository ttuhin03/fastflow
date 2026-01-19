---
sidebar_position: 3
---

# Setup-Anleitung

Diese Anleitung führt dich Schritt für Schritt durch das Aufsetzen von Fast-Flow – inklusive der wichtigsten Umgebungsvariablen und was sie bewirken.

## Für wen ist diese Anleitung?

- Du willst Fast-Flow das erste Mal zum Laufen bringen.
- Du möchtest verstehen, **warum** bestimmte Einstellungen nötig sind – nicht nur, **dass** sie gesetzt werden müssen.
- Du planst einen Produktionseinsatz und brauchst eine Checkliste.

Für die vollständige Referenz aller Variablen siehe [Konfiguration](/docs/deployment/CONFIGURATION).

---

## Übersicht: Was du brauchst

| Voraussetzung | Wofür |
|---------------|--------|
| **Docker & Docker Compose** | Zum Starten des Orchestrators und der Pipeline-Container. |
| **Python 3.11+** | Nur für lokale Entwicklung (z.B. `uvicorn`, `pip`, Key-Generierung). |
| **Git** | Falls du Pipelines aus einem Repository synchronisierst (optional, sonst lokales Verzeichnis). |

---

## 1. Projekt vorbereiten

### 1.1 Repository klonen (falls noch nicht geschehen)

```bash
git clone https://github.com/ttuhin03/fastflow.git
cd fastflow
```

### 1.2 `.env` aus der Vorlage anlegen

Fast-Flow liest Konfiguration aus einer `.env` Datei im Projektroot. Die Datei wird **nicht** ins Git übernommen (steht in `.gitignore`).

```bash
cp .env.example .env
```

Öffne `.env` in einem Editor – die meisten Zeilen sind auskommentiert (`#`). Du wirst nur einen Teil davon aktiv setzen müssen.

---

## 2. Pflicht-Variablen: Sicherheit & Start

Ohne diese Werte startet die Anwendung nicht oder blockiert den Start in Produktion.

### 2.1 `ENCRYPTION_KEY` (unbedingt setzen)

**Was es ist:** Ein symmetrischer Schlüssel (Fernet) zum Verschlüsseln von **Secrets** in der Datenbank (API-Keys, Passwörter, die du in der UI einträgst).

**Warum wichtig:** Ohne diesen Key können Secrets nicht sicher gespeichert werden. Die App verweigert den Start.

**So erzeugen:**

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Es erscheint eine Zeichenkette wie `xYz123...=`. Diese **komplett** in `.env` eintragen:

```
ENCRYPTION_KEY=xYz123...=
```

**Tipp:** Den Key sicher aufbewahren. Bei Verlust sind bestehende Secrets in der DB nicht mehr entschlüsselbar.

---

### 2.2 `JWT_SECRET_KEY` (in Produktion Pflicht)

**Was es ist:** Ein geheimer Wert, mit dem die App **JWT-Tokens** (für eingeloggte User) signiert. Er muss lang und zufällig sein.

**Warum wichtig:** Wer den Key kennt, kann gefälschte Login-Tokens erzeugen. In `ENVIRONMENT=production` wird der Standardwert `change-me-in-production` abgelehnt.

**Lokal/Entwicklung:** Der Wert aus `.env.example` reicht zum Testen.

**Produktion:** Mindestens 32 Zeichen, zufällig. Beispiele zum Erzeugen:

```bash
openssl rand -base64 32
# oder
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

In `.env`:

```
JWT_SECRET_KEY=dein-langer-zufaelliger-string
```

---

### 2.3 OAuth: Mindestens ein Login-Provider

Fast-Flow hat **kein** klassisches Passwort-Login. Der Zugriff läuft über **GitHub OAuth** und/oder **Google OAuth**. Es muss **mindestens ein** Provider vollständig konfiguriert sein (jeweils `CLIENT_ID` und `CLIENT_SECRET`), sonst startet die App nicht.

#### GitHub OAuth

**Was du brauchst:** Eine OAuth-App auf GitHub.

1. GitHub → **Settings** (dein Profil) → **Developer settings** → **OAuth Apps** → **New OAuth App**.
2. **Authorization callback URL** setzen auf:  
   `http://localhost:8000/api/auth/github/callback` (lokal mit Docker, alles auf :8000)  
   bzw. `https://deine-domain.de/api/auth/github/callback` in Produktion.
3. **Client ID** und **Client Secret** kopieren.

In `.env` (Zeilen auskommentieren = `#` entfernen und Werte eintragen):

```
GITHUB_CLIENT_ID=deine-client-id
GITHUB_CLIENT_SECRET=dein-client-secret
```

**Wichtig:** Die Callback-URL muss **exakt** zu `BASE_URL` passen (siehe unten). Sonst schlägt der OAuth-Flow fehl.

#### Google OAuth

1. [Google Cloud Console](https://console.cloud.google.com/) → **APIs & Services** → **Anmeldedaten** → **OAuth 2.0-Client-IDs**.
2. **Authorisierte Weiterleitungs-URIs** hinzufügen:  
   `http://localhost:8000/api/auth/google/callback` (lokal) bzw. `https://deine-domain.de/api/auth/google/callback` (Produktion).
3. **Client-ID** und **Client-Secret** eintragen.

In `.env`:

```
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
```

Ausführliche Schritte: [OAuth (GitHub & Google)](/docs/oauth/readme).

---

### 2.4 `INITIAL_ADMIN_EMAIL` (stark empfohlen)

**Was es ist:** Die E-Mail-Adresse des **ersten Admins**. Der User, der sich mit dieser E-Mail über GitHub oder Google anmeldet, erhält beim ersten Login automatisch die Admin-Rolle – **ohne** vorherige Einladung.

**Warum wichtig:** Ohne Admin kann niemand andere User einladen oder Einstellungen ändern. Mit `INITIAL_ADMIN_EMAIL` hast du sofort einen Admin.

```
INITIAL_ADMIN_EMAIL=deine-email@beispiel.de
```

Die E-Mail muss mit der Adresse übereinstimmen, die dein OAuth-Provider (GitHub/Google) für dein Konto zurückgibt.

---

### 2.5 `BASE_URL` und `FRONTEND_URL`

**BASE_URL:** Die öffentlich erreichbare URL des **Backends** (API). Wird für OAuth-Callbacks und Links in E-Mails genutzt. **Kein** nachgestelltes `/`.

**FRONTEND_URL:** Die URL des **Frontends**, falls es getrennt läuft (z.B. bei lokaler Entwicklung: Frontend auf :3000, Backend auf :8000). Wenn Frontend und Backend gemeinsam auf einer URL laufen (z.B. alles :8000), kann `FRONTEND_URL` weggelassen oder gleich `BASE_URL` gesetzt werden.

**Typische Fälle:**

| Szenario | BASE_URL | FRONTEND_URL |
|----------|----------|--------------|
| Docker, alles auf Port 8000 | `http://localhost:8000` | weglassen oder `http://localhost:8000` |
| Lokal: Frontend :3000, Backend :8000 | `http://localhost:8000` | `http://localhost:3000` |
| Produktion, eine Domain | `https://fastflow.example.com` | weglassen oder identisch |

**Fehlerquelle:** Wenn `BASE_URL` nicht exakt der aufgerufenen URL entspricht (inkl. `http`/`https`, Port), funktioniert der OAuth-Redirect nicht.

---

## 3. Wichtige optionale Variablen

### 3.1 `ENVIRONMENT`

- `development`: Lockere Sicherheitsprüfungen, Debug-Infos. Für lokales Arbeiten.
- `production`: Strenge Prüfungen (z.B. `JWT_SECRET_KEY` darf nicht der Default sein). Für den Live-Betrieb.

```
ENVIRONMENT=development
```

Für Produktion: `ENVIRONMENT=production`.

---

### 3.2 `PIPELINES_DIR`

**Was es ist:** Der Pfad zum Verzeichnis, in dem deine Pipeline-Ordner liegen (jeder mit `main.py`).

**Standard:** `./pipelines`

**Wann anpassen:** Wenn du ein anderes Verzeichnis oder ein geklontes Git-Repo nutzt. Bei Docker: Der Pfad ist **im Container**; über `docker-compose` wird typischerweise ein Host-Ordner gemountet (siehe `docker-compose.yaml`).

```
PIPELINES_DIR=./pipelines
```

---

### 3.3 `DATABASE_URL`

**Standard:** Leer → es wird **SQLite** verwendet (`./data/fastflow.db`).

**Produktion / Team:** Oft **PostgreSQL** für bessere Concurrency und Backup-Optionen.

```
# SQLite (Default, nichts setzen oder leer lassen)
# DATABASE_URL=

# PostgreSQL
DATABASE_URL=postgresql://user:password@host:5432/fastflow
```

---

### 3.4 `UV_CACHE_DIR`

**Was es ist:** Der globale Cache für **uv** (Python-Paketmanager). Alle Pipeline-Container teilen sich diesen Cache; schon geladene Pakete werden nicht erneut heruntergeladen.

**Standard:** `./data/uv_cache`

**Wann anpassen:** Nur, wenn du einen anderen Ort für den Cache haben möchtest (z.B. größere Festplatte). Für den Einstieg reicht der Default.

---

### 3.5 `UV_PRE_HEAT`

**Was es ist:** `true` oder `false`. Wenn `true`, werden beim **Git-Sync** die in `requirements.txt` genannten Pakete schon mal geladen („vorgewärmt“). Beim ersten Pipeline-Run sind sie dann oft sofort aus dem Cache da.

**Empfehlung:** `true` lassen.

```
UV_PRE_HEAT=true
```

---

### 3.6 Git-Sync (wenn Pipelines aus einem Repo kommen)

| Variable | Bedeutung | typischer Wert |
|----------|-----------|----------------|
| `GIT_BRANCH` | Branch, der synchronisiert wird | `main` |
| `AUTO_SYNC_ENABLED` | Automatischer Sync an/aus | `false` oder `true` |
| `AUTO_SYNC_INTERVAL` | Intervall in Sekunden | z.B. `300` |

Zusätzlich: Repo-URL und ggf. GitHub App oder Zugangsdaten (siehe [Konfiguration](/docs/deployment/CONFIGURATION), GitHub Apps).

---

## 4. Fast-Flow starten

### Mit Docker (empfohlen für Produktion und einfachen Einstieg)

```bash
docker-compose up -d
```

Logs prüfen:

```bash
docker-compose logs -f orchestrator
```

Die UI ist unter **http://localhost:8000** (bzw. unter der in `BASE_URL` konfigurierten Adresse).

### Lokal (für Entwicklung)

Zwei Terminals:

**Terminal 1 – Backend:**

```bash
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

**Terminal 2 – Frontend:**

```bash
cd frontend
npm install
npm run dev
```

Dann: Frontend meist unter **http://localhost:3000**, Backend unter **http://localhost:8000**. `FRONTEND_URL` und `BASE_URL` wie in der Tabelle oben setzen.

---

## 5. Nach dem Start

1. **Ersten Login:** Mit GitHub oder Google anmelden. Die in `INITIAL_ADMIN_EMAIL` hinterlegte E-Mail wird beim ersten Mal zum Admin.
2. **Pipelines:** Entweder Ordner unter `PIPELINES_DIR` anlegen (z.B. `pipelines/meine_erste/main.py`) oder Git-Sync einrichten. Siehe [Erste Pipeline](/docs/pipelines/erste-pipeline) und [Pipelines – Übersicht](/docs/pipelines/uebersicht).
3. **Secrets:** In der UI unter Pipelines → Secrets/Parameter eintragen. In der Pipeline über `os.getenv("NAME")` nutzbar.

---

## 6. Checkliste Produktion

- [ ] `ENVIRONMENT=production`
- [ ] `ENCRYPTION_KEY` und `JWT_SECRET_KEY` neu und sicher erzeugt, nicht die Beispiele aus der Doku
- [ ] OAuth (GitHub und/oder Google) mit **Produktions**-Callback-URLs
- [ ] `BASE_URL` und ggf. `FRONTEND_URL` mit **https** und der echten Domain
- [ ] HTTPS (z.B. Reverse-Proxy wie Nginx) – [Deployment-Guide](/docs/deployment/PRODUCTION)
- [ ] `DATABASE_URL` für PostgreSQL gesetzt (empfohlen)
- [ ] Backups für Datenbank und `.env` eingeplant

---

## Siehe auch

- [Konfiguration](/docs/deployment/CONFIGURATION) – alle Umgebungsvariablen im Überblick
- [OAuth (GitHub & Google)](/docs/oauth/readme) – detaillierte OAuth-Einrichtung
- [Schnellstart](/docs/schnellstart) – kompakte Version ohne Erklärungen
- [Troubleshooting](/docs/troubleshooting) – wenn etwas nicht startet
