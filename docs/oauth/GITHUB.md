# GitHub OAuth + Einladung

Anleitung zum Einrichten und Testen von GitHub-Login und Einladungs-Flow.

---

## 1. GitHub OAuth App anlegen

1. **GitHub** → **Settings** (dein Profil) → **Developer settings** → **OAuth Apps** → **New OAuth App**
2. Ausfüllen:
   - **Application name:** z.B. `Fast-Flow (lokal)`
   - **Homepage URL:** `http://localhost:3000` (oder deine Frontend-URL)
   - **Authorization callback URL:** `http://localhost:8000/api/auth/github/callback` (bzw. `{BASE_URL}/api/auth/github/callback`)
3. **Register application** → **Generate a new client secret**
4. **Client ID** und **Client Secret** kopieren (Secret nur einmal sichtbar).

---

## 2. .env vorbereiten

```bash
cp .env.example .env
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# → ENCRYPTION_KEY in .env eintragen
```

In `.env` mindestens:

```env
ENCRYPTION_KEY=<…>
GITHUB_CLIENT_ID=<deine-Client-ID>
GITHUB_CLIENT_SECRET=<dein-Client-Secret>
INITIAL_ADMIN_EMAIL=deine-github-email@beispiel.de
FRONTEND_URL=http://localhost:3000
BASE_URL=http://localhost:8000
```

---

## 3. Backend + Frontend starten

- **Docker:** `./start-docker.sh` oder `./start-dev.sh`
- **Lokal:** `uvicorn app.main:app --reload --port 8000` sowie `cd frontend && npm run dev`

---

## 4. Abläufe

### A) Erster Login (INITIAL_ADMIN_EMAIL)

1. `/login` → **„Sign in with GitHub“**
2. Auf GitHub anmelden/authorisieren
3. Redirect zu `/auth/callback#token=…` → Dashboard
4. Nur wenn die bei GitHub hinterlegte (primäre) E-Mail **exakt** `INITIAL_ADMIN_EMAIL` entspricht.

### B) Einladung einlösen

1. Als Admin: **Users** → **Einladung senden** (E-Mail, Rolle, Gültigkeit)
2. Link z.B. `{FRONTEND_URL}/invite?token=…` kopieren
3. Empfänger öffnet Link → **„Mit GitHub registrieren“** → OAuth; E-Mail muss der Einladung entsprechen
4. Neuer User in **Users**, Einladung **Eingelöst**

### C) Konto verknüpfen (Link GitHub)

1. Bereits mit Google (oder anderem) eingeloggt
2. **Einstellungen** → **Verknüpfte Konten** → bei GitHub **„Jetzt verbinden“**
3. Redirect zu `/api/auth/link/github` → GitHub OAuth → zurück zu **/settings?linked=github**
4. Ab dann: Login mit GitHub **oder** Google möglich (gleicher User)

---

## 5. Häufige Fehler

| Symptom | Prüfen |
|--------|--------|
| **503** „GitHub OAuth ist nicht konfiguriert“ | `GITHUB_CLIENT_ID` in `.env` |
| **403** „Zutritt verweigert. Keine gültige Einladung“ | `INITIAL_ADMIN_EMAIL` trifft nicht zu; Einladung abgelaufen/bereits eingelöst; oder E-Mail (GitHub) ≠ `recipient_email` der Einladung |
| Redirect zu GitHub, danach Fehlerseite | `BASE_URL`; Callback in der OAuth-App **exakt** `{BASE_URL}/api/auth/github/callback` |
| Nach OAuth: weiße Seite | `FRONTEND_URL`, Frontend läuft, `/auth/callback` erreichbar |
| „ENCRYPTION_KEY ist nicht gesetzt“ | `.env` mit `ENCRYPTION_KEY=…` |

---

## 6. Nützliche Befehle

```bash
curl -sI "http://localhost:8000/api/auth/github/authorize"
# Erwartung: 302, Location: https://github.com/login/oauth/authorize?...
```
