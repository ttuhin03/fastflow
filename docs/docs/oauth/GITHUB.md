# GitHub OAuth + Invitation

Guide to setting up and testing GitHub login and the invitation flow.

---

## 1. Create a GitHub OAuth App

1. **GitHub** → **Settings** (your profile) → **Developer settings** → **OAuth Apps** → **New OAuth App**
2. Fill in:
   - **Application name:** e.g. `Fast-Flow (local)`
   - **Homepage URL:** `http://localhost:3000` (or your frontend URL)
   - **Authorization callback URL:** `http://localhost:8000/api/auth/github/callback` (or `{BASE_URL}/api/auth/github/callback`)
3. **Register application** → **Generate a new client secret**
4. Copy **Client ID** and **Client Secret** (secret is only shown once).

---

## 2. Prepare .env

```bash
cp .env.example .env
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# → enter ENCRYPTION_KEY in .env
```

In `.env` at minimum:

```env
ENCRYPTION_KEY=<…>
GITHUB_CLIENT_ID=<your-client-id>
GITHUB_CLIENT_SECRET=<your-client-secret>
INITIAL_ADMIN_EMAIL=your-github-email@example.com
FRONTEND_URL=http://localhost:3000
BASE_URL=http://localhost:8000
```

---

## 3. Start Backend + Frontend

- **Docker:** `./start-docker.sh` (or `docker compose up -d`)
- **Local:** `uvicorn app.main:app --reload --port 8000` and `cd frontend && npm run dev`

---

## 4. Flows

### A) First login (INITIAL_ADMIN_EMAIL)

1. `/login` → **"Sign in with GitHub"**
2. Sign in/authorize on GitHub
3. Redirect to `/auth/callback#token=…` → Dashboard
4. Only if the (primary) email stored on GitHub **exactly** matches `INITIAL_ADMIN_EMAIL`.

### B) Redeem invitation

1. As admin: **Users** → **Send invitation** (email, role, validity)
2. Copy link e.g. `{FRONTEND_URL}/invite?token=…`
3. Recipient opens link → **"Register with GitHub"** → OAuth; email must match the invitation
4. New user in **Users**, invitation **Redeemed**

### C) Link account (Link GitHub)

1. Already logged in with Google (or another provider)
2. **Settings** → **Linked accounts** → for GitHub **"Connect now"**
3. Redirect to `/api/auth/link/github` → GitHub OAuth → back to **/settings?linked=github**
4. From then on: login with GitHub **or** Google possible (same user)

---

## 5. Common errors

| Symptom | Check |
|--------|--------|
| **503** "GitHub OAuth is not configured" | `GITHUB_CLIENT_ID` in `.env` |
| **403** "Access denied. No valid invitation" | `INITIAL_ADMIN_EMAIL` does not match; invitation expired/already redeemed; or email (GitHub) ≠ invitation `recipient_email` |
| Redirect to GitHub, then error page | `BASE_URL`; callback in OAuth app **exactly** `{BASE_URL}/api/auth/github/callback` |
| After OAuth: blank page | `FRONTEND_URL`, frontend running, `/auth/callback` reachable |
| "ENCRYPTION_KEY is not set" | `.env` with `ENCRYPTION_KEY=…` |

---

## 6. Useful commands

```bash
curl -sI "http://localhost:8000/api/auth/github/authorize"
# Expected: 302, Location: https://github.com/login/oauth/authorize?...
```
