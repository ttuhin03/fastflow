# Google OAuth + Invitation

Guide to setting up **Google OAuth 2.0 / OIDC** for login, invitation, and account linking.

---

## 1. OAuth client in Google Cloud Console

1. [Google Cloud Console](https://console.cloud.google.com/) → select/create project
2. **APIs & Services** → **Credentials** → **Create credentials** → **OAuth client ID**
3. Application type: **Web application**
4. Add **Authorized redirect URIs**:
   - `http://localhost:8000/api/auth/google/callback` (local)
   - in production: `https://your-domain.com/api/auth/google/callback`
5. **Create** → copy **Client ID** and **Client secret** (secret is only shown once).

---

## 2. .env

```env
GOOGLE_CLIENT_ID=<Client ID from step 1>
GOOGLE_CLIENT_SECRET=<Client secret>
# INITIAL_ADMIN_EMAIL: also applies to Google (Google email must match exactly)
# BASE_URL / FRONTEND_URL: same as GitHub (callback, redirects)
```

---

## 3. Flows

### A) First login (INITIAL_ADMIN_EMAIL)

- `/login` → **"Sign in with Google"**  
- Google email must **exactly** match `INITIAL_ADMIN_EMAIL`.

### B) Redeem invitation

- Invitation link `/invite?token=…` → **"Register with Google"**  
- Google email must match the invitation email (`recipient_email`).

### C) Link account (Link Google)

- **Settings** → **Linked accounts** → for Google **"Connect now"**  
- Redirect to `/api/auth/link/google` → Google OAuth → back to **/settings?linked=google**  
- Useful when GitHub and Google emails are **different**: linking is only possible this way (no auto-match via email).

---

## 4. Scopes

Used: `openid`, `email`, `profile` (via `openid email profile`).

---

## 5. Common errors

| Symptom | Check |
|--------|--------|
| **503** "Google OAuth is not configured" | `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` in `.env` |
| **403** after Google login | `INITIAL_ADMIN_EMAIL` or invitation email does not match Google email; invitation expired/already redeemed |
| Redirect error after authorization | **Redirect URI** in Cloud Console **exactly** `{BASE_URL}/api/auth/google/callback` (including protocol, port, path) |

---

## 6. Note on different emails

If someone has `me@private.com` on **GitHub** and `me@company.com` on **Google**, the system **cannot** automatically match the accounts by email.  
Solution: First log in with one provider, then under **Settings → Linked accounts** link the other provider via **"Connect now"**. Linking uses the active session (user is already logged in); the second provider's email does not matter.
