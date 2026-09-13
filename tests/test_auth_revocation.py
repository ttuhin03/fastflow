"""Tests dafür, dass ein Entzug sofort wirkt.

Drei Wege blieben offen, nachdem ein Betreiber den Zugang gekappt hatte:

- ein laufender SSE-Log-Stream lief mit der Berechtigung vom Verbindungsaufbau
  weiter, bei einem langen ETL-Lauf also stundenlang;
- ein auf Vorrat geholter Download-Token las 60 Sekunden ohne jede Credential
  weiter, von beliebiger Adresse;
- ``PUT /users/{id}`` mit ``blocked: true`` ließ bestehende Sessions am Leben,
  anders als ``POST /users/{id}/block``.

Alle drei sind vorbestehend und unabhängig von der MCP-Anbindung.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlmodel import select

from app.api.logs import _stream_still_authorized
from app.auth.auth import (
    create_access_token,
    create_log_download_token,
    create_session,
    get_session_by_token,
    verify_log_download_token,
)
from app.core.api_token_hash import generate_api_token
from app.models import (
    ApiToken,
    ApiTokenScope,
    PipelineRun,
    RunStatus,
    Session as SessionModel,
    User,
    UserRole,
    UserStatus,
)


@pytest.fixture(autouse=True)
def _disable_rate_limit():
    from app.middleware.rate_limiting import limiter

    previous = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previous


def _user(test_session, role: UserRole = UserRole.WRITE) -> User:
    user = User(
        username=f"rev-{uuid4().hex[:8]}",
        email=f"{uuid4().hex[:8]}@example.com",
        role=role,
        status=UserStatus.ACTIVE,
    )
    test_session.add(user)
    test_session.commit()
    test_session.refresh(user)
    return user


def _api_token(test_session, user: User, *scopes: ApiTokenScope) -> tuple[str, ApiToken]:
    generated = generate_api_token()
    now = datetime.now(timezone.utc)
    row = ApiToken(
        token_hash=generated.token_hash,
        prefix=generated.prefix,
        label="widerruf",
        user_id=user.id,
        scopes=[s.value for s in (scopes or (ApiTokenScope.LOGS,))],
        expires_at=now + timedelta(days=1),
        created_at=now,
    )
    test_session.add(row)
    test_session.commit()
    test_session.refresh(row)
    return generated.token, row


def _run(test_session) -> PipelineRun:
    run = PipelineRun(
        id=uuid4(),
        pipeline_name="etl",
        status=RunStatus.RUNNING,
        log_file="/logs/etl.log",
        started_at=datetime.now(timezone.utc),
    )
    test_session.add(run)
    test_session.commit()
    test_session.refresh(run)
    return run


# --------------------------------------------------------------------------- #
# Download-Token: an den Aussteller gebunden
# --------------------------------------------------------------------------- #


def test_download_token_dies_with_the_api_token_that_minted_it(test_session):
    """Auf Vorrat geholte Download-URLs überleben den Widerruf nicht mehr.

    Vorher war das Token an nichts als die run_id gebunden: 60 Sekunden lang
    mehrfach nutzbar, ohne Bezug zum Aussteller.
    """
    user = _user(test_session)
    _, api_token = _api_token(test_session, user)
    run = _run(test_session)

    download = create_log_download_token(
        test_session, run.id,
        issued_to_user_id=user.id, issued_via_api_token_id=api_token.id,
    )
    assert verify_log_download_token(test_session, download, run.id) is True

    api_token.revoked_at = datetime.now(timezone.utc)
    test_session.add(api_token)
    test_session.commit()

    assert verify_log_download_token(test_session, download, run.id) is False


def test_download_token_dies_when_the_user_is_blocked(test_session):
    user = _user(test_session)
    run = _run(test_session)
    download = create_log_download_token(test_session, run.id, issued_to_user_id=user.id)
    assert verify_log_download_token(test_session, download, run.id) is True

    user.blocked = True
    test_session.add(user)
    test_session.commit()

    assert verify_log_download_token(test_session, download, run.id) is False


def test_download_token_dies_with_an_expired_api_token(test_session):
    user = _user(test_session)
    _, api_token = _api_token(test_session, user)
    run = _run(test_session)
    download = create_log_download_token(
        test_session, run.id,
        issued_to_user_id=user.id, issued_via_api_token_id=api_token.id,
    )

    api_token.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    test_session.add(api_token)
    test_session.commit()

    assert verify_log_download_token(test_session, download, run.id) is False


def test_legacy_download_token_without_an_issuer_still_works(test_session):
    """Zeilen aus der Zeit vor Migration 042 tragen keinen Aussteller.

    Sie verfallen binnen 60 Sekunden von selbst; sie abzulehnen hieße, während
    des Deployments laufende Downloads abzubrechen.
    """
    run = _run(test_session)

    legacy = create_log_download_token(test_session, run.id)

    assert verify_log_download_token(test_session, legacy, run.id) is True


def test_download_token_is_still_bound_to_its_run(test_session):
    """Die bisherige Bindung darf durch die neue nicht verloren gehen."""
    user = _user(test_session)
    run_a, run_b = _run(test_session), _run(test_session)
    download = create_log_download_token(test_session, run_a.id, issued_to_user_id=user.id)

    assert verify_log_download_token(test_session, download, run_b.id) is False


# --------------------------------------------------------------------------- #
# SSE-Stream: Neuprüfung im laufenden Betrieb
# --------------------------------------------------------------------------- #


def test_stream_authorization_follows_a_token_revocation(test_session, monkeypatch):
    """Der laufende Stream muss den Entzug bemerken, nicht nur der Verbindungsaufbau."""
    import app.core.database as database

    monkeypatch.setattr(database, "engine", test_session.get_bind())
    import app.api.logs as logs_api

    monkeypatch.setattr(logs_api, "engine", test_session.get_bind())

    user = _user(test_session)
    raw, api_token = _api_token(test_session, user, ApiTokenScope.LOGS)

    assert _stream_still_authorized(raw) is True

    api_token.revoked_at = datetime.now(timezone.utc)
    test_session.add(api_token)
    test_session.commit()

    assert _stream_still_authorized(raw) is False


def test_stream_authorization_follows_a_user_block(test_session, monkeypatch):
    import app.api.logs as logs_api

    monkeypatch.setattr(logs_api, "engine", test_session.get_bind())

    user = _user(test_session)
    raw, _ = _api_token(test_session, user, ApiTokenScope.LOGS)
    assert _stream_still_authorized(raw) is True

    user.blocked = True
    test_session.add(user)
    test_session.commit()

    assert _stream_still_authorized(raw) is False


def test_stream_authorization_requires_the_logs_scope(test_session, monkeypatch):
    import app.api.logs as logs_api

    monkeypatch.setattr(logs_api, "engine", test_session.get_bind())

    user = _user(test_session)
    raw, _ = _api_token(test_session, user, ApiTokenScope.READ)

    assert _stream_still_authorized(raw) is False


def test_stream_authorization_rejects_a_missing_credential(test_session, monkeypatch):
    import app.api.logs as logs_api

    monkeypatch.setattr(logs_api, "engine", test_session.get_bind())

    assert _stream_still_authorized(None) is False
    assert _stream_still_authorized("") is False


def test_stream_authorization_accepts_a_live_session(test_session, monkeypatch):
    import app.api.logs as logs_api

    monkeypatch.setattr(logs_api, "engine", test_session.get_bind())

    user = _user(test_session)
    jwt = create_access_token(user.username)
    create_session(test_session, user, jwt)

    assert _stream_still_authorized(jwt) is True

    user.blocked = True
    test_session.add(user)
    test_session.commit()

    assert _stream_still_authorized(jwt) is False


# --------------------------------------------------------------------------- #
# Sperren beendet die Sessions
# --------------------------------------------------------------------------- #


def test_blocking_via_update_deletes_the_sessions(client, test_session):
    """PUT /users/{id} muss dasselbe bewirken wie POST /users/{id}/block.

    Sonst behielt ein so gesperrter Nutzer sein JWT, bis es von selbst ablief.
    """
    from app.main import app
    from app.auth import get_current_user

    admin = _user(test_session, UserRole.ADMIN)
    victim = _user(test_session, UserRole.WRITE)
    jwt = create_access_token(victim.username)
    create_session(test_session, victim, jwt)
    assert get_session_by_token(test_session, jwt) is not None

    app.dependency_overrides[get_current_user] = lambda: admin
    try:
        response = client.put(f"/api/users/{victim.id}", json={"blocked": True})
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    assert get_session_by_token(test_session, jwt) is None
    remaining = test_session.exec(
        select(SessionModel).where(SessionModel.user_id == victim.id)
    ).all()
    assert remaining == []


def test_unblocking_does_not_touch_sessions(client, test_session):
    """Nur der Übergang nach 'gesperrt' beendet Sessions, nicht jedes Update."""
    from app.main import app
    from app.auth import get_current_user

    admin = _user(test_session, UserRole.ADMIN)
    other = _user(test_session, UserRole.WRITE)
    other.blocked = True
    test_session.add(other)
    test_session.commit()

    jwt = create_access_token(admin.username)
    create_session(test_session, admin, jwt)

    app.dependency_overrides[get_current_user] = lambda: admin
    try:
        response = client.put(f"/api/users/{other.id}", json={"blocked": False})
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    assert get_session_by_token(test_session, jwt) is not None
