"""Tests für persönliche API-Tokens: Format, Principal-Auflösung und Endpoints.

Schwerpunkt liegt auf den Sicherheitszusagen aus app/auth/principal.py:
- Token- und Session-Pfad sind strikt getrennt (Verzweigung am Präfix)
- Rolle begrenzt Token-Scopes jederzeit nach unten
- widerrufene, abgelaufene und verwaiste Tokens sind wertlos
- die Token-Endpoints selbst sind session-only (kein Self-Service per Token)
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlmodel import select

from app.auth import create_access_token, create_session, get_current_user
from app.auth.principal import (
    LAST_USED_THROTTLE_SECONDS,
    Principal,
    get_principal,
    parse_scopes,
    require_scope,
    scopes_for_role,
)
from app.core.api_token_hash import (
    TOKEN_PREFIX,
    digest_api_token,
    generate_api_token,
    looks_like_api_token,
)
from app.core.database import get_session
from app.main import app
from app.models import ApiToken, ApiTokenScope, AuditLogEntry, User, UserRole, UserStatus


# --------------------------------------------------------------------------- #
# Fixtures und Helfer
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _disable_rate_limit():
    """Deaktiviert das globale Rate-Limit für dieses Modul.

    POST /api/tokens ist auf 10/min begrenzt; die Tests hier legen mehr Tokens an.
    Die Begrenzung selbst ist slowapi-Verhalten und wird nicht hier getestet.
    """
    from app.middleware.rate_limiting import limiter

    previous = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previous


def _make_user(
    test_session,
    role: UserRole = UserRole.WRITE,
    *,
    username: str = None,
    blocked: bool = False,
    status: UserStatus = UserStatus.ACTIVE,
) -> User:
    user = User(
        username=username or f"user-{uuid4().hex[:8]}",
        email=f"{uuid4().hex[:8]}@example.com",
        role=role,
        blocked=blocked,
        status=status,
    )
    test_session.add(user)
    test_session.commit()
    test_session.refresh(user)
    return user


def _seed_token(
    test_session,
    user: User,
    *,
    scopes=(ApiTokenScope.READ,),
    expires_in_days: int = 30,
    revoked: bool = False,
    label: str = "test token",
    last_used_at: datetime = None,
) -> tuple[str, ApiToken]:
    """Legt ein Token direkt in der DB an und gibt (Klartext, Zeile) zurück."""
    generated = generate_api_token()
    now = datetime.now(timezone.utc)
    row = ApiToken(
        token_hash=generated.token_hash,
        prefix=generated.prefix,
        label=label,
        user_id=user.id,
        scopes=[s.value for s in scopes],
        expires_at=now + timedelta(days=expires_in_days),
        revoked_at=now if revoked else None,
        last_used_at=last_used_at,
        created_at=now,
    )
    test_session.add(row)
    test_session.commit()
    test_session.refresh(row)
    return generated.token, row


def _as_user(user: User):
    """Überschreibt die Session-Authentifizierung der Haupt-App."""
    app.dependency_overrides[get_current_user] = lambda: user
    return lambda: app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def principal_client(test_session):
    """Mini-App, die get_principal und require_scope über echte Requests prüft.

    Phase 1 stellt noch keinen produktiven Endpoint auf require_scope um; ohne
    diese App ließe sich das Zusammenspiel aus HTTPBearer, Präfix-Verzweigung und
    Scope-Prüfung nur unter Umgehung der HTTP-Schicht testen.
    """
    probe = FastAPI()

    @probe.get("/whoami")
    async def whoami(principal: Principal = Depends(get_principal)):
        return {
            "username": principal.user.username,
            "auth_kind": principal.auth_kind,
            "scopes": sorted(s.value for s in principal.scopes),
            "token_id": str(principal.token_id) if principal.token_id else None,
            "audit_details": principal.audit_details(),
        }

    @probe.get("/needs-run")
    async def needs_run(principal: Principal = Depends(require_scope(ApiTokenScope.RUN))):
        return {"ok": True, "username": principal.user.username}

    @probe.get("/needs-read-and-logs")
    async def needs_read_and_logs(
        principal: Principal = Depends(
            require_scope(ApiTokenScope.READ, ApiTokenScope.LOGS)
        ),
    ):
        return {"ok": True}

    probe.dependency_overrides[get_session] = lambda: test_session
    with TestClient(probe) as client:
        yield client


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _session_jwt(test_session, user: User) -> str:
    """Erzeugt ein echtes Session-JWT samt DB-Zeile.

    get_principal ruft get_current_user direkt als Funktion auf (nicht über
    Depends), damit FastAPI den Session-Pfad nicht schon vor der
    Präfix-Verzweigung auflöst. Ein dependency_overrides-Eintrag greift deshalb
    nicht – der Session-Pfad muss über ein echtes Token getestet werden, was
    ohnehin die realistischere Abdeckung ist.
    """
    token = create_access_token(user.username)
    create_session(test_session, user, token)
    return token


# --------------------------------------------------------------------------- #
# Token-Format und Digest
# --------------------------------------------------------------------------- #


def test_generated_token_has_expected_shape():
    generated = generate_api_token()

    assert generated.token.startswith(TOKEN_PREFIX)
    assert looks_like_api_token(generated.token)
    assert len(generated.prefix) == 8
    # Der öffentliche Prefix ist eine eigene Ziehung, kein Ausschnitt des Geheimnisses.
    secret_part = generated.token.split("_", 2)[2]
    assert generated.prefix not in secret_part
    assert generated.token_hash == digest_api_token(generated.token)
    assert len(generated.token_hash) == 64


def test_generated_tokens_are_unique():
    tokens = {generate_api_token().token for _ in range(200)}
    assert len(tokens) == 200


def test_digest_is_stable_and_differs_per_token():
    a, b = generate_api_token(), generate_api_token()

    # Zweimal derselbe Klartext muss denselben Digest ergeben – sonst fände die
    # Suche in api_tokens.token_hash ein gültiges Token nie wieder.
    first_pass = digest_api_token(a.token)
    second_pass = digest_api_token(a.token)

    assert first_pass == second_pass
    assert digest_api_token(b.token) != first_pass


@pytest.mark.parametrize(
    "value",
    [
        "",
        "ffp_",
        "ffp_short_abc",
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.signature",
        "ffp_12345678_" + "x" * 42,   # ein Zeichen zu kurz
        "ffp_12345678_" + "x" * 44,   # ein Zeichen zu lang
        "xfp_12345678_" + "x" * 43,   # falsches Präfix
        "ffp_1234567!_" + "x" * 43,   # unerlaubtes Zeichen im Prefix
    ],
)
def test_looks_like_api_token_rejects_invalid(value):
    assert looks_like_api_token(value) is False


def test_parse_scopes_drops_unknown_values():
    assert parse_scopes(["read", "bogus", "run"]) == frozenset(
        {ApiTokenScope.READ, ApiTokenScope.RUN}
    )
    assert parse_scopes([]) == frozenset()


def test_scopes_for_role_matrix():
    assert ApiTokenScope.RUN not in scopes_for_role(UserRole.READONLY)
    assert ApiTokenScope.RUN in scopes_for_role(UserRole.WRITE)
    assert ApiTokenScope.RUN in scopes_for_role(UserRole.ADMIN)
    # Alle Rollen dürfen lesen.
    for role in (UserRole.READONLY, UserRole.WRITE, UserRole.ADMIN):
        assert ApiTokenScope.READ in scopes_for_role(role)


# --------------------------------------------------------------------------- #
# Principal-Auflösung
# --------------------------------------------------------------------------- #


def test_valid_token_resolves_to_principal(principal_client, test_session):
    user = _make_user(test_session, UserRole.WRITE, username="token-owner")
    token, row = _seed_token(test_session, user, scopes=(ApiTokenScope.READ, ApiTokenScope.RUN))

    response = principal_client.get("/whoami", headers=_bearer(token))

    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "token-owner"
    assert body["auth_kind"] == "token"
    assert body["scopes"] == ["read", "run"]
    assert body["token_id"] == str(row.id)
    assert body["audit_details"]["auth_kind"] == "token"
    assert body["audit_details"]["token_label"] == "test token"


def test_missing_credentials_are_rejected(principal_client):
    assert principal_client.get("/whoami").status_code == 401


def test_unknown_token_is_rejected(principal_client, test_session):
    _make_user(test_session)
    unknown = generate_api_token().token

    assert principal_client.get("/whoami", headers=_bearer(unknown)).status_code == 401


def test_revoked_token_is_rejected(principal_client, test_session):
    user = _make_user(test_session)
    token, _ = _seed_token(test_session, user, revoked=True)

    assert principal_client.get("/whoami", headers=_bearer(token)).status_code == 401


def test_expired_token_is_rejected(principal_client, test_session):
    user = _make_user(test_session)
    token, _ = _seed_token(test_session, user, expires_in_days=-1)

    assert principal_client.get("/whoami", headers=_bearer(token)).status_code == 401


def test_blocked_user_token_is_rejected(principal_client, test_session):
    user = _make_user(test_session, blocked=True)
    token, _ = _seed_token(test_session, user)

    assert principal_client.get("/whoami", headers=_bearer(token)).status_code == 401


def test_pending_user_token_is_rejected(principal_client, test_session):
    user = _make_user(test_session, status=UserStatus.PENDING)
    token, _ = _seed_token(test_session, user)

    assert principal_client.get("/whoami", headers=_bearer(token)).status_code == 401


def test_orphaned_token_is_rejected(principal_client, test_session):
    """Ein Token ohne Besitzer ist wertlos – unabhängig vom ON DELETE CASCADE.

    Das Cascade der Migration räumt solche Zeilen normalerweise ab; die Prüfung
    in _principal_from_api_token ist die eigentliche Garantie und greift auch
    dort, wo die Datenbank Fremdschlüssel nicht durchsetzt (SQLite tut das ohne
    PRAGMA foreign_keys=ON nicht).
    """
    user = _make_user(test_session)
    token, row = _seed_token(test_session, user)
    test_session.delete(user)
    test_session.commit()

    assert principal_client.get("/whoami", headers=_bearer(token)).status_code == 401


def test_failure_responses_do_not_distinguish_cause(principal_client, test_session):
    """Unbekannt, widerrufen und abgelaufen liefern denselben Text.

    Andernfalls verriete die Antwort, ob ein Token existiert.
    """
    user = _make_user(test_session)
    revoked, _ = _seed_token(test_session, user, revoked=True)
    expired, _ = _seed_token(test_session, user, expires_in_days=-1)
    unknown = generate_api_token().token

    details = {
        principal_client.get("/whoami", headers=_bearer(value)).json()["detail"]
        for value in (revoked, expired, unknown)
    }
    assert len(details) == 1


def test_role_narrows_token_scopes(principal_client, test_session):
    """Ein Token mit run bei einem READONLY-Nutzer verliert run."""
    user = _make_user(test_session, UserRole.READONLY)
    token, _ = _seed_token(
        test_session, user, scopes=(ApiTokenScope.READ, ApiTokenScope.RUN)
    )

    body = principal_client.get("/whoami", headers=_bearer(token)).json()

    assert body["scopes"] == ["read"]


def test_token_with_only_forbidden_scopes_is_rejected(principal_client, test_session):
    """Bleibt nach dem Schnitt mit der Rolle nichts übrig, ist das Token wertlos."""
    user = _make_user(test_session, UserRole.READONLY)
    token, _ = _seed_token(test_session, user, scopes=(ApiTokenScope.RUN,))

    assert principal_client.get("/whoami", headers=_bearer(token)).status_code == 401


def test_session_auth_still_works_through_get_principal(principal_client, test_session):
    """Der Session-Pfad bleibt unverändert und erhält alle Scopes der Rolle."""
    user = _make_user(test_session, UserRole.WRITE, username="session-user")
    jwt_token = _session_jwt(test_session, user)

    response = principal_client.get("/whoami", headers=_bearer(jwt_token))

    assert response.status_code == 200
    body = response.json()
    assert body["auth_kind"] == "session"
    assert body["token_id"] is None
    assert body["scopes"] == ["logs", "read", "run", "source"]


def test_last_used_at_is_recorded(principal_client, test_session):
    user = _make_user(test_session)
    token, row = _seed_token(test_session, user)
    assert row.last_used_at is None

    principal_client.get("/whoami", headers=_bearer(token))

    test_session.refresh(row)
    assert row.last_used_at is not None


def test_last_used_at_is_throttled(principal_client, test_session):
    """Ein kürzlich gesetzter Zeitstempel wird nicht bei jedem Request neu geschrieben."""
    user = _make_user(test_session)
    recent = datetime.now(timezone.utc) - timedelta(seconds=LAST_USED_THROTTLE_SECONDS // 2)
    token, row = _seed_token(test_session, user, last_used_at=recent)

    principal_client.get("/whoami", headers=_bearer(token))

    test_session.refresh(row)
    stored = row.last_used_at
    stored = stored if stored.tzinfo else stored.replace(tzinfo=timezone.utc)
    assert abs((stored - recent).total_seconds()) < 1


# --------------------------------------------------------------------------- #
# require_scope
# --------------------------------------------------------------------------- #


def test_require_scope_allows_matching_token(principal_client, test_session):
    user = _make_user(test_session, UserRole.WRITE)
    token, _ = _seed_token(test_session, user, scopes=(ApiTokenScope.RUN,))

    assert principal_client.get("/needs-run", headers=_bearer(token)).status_code == 200


def test_require_scope_rejects_missing_scope(principal_client, test_session):
    user = _make_user(test_session, UserRole.WRITE)
    token, _ = _seed_token(test_session, user, scopes=(ApiTokenScope.READ,))

    response = principal_client.get("/needs-run", headers=_bearer(token))

    assert response.status_code == 403
    assert "run" in response.json()["detail"]


def test_require_scope_needs_all_listed_scopes(principal_client, test_session):
    user = _make_user(test_session, UserRole.WRITE)
    token, _ = _seed_token(test_session, user, scopes=(ApiTokenScope.READ,))

    assert (
        principal_client.get("/needs-read-and-logs", headers=_bearer(token)).status_code == 403
    )


def test_require_scope_applies_to_session_auth_too(principal_client, test_session):
    """Ein READONLY-Nutzer im Browser scheitert an run genauso wie ein Token."""
    user = _make_user(test_session, UserRole.READONLY)
    jwt_token = _session_jwt(test_session, user)

    response = principal_client.get("/needs-run", headers=_bearer(jwt_token))

    assert response.status_code == 403


def test_require_scope_without_arguments_is_a_programming_error():
    with pytest.raises(ValueError):
        require_scope()


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #


def test_create_token_returns_cleartext_once(client, test_session):
    user = _make_user(test_session, UserRole.WRITE)
    clear = _as_user(user)
    try:
        response = client.post(
            "/api/tokens",
            json={"label": "CI nightly", "scopes": ["read", "run"], "expires_in_days": 30},
        )
    finally:
        clear()

    assert response.status_code == 201
    body = response.json()
    assert looks_like_api_token(body["token"])
    assert body["label"] == "CI nightly"
    assert sorted(body["scopes"]) == ["read", "run"]

    # Gespeichert wird nur der Digest – der Klartext taucht nirgends in der DB auf.
    row = test_session.get(ApiToken, UUID(body["id"]))
    assert row is not None
    assert row.token_hash == digest_api_token(body["token"])
    assert body["token"] not in (row.prefix, row.label)


def test_create_token_writes_audit_entry_without_secret(client, test_session):
    user = _make_user(test_session, UserRole.WRITE)
    clear = _as_user(user)
    try:
        response = client.post(
            "/api/tokens", json={"label": "audit me", "scopes": ["read"]}
        )
    finally:
        clear()

    token_value = response.json()["token"]
    entries = test_session.exec(
        select(AuditLogEntry).where(
            AuditLogEntry.action == "api_token_create"
        )
    ).all()
    assert len(entries) == 1
    assert entries[0].resource_type == "api_token"
    assert token_value not in str(entries[0].details)


def test_create_token_rejects_scope_above_role(client, test_session):
    user = _make_user(test_session, UserRole.READONLY)
    clear = _as_user(user)
    try:
        response = client.post("/api/tokens", json={"label": "x", "scopes": ["run"]})
    finally:
        clear()

    assert response.status_code == 403
    assert "run" in response.json()["detail"]


def test_create_token_rejects_empty_label(client, test_session):
    user = _make_user(test_session)
    clear = _as_user(user)
    try:
        response = client.post("/api/tokens", json={"label": "   ", "scopes": ["read"]})
    finally:
        clear()

    assert response.status_code == 422


def test_create_token_rejects_empty_scopes(client, test_session):
    user = _make_user(test_session)
    clear = _as_user(user)
    try:
        response = client.post("/api/tokens", json={"label": "x", "scopes": []})
    finally:
        clear()

    assert response.status_code == 422


@pytest.mark.parametrize("days", [0, -1, 366])
def test_create_token_rejects_expiry_out_of_bounds(client, test_session, days):
    user = _make_user(test_session)
    clear = _as_user(user)
    try:
        response = client.post(
            "/api/tokens",
            json={"label": "x", "scopes": ["read"], "expires_in_days": days},
        )
    finally:
        clear()

    assert response.status_code == 422


def test_create_token_enforces_per_user_limit(client, test_session):
    from app.api.tokens import MAX_ACTIVE_TOKENS_PER_USER

    user = _make_user(test_session)
    for _ in range(MAX_ACTIVE_TOKENS_PER_USER):
        _seed_token(test_session, user)

    clear = _as_user(user)
    try:
        response = client.post("/api/tokens", json={"label": "one too many", "scopes": ["read"]})
    finally:
        clear()

    assert response.status_code == 409


def test_revoked_tokens_do_not_count_towards_limit(client, test_session):
    from app.api.tokens import MAX_ACTIVE_TOKENS_PER_USER

    user = _make_user(test_session)
    for _ in range(MAX_ACTIVE_TOKENS_PER_USER):
        _seed_token(test_session, user, revoked=True)

    clear = _as_user(user)
    try:
        response = client.post("/api/tokens", json={"label": "fresh", "scopes": ["read"]})
    finally:
        clear()

    assert response.status_code == 201


def test_list_returns_only_own_tokens_and_no_values(client, test_session):
    owner = _make_user(test_session, username="owner")
    other = _make_user(test_session, username="other")
    own_token, _ = _seed_token(test_session, owner, label="mine")
    _seed_token(test_session, other, label="theirs")

    clear = _as_user(owner)
    try:
        response = client.get("/api/tokens")
    finally:
        clear()

    assert response.status_code == 200
    body = response.json()
    labels = [item["label"] for item in body["tokens"]]
    assert labels == ["mine"]
    assert own_token not in response.text
    assert body["available_scopes"] == ["read", "logs", "source", "run"]


def test_list_hides_revoked_by_default_and_shows_them_on_request(client, test_session):
    user = _make_user(test_session)
    _seed_token(test_session, user, label="active")
    _seed_token(test_session, user, label="dead", revoked=True)

    clear = _as_user(user)
    try:
        default = client.get("/api/tokens").json()
        with_revoked = client.get("/api/tokens", params={"include_revoked": "true"}).json()
    finally:
        clear()

    assert [t["label"] for t in default["tokens"]] == ["active"]
    assert sorted(t["label"] for t in with_revoked["tokens"]) == ["active", "dead"]


def test_list_marks_expired_tokens(client, test_session):
    user = _make_user(test_session)
    _seed_token(test_session, user, label="stale", expires_in_days=-1)

    clear = _as_user(user)
    try:
        body = client.get("/api/tokens").json()
    finally:
        clear()

    assert body["tokens"][0]["expired"] is True


def test_admin_sees_all_tokens_with_owner(client, test_session):
    admin = _make_user(test_session, UserRole.ADMIN, username="admin")
    owner = _make_user(test_session, username="someone")
    _seed_token(test_session, owner, label="theirs")

    clear = _as_user(admin)
    try:
        body = client.get("/api/tokens").json()
    finally:
        clear()

    theirs = [t for t in body["tokens"] if t["label"] == "theirs"]
    assert len(theirs) == 1
    assert theirs[0]["username"] == "someone"


def test_readonly_user_available_scopes_exclude_run(client, test_session):
    user = _make_user(test_session, UserRole.READONLY)
    clear = _as_user(user)
    try:
        body = client.get("/api/tokens").json()
    finally:
        clear()

    assert body["available_scopes"] == ["read", "logs", "source"]


def test_revoke_own_token_is_idempotent(client, test_session):
    user = _make_user(test_session)
    token, row = _seed_token(test_session, user)

    clear = _as_user(user)
    try:
        first = client.delete(f"/api/tokens/{row.id}")
        second = client.delete(f"/api/tokens/{row.id}")
    finally:
        clear()

    assert first.status_code == 200
    assert second.status_code == 200
    test_session.refresh(row)
    assert row.revoked_at is not None

    # Nur der tatsächliche Übergang wird auditiert, nicht der zweite Aufruf.
    entries = test_session.exec(
        select(AuditLogEntry).where(
            AuditLogEntry.action == "api_token_revoke"
        )
    ).all()
    assert len(entries) == 1


def test_revoking_foreign_token_returns_404_not_403(client, test_session):
    """404 statt 403: sonst ließe sich die Existenz fremder Token-IDs abfragen."""
    owner = _make_user(test_session, username="owner")
    attacker = _make_user(test_session, username="attacker")
    _, row = _seed_token(test_session, owner)

    clear = _as_user(attacker)
    try:
        response = client.delete(f"/api/tokens/{row.id}")
    finally:
        clear()

    assert response.status_code == 404
    test_session.refresh(row)
    assert row.revoked_at is None


def test_admin_can_revoke_foreign_token(client, test_session):
    admin = _make_user(test_session, UserRole.ADMIN, username="admin")
    owner = _make_user(test_session, username="owner")
    _, row = _seed_token(test_session, owner)

    clear = _as_user(admin)
    try:
        response = client.delete(f"/api/tokens/{row.id}")
    finally:
        clear()

    assert response.status_code == 200
    test_session.refresh(row)
    assert row.revoked_at is not None


def test_revoked_token_stops_authenticating(principal_client, client, test_session):
    """Der Widerruf wirkt sofort auf den Auth-Pfad."""
    user = _make_user(test_session)
    token, row = _seed_token(test_session, user)
    assert principal_client.get("/whoami", headers=_bearer(token)).status_code == 200

    clear = _as_user(user)
    try:
        client.delete(f"/api/tokens/{row.id}")
    finally:
        clear()

    assert principal_client.get("/whoami", headers=_bearer(token)).status_code == 401


def test_token_endpoints_reject_api_token_auth(client, test_session):
    """Ein API-Token darf kein weiteres Token erzeugen (keine Selbstverlängerung).

    Die Token-Endpoints hängen an get_current_user, das ausschließlich
    Session-JWTs akzeptiert – ein ffp_-Wert scheitert bereits am JWT-Decode.
    """
    user = _make_user(test_session, UserRole.WRITE)
    token, _ = _seed_token(test_session, user, scopes=(ApiTokenScope.READ, ApiTokenScope.RUN))

    created = client.post(
        "/api/tokens",
        json={"label": "escalate", "scopes": ["run"]},
        headers=_bearer(token),
    )
    listed = client.get("/api/tokens", headers=_bearer(token))

    assert created.status_code == 401
    assert listed.status_code == 401
