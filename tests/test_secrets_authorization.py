"""
Regression-Test: GET /api/secrets darf entschlüsselte Klartext-Secrets nur
Administrator:innen ausliefern (TE-18).

Vorher war der Endpoint nur mit `get_current_user` geschützt (jeder eingeloggte
Nutzer, auch READONLY), obwohl er den gesamten globalen Secret-Store im
Klartext zurückgibt (API-Keys, DB-Credentials etc.), unabhängig davon, welcher
Pipeline/welchem Owner ein Secret gehört. Sowohl READONLY- als auch
WRITE-Nutzer müssen abgelehnt werden - nur ADMIN darf diesen Bulk-Read
ausführen.
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


def _get_as(client, user: User):
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        return client.get("/api/secrets")
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_readonly_user_cannot_read_secrets(client, test_session):
    _seed_secret(test_session)
    readonly_user = _make_user(test_session, UserRole.READONLY)

    response = _get_as(client, readonly_user)

    assert response.status_code == 403


def test_write_user_cannot_read_secrets(client, test_session):
    """Non-admin WRITE users must not see the global secret store either."""
    _seed_secret(test_session)
    write_user = _make_user(test_session, UserRole.WRITE)

    response = _get_as(client, write_user)

    assert response.status_code == 403


def test_admin_user_can_read_secrets(client, test_session):
    _seed_secret(test_session)
    admin_user = _make_user(test_session, UserRole.ADMIN)

    response = _get_as(client, admin_user)

    assert response.status_code == 200
    body = response.json()
    assert any(s["key"] == "DB_PASSWORD" and s["value"] == "super-secret-value" for s in body["secrets"])
