"""
Regression-Test: GET /api/users darf nicht an alle eingeloggten Nutzer ausliefern.

Vorher war der Endpoint nur mit `get_current_user` geschützt (jeder eingeloggte
Nutzer, auch READONLY), obwohl er UUID, E-Mail und OAuth-Verknüpfungen aller
Benutzer zurückgibt (User-Enumeration, siehe TE-15 / TE-11).
"""

from app.main import app
from app.models import User, UserRole, UserStatus


def _override_current_user(test_session, role: UserRole) -> User:
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


def test_readonly_user_cannot_list_users(client, test_session):
    from app.auth import get_current_user

    readonly_user = _override_current_user(test_session, UserRole.READONLY)

    app.dependency_overrides[get_current_user] = lambda: readonly_user
    try:
        response = client.get("/api/users")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 403


def test_write_user_cannot_list_users(client, test_session):
    from app.auth import get_current_user

    write_user = _override_current_user(test_session, UserRole.WRITE)

    app.dependency_overrides[get_current_user] = lambda: write_user
    try:
        response = client.get("/api/users")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 403


def test_admin_user_can_list_users(client, test_session):
    from app.auth import get_current_user

    admin_user = _override_current_user(test_session, UserRole.ADMIN)

    app.dependency_overrides[get_current_user] = lambda: admin_user
    try:
        response = client.get("/api/users")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    usernames = {u["username"] for u in response.json()}
    assert admin_user.username in usernames
