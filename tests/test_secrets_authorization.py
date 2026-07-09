"""
Regression-Test: GET /api/secrets darf Klartext-Secrets nicht an READONLY-Nutzer ausliefern.

Vorher war der Endpoint nur mit `get_current_user` geschützt (jeder eingeloggte
Nutzer, auch READONLY), obwohl er entschlüsselte Secret-Werte (API-Keys,
DB-Credentials etc.) zurückgibt. Das verletzte das App-eigene Rollenmodell,
in dem READONLY explizit keine sensiblen/ändernden Aktionen ausführen darf
(siehe require_write).
"""

from app.main import app
from app.models import Secret, User, UserRole, UserStatus
from app.services.secrets import encrypt


def _override_current_user(session, test_session, role: UserRole) -> User:
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


def test_readonly_user_cannot_read_decrypted_secrets(client, test_session):
    from app.auth import get_current_user

    _seed_secret(test_session)
    readonly_user = _override_current_user(client, test_session, UserRole.READONLY)

    app.dependency_overrides[get_current_user] = lambda: readonly_user
    try:
        response = client.get("/api/secrets")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 403


def test_write_user_can_read_decrypted_secrets(client, test_session):
    from app.auth import get_current_user

    _seed_secret(test_session)
    write_user = _override_current_user(client, test_session, UserRole.WRITE)

    app.dependency_overrides[get_current_user] = lambda: write_user
    try:
        response = client.get("/api/secrets")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    body = response.json()
    assert any(s["key"] == "DB_PASSWORD" and s["value"] == "super-secret-value" for s in body["secrets"])
