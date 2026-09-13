"""GET /api/settings/system-status gibt Infrastrukturdetails nur an Admins.

Die Check-Werte sind Exception-Texte. Eine fehlgeschlagene DB-Verbindung liefert
darin Hostname, Port und Benutzernamen — bei Vault-Rotation einen dynamischen.
``redact_error`` existiert genau dafür und wird auf dem unauthentifizierten
``/ready`` seit jeher angewandt; hier fehlte es.

``GET /settings`` in derselben Datei verbirgt SMTP- und S3-Endpunkte vor
Nicht-Admins mit der Begründung, die Anzeige solle dem Least-Privilege-Prinzip
des Schreibzugriffs folgen. Für rohe DB-Fehlermeldungen galt das nicht.
"""

from uuid import uuid4

import pytest

from app.main import app
from app.auth import get_current_user
from app.models import User, UserRole, UserStatus

LEAKY_ERROR = (
    'connection to server at "db-prod-01.internal.example.com" (10.42.7.19), '
    'port 5432 failed: FATAL: password authentication failed for user "vault-dyn-x7f2"'
)


@pytest.fixture
def failing_checks(monkeypatch):
    """Stellt einen fehlgeschlagenen DB-Check mit realistischer Meldung."""
    import app.core.readiness as readiness

    monkeypatch.setattr(
        readiness,
        "run_readiness_checks",
        lambda: ({"database": LEAKY_ERROR, "disk_free_gb": 12.5}, False),
    )


def _user(test_session, role: UserRole) -> User:
    user = User(
        username=f"status-{uuid4().hex[:8]}",
        email=f"{uuid4().hex[:8]}@example.com",
        role=role,
        status=UserStatus.ACTIVE,
    )
    test_session.add(user)
    test_session.commit()
    test_session.refresh(user)
    return user


def _as(user: User):
    app.dependency_overrides[get_current_user] = lambda: user
    return lambda: app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.parametrize("role", [UserRole.READONLY, UserRole.WRITE])
def test_non_admins_do_not_see_infrastructure_details(
    client, test_session, failing_checks, role
):
    user = _user(test_session, role)
    clear = _as(user)
    try:
        body = client.get("/api/settings/system-status").json()
    finally:
        clear()

    database = body["checks"]["database"]
    assert "db-prod-01.internal.example.com" not in database
    assert "10.42.7.19" not in database
    assert "vault-dyn-x7f2" not in database
    # Der Nutzer soll trotzdem erkennen, dass die Datenbank das Problem ist.
    assert body["status"] == "not_ready"
    assert database != ""


def test_admins_still_see_the_full_message(client, test_session, failing_checks):
    """Für Admins ist der volle Text nützlich und steht ohnehin im Log."""
    admin = _user(test_session, UserRole.ADMIN)
    clear = _as(admin)
    try:
        body = client.get("/api/settings/system-status").json()
    finally:
        clear()

    assert body["checks"]["database"] == LEAKY_ERROR


def test_non_string_check_values_survive_redaction(client, test_session, failing_checks):
    """disk_free_gb und die Inode-Zähler sind Zahlen, keine Meldungen."""
    user = _user(test_session, UserRole.READONLY)
    clear = _as(user)
    try:
        body = client.get("/api/settings/system-status").json()
    finally:
        clear()

    assert body["checks"]["disk_free_gb"] == 12.5


def test_healthy_checks_are_unaffected(client, test_session, monkeypatch):
    """Im Normalfall steht dort 'ok' – das darf die Redaktion nicht verändern."""
    import app.core.readiness as readiness

    monkeypatch.setattr(
        readiness, "run_readiness_checks", lambda: ({"database": "ok", "docker": "ok"}, True)
    )
    user = _user(test_session, UserRole.READONLY)
    clear = _as(user)
    try:
        body = client.get("/api/settings/system-status").json()
    finally:
        clear()

    assert body["status"] == "ready"
    assert body["checks"] == {"database": "ok", "docker": "ok"}
