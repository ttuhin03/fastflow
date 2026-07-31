"""
Tests für "letzter Login" (users.last_login_at).

Abgedeckt:
- Zeitstempel wird beim OAuth-Login gesetzt, nicht beim Token-Refresh
- API liefert den Wert mit UTC-Offset (naive DB-Werte werden als UTC gelesen)
- Sichtbarkeit: eigener Wert über /api/auth/me, fremde Werte nur für Admins
- Login schreibt eine Audit-Spur (user_login)
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from urllib.parse import urlparse, parse_qs

from sqlmodel import select

from app.auth import record_login
from app.core.timeutils import to_utc_iso
from app.main import app
from app.models import AuditLogEntry, User, UserRole, UserStatus


def _make_user(test_session, role: UserRole = UserRole.ADMIN, username: str = "admin-user") -> User:
    user = User(
        username=username,
        email=f"{username}@example.com",
        role=role,
        status=UserStatus.ACTIVE,
        github_id=f"gh-{username}",
    )
    test_session.add(user)
    test_session.commit()
    test_session.refresh(user)
    return user


def _state_from_authorize(client) -> str:
    """Startet den Authorize-Flow (setzt das oauth_state-Cookie) und liefert den state."""
    resp = client.get("/api/auth/github/authorize", follow_redirects=False)
    assert resp.status_code == 302
    return parse_qs(urlparse(resp.headers["location"]).query)["state"][0]


# --- to_utc_iso ------------------------------------------------------------


def test_to_utc_iso_treats_naive_values_as_utc():
    """SQLite/Postgres liefern naive Timestamps; ohne Offset würde der Browser Lokalzeit annehmen."""
    naive = datetime(2026, 7, 31, 9, 12, 0)
    assert to_utc_iso(naive) == "2026-07-31T09:12:00+00:00"


def test_to_utc_iso_normalizes_aware_values_to_utc():
    aware = datetime(2026, 7, 31, 11, 12, 0, tzinfo=timezone(timedelta(hours=2)))
    assert to_utc_iso(aware) == "2026-07-31T09:12:00+00:00"


def test_to_utc_iso_passes_through_none():
    assert to_utc_iso(None) is None


# --- record_login ----------------------------------------------------------


def test_record_login_sets_timestamp(test_session):
    user = _make_user(test_session, username="login-user")
    assert user.last_login_at is None

    before = datetime.now(timezone.utc)
    recorded = record_login(test_session, user.id)
    after = datetime.now(timezone.utc)

    assert recorded is not None
    stored = test_session.exec(select(User).where(User.id == user.id)).first().last_login_at
    assert stored is not None
    stored_utc = stored if stored.tzinfo else stored.replace(tzinfo=timezone.utc)
    assert before <= stored_utc <= after


def test_record_login_overwrites_previous_value(test_session):
    user = _make_user(test_session, username="repeat-user")
    user.last_login_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    test_session.add(user)
    test_session.commit()

    record_login(test_session, user.id)

    stored = test_session.exec(select(User).where(User.id == user.id)).first().last_login_at
    stored_utc = stored if stored.tzinfo else stored.replace(tzinfo=timezone.utc)
    assert stored_utc.year >= 2026


def test_record_login_does_not_raise_when_update_fails(test_session):
    """Ein fehlgeschlagenes Statistik-Update darf einen gültigen Login nie abbrechen."""
    user = _make_user(test_session, username="broken-db-user")

    with patch.object(type(test_session), "exec", side_effect=RuntimeError("db down")):
        assert record_login(test_session, user.id) is None


# --- API-Sichtbarkeit ------------------------------------------------------


def test_users_list_exposes_last_login_for_admin(client, test_session):
    from app.auth import get_current_user

    admin = _make_user(test_session, UserRole.ADMIN, "admin-list")
    other = _make_user(test_session, UserRole.WRITE, "colleague")
    record_login(test_session, other.id)

    app.dependency_overrides[get_current_user] = lambda: admin
    try:
        response = client.get("/api/users")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    by_name = {u["username"]: u for u in response.json()}
    assert by_name["colleague"]["last_login_at"] is not None
    assert by_name["colleague"]["last_login_at"].endswith("+00:00")
    # Noch nie angemeldet -> null (Frontend zeigt "–")
    assert by_name["admin-list"]["last_login_at"] is None


def test_invites_list_returns_utc_offsets(client, test_session):
    """Einladungs-Zeitpunkte kommen aus der DB (naiv) und brauchen denselben Offset."""
    from app.auth import get_current_user
    from app.models import Invitation

    admin = _make_user(test_session, UserRole.ADMIN, "invite-admin")
    test_session.add(
        Invitation(
            recipient_email="new@example.com",
            token="token-for-test",
            is_used=False,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            role=UserRole.READONLY,
        )
    )
    test_session.commit()

    app.dependency_overrides[get_current_user] = lambda: admin
    try:
        response = client.get("/api/users/invites")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    row = response.json()[0]
    assert row["created_at"].endswith("+00:00")
    assert row["expires_at"].endswith("+00:00")


def test_non_admin_cannot_read_other_users_last_login(client, test_session):
    """Fremde Login-Zeitpunkte bleiben Admins vorbehalten (GET /api/users ist admin-only)."""
    from app.auth import get_current_user

    write_user = _make_user(test_session, UserRole.WRITE, "write-user")

    app.dependency_overrides[get_current_user] = lambda: write_user
    try:
        response = client.get("/api/users")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 403


def test_me_returns_own_last_login(client, test_session):
    from app.auth import get_current_user

    user = _make_user(test_session, UserRole.READONLY, "me-user")
    record_login(test_session, user.id)
    test_session.refresh(user)

    app.dependency_overrides[get_current_user] = lambda: user
    try:
        response = client.get("/api/auth/me")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    body = response.json()
    assert body["last_login_at"] is not None
    assert body["last_login_at"].endswith("+00:00")


def test_me_returns_null_before_first_login(client, test_session):
    from app.auth import get_current_user

    user = _make_user(test_session, UserRole.READONLY, "fresh-user")

    app.dependency_overrides[get_current_user] = lambda: user
    try:
        response = client.get("/api/auth/me")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    assert response.json()["last_login_at"] is None


# --- Login-Flow ------------------------------------------------------------


def test_oauth_callback_records_login_and_audit(client, test_session):
    user = _make_user(test_session, UserRole.WRITE, "oauth-user")
    state = _state_from_authorize(client)

    fake_user = {"id": 4242, "login": "octocat", "email": "octo@example.com", "avatar_url": None}
    with patch("app.api.auth.get_github_user_data", new=AsyncMock(return_value=fake_user)), patch(
        "app.api.auth.process_oauth_login",
        new=AsyncMock(return_value=(user, False, False, False, None)),
    ):
        resp = client.get(
            f"/api/auth/github/callback?code=valid-code&state={state}",
            follow_redirects=False,
        )

    assert resp.status_code == 302
    stored = test_session.exec(select(User).where(User.id == user.id)).first()
    assert stored.last_login_at is not None

    entries = test_session.exec(
        select(AuditLogEntry).where(AuditLogEntry.action == "user_login")
    ).all()
    assert len(entries) == 1
    assert entries[0].resource_id == str(user.id)
    assert entries[0].details == {"provider": "github"}


def test_link_flow_does_not_record_login(client, test_session):
    """Ein Account-Link ist keine Anmeldung: last_login_at bleibt unverändert."""
    user = _make_user(test_session, UserRole.WRITE, "link-user")
    state = _state_from_authorize(client)

    fake_user = {"id": 4242, "login": "octocat", "email": "octo@example.com", "avatar_url": None}
    with patch("app.api.auth.get_github_user_data", new=AsyncMock(return_value=fake_user)), patch(
        "app.api.auth.process_oauth_login",
        new=AsyncMock(return_value=(user, True, False, False, None)),
    ):
        resp = client.get(
            f"/api/auth/github/callback?code=valid-code&state={state}",
            follow_redirects=False,
        )

    assert resp.status_code == 302
    assert "linked=github" in resp.headers["location"]
    stored = test_session.exec(select(User).where(User.id == user.id)).first()
    assert stored.last_login_at is None


def test_refresh_does_not_change_last_login(client, test_session):
    """Token-Refresh erneuert nur das Access-Token einer bestehenden Sitzung."""
    from app.auth import create_access_token, create_session

    user = _make_user(test_session, UserRole.WRITE, "refresh-user")
    earlier = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
    user.last_login_at = earlier
    test_session.add(user)
    test_session.commit()

    token = create_access_token(username=user.username)
    create_session(test_session, user, token)

    response = client.post("/api/auth/refresh", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200

    stored = test_session.exec(select(User).where(User.id == user.id)).first().last_login_at
    stored_utc = stored if stored.tzinfo else stored.replace(tzinfo=timezone.utc)
    assert stored_utc == earlier
