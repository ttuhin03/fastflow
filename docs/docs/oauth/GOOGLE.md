# Google OAuth + Einladung

Anleitung zum Einrichten von **Google OAuth 2.0 / OIDC** für Login, Einladung und Konto verknüpfen.

---

## 1. OAuth-Client in der Google Cloud Console

1. [Google Cloud Console](https://console.cloud.google.com/) → Projekt wählen/erstellen
2. **APIs & Services** → **Anmeldedaten** → **Anmeldedaten erstellen**** → **OAuth-Client-ID**
3. Anwendungstyp: **Webanwendung**
4. **Authorisierte Weiterleitungs-URIs** hinzufügen:
   - `http://localhost:8000/api/auth/google/callback` (lokal)
   - in Produktion: `https://deine-domain.de/api/auth/google/callback`
5. **Erstellen** → **Client-ID** und **Client-Geheimnis** kopieren (Geheimnis nur einmal sichtbar).

---

## 2. .env

```env
GOOGLE_CLIENT_ID=<Client-ID aus Schritt 1>
GOOGLE_CLIENT_SECRET=<Client-Geheimnis>
# INITIAL_ADMIN_EMAIL: gilt auch für Google (E-Mail von Google muss exakt passen)
# BASE_URL / FRONTEND_URL: wie bei GitHub (Callback, Redirects)
```

---

## 3. Abläufe

### A) Erster Login (INITIAL_ADMIN_EMAIL)

- `/login` → **„Sign in with Google“**  
- E-Mail von Google muss **exakt** `INITIAL_ADMIN_EMAIL` entsprechen.

### B) Einladung einlösen

- Einladungslink `/invite?token=…` → **„Mit Google registrieren“**  
- E-Mail von Google muss der Einladungs-E-Mail (`recipient_email`) entsprechen.

### C) Konto verknüpfen (Link Google)

- **Einstellungen** → **Verknüpfte Konten** → bei Google **„Jetzt verbinden“**  
- Redirect zu `/api/auth/link/google` → Google OAuth → zurück zu **/settings?linked=google**  
- Sinnvoll, wenn GitHub- und Google-E-Mail **unterschiedlich** sind: Verknüpfung nur so möglich (kein Auto-Match über E-Mail).

---

## 4. Scopes

Verwendet werden: `openid`, `email`, `profile` (über `openid email profile`).

---

## 5. Häufige Fehler

| Symptom | Prüfen |
|--------|--------|
| **503** „Google OAuth ist nicht konfiguriert“ | `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` in `.env` |
| **403** nach Google-Login | `INITIAL_ADMIN_EMAIL` bzw. Einladungs-E-Mail entspricht nicht der Google-E-Mail; Einladung abgelaufen/bereits eingelöst |
| Redirect-Fehler nach Authorisierung | **Weiterleitungs-URI** in der Cloud Console **exakt** `{BASE_URL}/api/auth/google/callback` (inkl. Protocol, Port, Pfad) |

---

## 6. Hinweis zu abweichenden E-Mails

Wenn jemand bei **GitHub** `ich@privat.de` und bei **Google** `ich@firma.de` hat, kann das System die Accounts **nicht** automatisch anhand der E-Mail zuordnen.  
Lösung: Zuerst mit einem Provider einloggen, dann unter **Einstellungen → Verknüpfte Konten** den anderen Provider über **„Jetzt verbinden“** verknüpfen. Die Verknüpfung erfolgt über die aktive Session (User ist schon eingeloggt), die E-Mail des zweiten Providers spielt dabei keine Rolle.
