# OAuth (GitHub & Google)

Fast-Flow unterstützt **GitHub OAuth** und **Google OAuth** für Login. Beide können pro User verknüpft werden („Link-Konto“ in den Einstellungen).

## Übersicht

- **Login:** `/login` → „Sign in with GitHub“ oder „Sign in with Google“
- **Einladung:** `/invite?token=…` → „Mit GitHub registrieren“ oder „Mit Google registrieren“ (E-Mail muss der Einladung entsprechen)
- **Erster Admin:** `INITIAL_ADMIN_EMAIL` in `.env` – User mit dieser E-Mail (von GitHub oder Google) wird beim ersten Login Admin
- **Konto verknüpfen:** Einstellungen → Verknüpfte Konten → „Jetzt verbinden“ bei GitHub bzw. Google. Ermöglicht Login mit beiden Accounts; nötig, wenn E-Mails bei GitHub und Google unterschiedlich sind.

## Dokumentation

- **[GitHub OAuth](GITHUB.md)** – OAuth-App, Scopes, Callback, Einladung, Link-Konto, Fehler
- **[Google OAuth](GOOGLE.md)** – OAuth-Client, Scopes, Callback, Einladung, Link-Konto

## Konfiguration

Siehe [CONFIGURATION.md](../deployment/CONFIGURATION.md): `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `INITIAL_ADMIN_EMAIL`, `FRONTEND_URL`, `BASE_URL`.
