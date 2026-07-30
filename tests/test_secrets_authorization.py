"""
Regression-Tests für /api/secrets Autorisierung.
"""

from app.main import app
from app.auth import get_current_user
from app.models import Secret, User, UserRole, UserStatus
from app.services.secrets import encrypt


def _make_user(test_session, role: UserRole) -> User:
    user = User(
        username=f"user-{role.value.lower()}",
        email=f"{role.value.lower()}@example.com",
        role=role,
        status=UserStatus.ACTIVE,
    )
    test_session.add(user)
    test_session.commit()
    test_session.refresh(user)
    return user


def _seed_secret(test_session) -> None:
    secret = Secret(key="DB_PASSWORD", value=encrypt("super-secret-value"), is_parameter=False)
    test_session.add(secret)
    test_session.commit()


def _as_user(client, user: User):
    app.dependency_overrides[get_current_user] = lambda: user
    return lambda: app.dependency_overrides.pop(get_current_user, None)


def test_readonly_user_cannot_read_secrets(client, test_session):
    _seed_secret(test_session)
    readonly_user = _make_user(test_session, UserRole.READONLY)

    clear_override = _as_user(client, readonly_user)
    try:
        response = client.get("/api/secrets")
    finally:
        clear_override()

    assert response.status_code == 403


def test_write_user_cannot_read_secrets(client, test_session):
    _seed_secret(test_session)
    write_user = _make_user(test_session, UserRole.WRITE)

    clear_override = _as_user(client, write_user)
    try:
        response = client.get("/api/secrets")
    finally:
        clear_override()

    assert response.status_code == 403


def test_admin_user_can_read_secrets(client, test_session):
    _seed_secret(test_session)
    admin_user = _make_user(test_session, UserRole.ADMIN)

    clear_override = _as_user(client, admin_user)
    try:
        response = client.get("/api/secrets")
    finally:
        clear_override()

    assert response.status_code == 200
    body = response.json()
    assert any(s["key"] == "DB_PASSWORD" and s["value"] == "super-secret-value" for s in body["secrets"])


def test_readonly_user_cannot_encrypt_for_pipeline(client, test_session):
    readonly_user = _make_user(test_session, UserRole.READONLY)

    clear_override = _as_user(client, readonly_user)
    try:
        response = client.post("/api/secrets/encrypt-for-pipeline", json={"value": "some-plaintext"})
    finally:
        clear_override()

    assert response.status_code == 403


def test_write_user_can_encrypt_for_pipeline(client, test_session):
    write_user = _make_user(test_session, UserRole.WRITE)

    clear_override = _as_user(client, write_user)
    try:
        response = client.post("/api/secrets/encrypt-for-pipeline", json={"value": "some-plaintext"})
    finally:
        clear_override()

    assert response.status_code == 200
    assert "encrypted" in response.json()
