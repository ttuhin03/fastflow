# GitHub OAuth + Einladung

Anleitung zum Einrichten und Testen von GitHub-Login und Einladungs-Flow.

---

## 1. GitHub OAuth App anlegen

1. **GitHub** → **Settings** (dein Profil) → **Developer settings** → **OAuth Apps** → **New OAuth App**
2. Ausfüllen:
   - **Application name:** z.B. `Fast-Flow (lokal)`
   - **Homepage URL:** `http://localhost:3000` (oder deine Frontend-URL)
   - **Authorization callback URL:** `http://localhost:8000/api/auth/github/callback`
3. **Register application** → **Generate a new client secret**
4. **Client ID** und **Client Secret** kopieren (Secret nur einmal sichtbar).

---

## 2. .env vorbereiten

```bash
# .env aus Beispiel anlegen (falls noch nicht vorhanden)
cp .env.example .env

# ENCRYPTION_KEY erzeugen und in .env eintragen
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

In `.env` mindestens setzen:

```env
# Pflicht
ENCRYPTION_KEY=<Output-vom-Fernet-Befehl>

# GitHub OAuth (aus Schritt 1)
GITHUB_CLIENT_ID=<deine-Client-ID>
GITHUB_CLIENT_SECRET=<dein-Client-Secret>

# E-Mail deines GitHub-Accounts → wird erster Admin
INITIAL_ADMIN_EMAIL=deine-github-email@beispiel.de

# Für OAuth-Callback und Einladungs-Links:
# - Ein Container (orchestrator auf :8000 serviert alles): FRONTEND_URL weglassen oder =http://localhost:8000, BASE_URL=http://localhost:8000
# - Dev (Frontend :3000, API :8000): FRONTEND_URL=http://localhost:3000, BASE_URL=http://localhost:8000
# Wenn FRONTEND_URL fehlt, wird BASE_URL verwendet.
FRONTEND_URL=http://localhost:3000
BASE_URL=http://localhost:8000
```

---

## 3. Backend + Frontend starten

### Option A: Docker (start-docker.sh / start-dev.sh)

```bash
./start-docker.sh   # Produktions-Setup (Alles auf :8000)
# oder
./start-dev.sh      # Dev: Frontend :3000, Backend :8000
```

### Option B: Docker manuell

```bash
mkdir -p pipelines logs data data/uv_cache
docker-compose up --build
# bzw. docker-compose -f docker-compose.dev.yaml up --build für Dev
```

### Option C: Lokal (Backend + Frontend getrennt)

**Backend:**

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend (anderes Terminal):**

```bash
cd frontend && npm install && npm run dev
```

---

## 4. Test-Szenarien

### A) Erster Login (INITIAL_ADMIN_EMAIL)

1. App öffnen (z.B. **http://localhost:8000** oder **http://localhost:3000**) → Redirect zu `/login`
2. **„Login mit GitHub“** klicken
3. Auf GitHub anmelden/Authorisieren
4. Redirect zu `/auth/callback#token=…` → dann zu **/** (Dashboard)
5. Prüfen: oben rechts eingeloggt, Nutzerverwaltung (Users) als Admin sichtbar

**Hinweis:** Funktioniert nur, wenn die bei GitHub hinterlegte (primäre) E-Mail **exakt** `INITIAL_ADMIN_EMAIL` entspricht.

---

### B) Einladung erstellen und einlösen

1. Als Admin (aus A) einloggen
2. **Users** → **„Einladung senden“**
   - E-Mail: eine **andere** GitHub-E-Mail (nicht `INITIAL_ADMIN_EMAIL`)
   - Rolle: z.B. Readonly
   - Gültig: z.B. 168 h
3. **Einladung erstellen** → Link wird in die Zwischenablage kopiert  
   Format: `http://…/invite?token=…`
4. Im selben oder anderen Browser/Profil: Link öffnen (oder Incognito)
5. **„Mit GitHub registrieren“** klicken → GitHub OAuth → Redirect mit `#token=…` → zu **/**
6. Prüfen: neuer User in **Users**, Einladung in der Liste als **Eingelöst**

---

### C) Einladungsliste und Widerruf

1. Als Admin: **Users** → Bereich **„Einladungen“**
2. Prüfen: E-Mail, Erstellt, Läuft ab, Status (Offen / Eingelöst)
3. Bei **offener** Einladung: **Widerrufen** (Mülleimer) → Eintrag verschwindet, Link ist ungültig

---

### D) Abgelaufener Einladungslink (403)

1. Einladung erstellen, Link kopieren
2. In der DB `expires_at` in die Vergangenheit setzen (oder 1 h Gültigkeit wählen und warten)
3. Link öffnen → **„Mit GitHub registrieren“** → nach GitHub und zurück
4. Erwartung: **403** „Zutritt verweigert. Keine gültige Einladung gefunden.“

---

## 5. Nützliche Befehle

```bash
# Logs (Docker)
docker-compose logs -f orchestrator

# API Health (Backend läuft?)
curl -s http://localhost:8000/health

# OAuth-Start manuell prüfen (Redirect zu GitHub)
curl -sI "http://localhost:8000/api/auth/github/authorize"
# Erwartung: 302, Location: https://github.com/login/oauth/authorize?...
```

---

## 6. Häufige Fehler

| Symptom | Prüfen |
|--------|--------|
| **503** „GitHub OAuth ist nicht konfiguriert“ | `GITHUB_CLIENT_ID` in `.env` gesetzt? |
| **403** „Zutritt verweigert. Keine gültige Einladung“ | Beim Einladungs-Login: `INITIAL_ADMIN_EMAIL` trifft nicht zu, und entweder keine gültige Einladung (`state=token`) oder abgelaufen/bereits eingelöst. |
| Redirect zu GitHub klappt, danach Fehlerseite | `BASE_URL` = `http://localhost:8000`? Callback-URL in der GitHub OAuth App **exakt** `http://localhost:8000/api/auth/github/callback`? |
| Nach OAuth: weiße Seite oder „Anmeldung wird abgeschlossen…“ | `FRONTEND_URL` passt zur tatsächlichen Frontend-URL? Frontend läuft? `/auth/callback` erreichbar? |
| „ENCRYPTION_KEY ist nicht gesetzt“ | `.env` mit `ENCRYPTION_KEY=…` anlegen (Fernet-Key aus Schritt 2). |
