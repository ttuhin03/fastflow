---
slug: readme
---

# OAuth (GitHub, Google, Microsoft, Custom)

Fast-Flow unterstützt **GitHub OAuth**, **Google OAuth**, **Microsoft OAuth (Entra ID)** und **Custom OAuth** für Login. Provider können pro User verknüpft werden („Link-Konto“ in den Einstellungen).

## Übersicht

- **Login:** `/login` → Sign in mit GitHub, Google, Microsoft oder Custom
- **Einladung:** `/invite?token=…` → Registrierung via OAuth-Provider (E-Mail muss der Einladung entsprechen)
- **Erster Admin:** `INITIAL_ADMIN_EMAIL` in `.env` – User mit dieser E-Mail (vom jeweiligen OAuth-Provider) wird beim ersten Login Admin
- **Konto verknüpfen:** Einstellungen → Verknüpfte Konten → „Jetzt verbinden“ bei GitHub/Google/Microsoft/Custom.
- **Beitrittsanfragen (Anklopfen):** Unbekannte Nutzer (ohne Einladung, ohne E-Mail-Match, ohne INITIAL_ADMIN) können sich per OAuth anmelden. Statt 403 wird eine Anfrage angelegt (Status `pending`). Sie erhalten **keine Session, keinen Token** und werden auf `/request-sent` umgeleitet. Admins sehen sie unter **Users → Beitrittsanfragen** und können **Freigeben** (Rolle wählen) oder **Ablehnen**. Bei Freigabe: `status=active`, Nutzer kann sich danach normal einloggen. Abgelehnte (`status=rejected`, `blocked=true`) bzw. noch wartende Nutzer landen bei erneutem OAuth-Login auf `/request-rejected` bzw. `/request-sent` – ebenfalls ohne Session. Optional: E-Mail an Admins bei neuer Anfrage (`EMAIL_ENABLED`, `EMAIL_RECIPIENTS`), E-Mail an Nutzer bei Freigabe.

---

## OAuth-Flow (Diagramm)

```mermaid
flowchart TB
    subgraph Einstieg[Einstiegspunkte]
        L["/login - Sign in via OAuth-Provider"]
        I["/invite mit token - Registrierung via OAuth-Provider"]
        S["Einstellungen - Verknüpfte Konten - Jetzt verbinden"]
    end

    subgraph OAuth[OAuth bei Provider]
        G["GitHub, Google, Microsoft oder Custom - Autorisierung"]
    end

    subgraph Callback[API-Callback]
        C["/api/auth/{provider}/callback"]
    end

    subgraph Auswertung[process_oauth_login - Reihenfolge]
        P1{"state link_<provider>"}
        P2{"User mit dieser Provider-ID vorhanden"}
        P3{"pending oder blocked"}
        P4{"E-Mail-Match bei bestehendem User"}
        P5{"E-Mail eq INITIAL_ADMIN_EMAIL"}
        P6{"state Einladungs-token und E-Mail eq recipient"}
        P7["Anklopfen: unbekannter Nutzer"]
    end

    subgraph Ergebnis[Ergebnis]
        R1["/settings mit linked - Konto verknüpft, kein Token"]
        R2["/request-rejected - blocked, kein Token"]
        R3["/request-sent - pending, kein Token"]
        R4["/auth/callback mit token - App-Zugriff"]
        R5["User pending anlegen, notify Admin - dann /request-sent"]
    end

    L -->|state login| G
    I -->|state Invitation.token| G
    S -->|link + user_id| G

    G --> C
    C --> P1

    P1 -->|ja| R1
    P1 -->|nein| P2

    P2 -->|ja| P3
    P2 -->|nein| P4

    P3 -->|blocked rejected| R2
    P3 -->|pending| R3
    P3 -->|nein active| R4

    P4 -->|ja| R4
    P4 -->|nein| P5

    P5 -->|ja| R4
    P5 -->|nein| P6

    P6 -->|ja| R4
    P6 -->|nein| P7

    P7 --> R5
```

### Kurz erklärt

| Schritt | Bedingung | Ergebnis |
|--------|-----------|----------|
| **1. Link-Flow** | `state` enthält `link_<provider>` (von Einstellungen), Provider passt | Konto wird an bestehenden User gehängt → Redirect zu `/settings?linked=…` **ohne** neues Token. |
| **2. Direkt-Match** | User hat bereits diese Provider-ID | **blocked/rejected** → `/request-rejected` (kein Token). **pending** → `/request-sent` (kein Token). **active** → Token + `/auth/callback#token=…`. |
| **3. E-Mail-Match** | Anderer User mit gleicher E-Mail (Provider wird verknüpft) | Token + Session → App. |
| **4. INITIAL_ADMIN_EMAIL** | E-Mail von OAuth = `INITIAL_ADMIN_EMAIL` | Erster Admin: User anlegen/verknüpfen → Token + App. |
| **5. Einladung** | `state` = gültiger Einladungs‑Token **und** OAuth-E-Mail = `recipient_email` | User anlegen (Rolle aus Einladung) → Token + App. |
| **6. Anklopfen** | Keine der obigen | User mit `status=pending` anlegen, Admins benachrichtigen → Redirect zu `/request-sent` **ohne** Token. |

*Die Prüfungen in `process_oauth_login` laufen in dieser Reihenfolge; der erste Treffer bestimmt das Ergebnis.*

---

## Dokumentation

- **[GitHub OAuth](GITHUB.md)** – OAuth-App, Scopes, Callback, Einladung, Link-Konto, Fehler
- **[Google OAuth](GOOGLE.md)** – OAuth-Client, Scopes, Callback, Einladung, Link-Konto
- **Microsoft OAuth** – Callback: `{BASE_URL}/api/auth/microsoft/callback`
- **Custom OAuth** – Callback: `{BASE_URL}/api/auth/custom/callback`

## Konfiguration

Siehe [CONFIGURATION.md](../deployment/CONFIGURATION.md): `GITHUB_*`, `GOOGLE_*`, `MICROSOFT_*`, `CUSTOM_OAUTH_*`, `INITIAL_ADMIN_EMAIL`, `FRONTEND_URL`, `BASE_URL`.
