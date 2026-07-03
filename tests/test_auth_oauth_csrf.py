"""
Tests für Login-CSRF-Schutz der OAuth-Callbacks.

Der zurückkommende `state` muss zum browser-gebundenen `oauth_state`-Cookie
passen, das beim Authorize-Schritt gesetzt wird. Andernfalls: 400.
"""

from urllib.parse import urlparse, parse_qs
from unittest.mock import AsyncMock, patch

import pytest


def _state_from_authorize(client) -> str:
    """Startet den Authorize-Flow und liefert den generierten state zurück.

    Nebeneffekt: das oauth_state-Cookie wird im Client gespeichert (wie im Browser).
    """
    resp = client.get("/api/auth/github/authorize", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    state = parse_qs(urlparse(location).query)["state"][0]
    # Cookie wurde an den Browser (Client) gebunden
    assert "oauth_state" in resp.cookies or "oauth_state" in client.cookies
    return state


def test_authorize_sets_oauth_state_cookie(client):
    resp = client.get("/api/auth/github/authorize", follow_redirects=False)
    assert resp.status_code == 302
    set_cookie = resp.headers.get("set-cookie", "")
    assert "oauth_state=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "samesite=lax" in set_cookie.lower()
    assert "Path=/api/auth" in set_cookie


def test_callback_with_matching_state_and_cookie_succeeds(client, test_user):
    """Happy Path: state == Cookie -> Login läuft durch (Redirect zum Frontend)."""
    state = _state_from_authorize(client)

    fake_user = {"id": 4242, "login": "octocat", "email": "octo@example.com", "avatar_url": None}
    with patch("app.api.auth.get_github_user_data", new=AsyncMock(return_value=fake_user)), patch(
        "app.api.auth.process_oauth_login",
        new=AsyncMock(return_value=(test_user, False, False, True, None)),
    ):
        resp = client.get(
            f"/api/auth/github/callback?code=valid-code&state={state}",
            follow_redirects=False,
        )

    assert resp.status_code == 302
    # Erfolgreicher Login leitet zum Frontend-Exchange (/auth/callback?code=) weiter
    assert "/auth/callback?code=" in resp.headers["location"]
    # Cookie wird nach Abschluss gelöscht
    assert 'oauth_state=""' in resp.headers.get("set-cookie", "") or "oauth_state=;" in resp.headers.get("set-cookie", "")


def test_callback_with_missing_cookie_is_rejected(client):
    """Angreifer-Szenario: gültig aussehender state, aber kein passendes Cookie -> 400."""
    fake_user = {"id": 4242, "login": "octocat", "email": "octo@example.com", "avatar_url": None}
    with patch("app.api.auth.get_github_user_data", new=AsyncMock(return_value=fake_user)) as m_user:
        resp = client.get(
            "/api/auth/github/callback?code=attacker-code&state=attacker-state",
            follow_redirects=False,
        )
    assert resp.status_code == 400
    # Der Provider-Code wurde gar nicht erst eingelöst
    m_user.assert_not_called()


def test_callback_with_mismatched_state_is_rejected(client):
    """state im Query weicht vom Cookie ab (Login-CSRF) -> 400, kein Code-Exchange."""
    _state_from_authorize(client)  # setzt gültiges Cookie
    fake_user = {"id": 4242, "login": "octocat", "email": "octo@example.com", "avatar_url": None}
    with patch("app.api.auth.get_github_user_data", new=AsyncMock(return_value=fake_user)) as m_user:
        resp = client.get(
            "/api/auth/github/callback?code=attacker-code&state=does-not-match-cookie",
            follow_redirects=False,
        )
    assert resp.status_code == 400
    m_user.assert_not_called()


def test_callback_without_state_is_rejected(client):
    """Fehlender state-Query -> 400."""
    _state_from_authorize(client)
    fake_user = {"id": 4242, "login": "octocat", "email": "octo@example.com", "avatar_url": None}
    with patch("app.api.auth.get_github_user_data", new=AsyncMock(return_value=fake_user)) as m_user:
        resp = client.get(
            "/api/auth/github/callback?code=attacker-code",
            follow_redirects=False,
        )
    assert resp.status_code == 400
    m_user.assert_not_called()
