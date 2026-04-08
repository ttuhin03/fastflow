"""Unit-Tests für Audit-Helper und log_audit (ohne App-Lifespan / TestClient)."""

from sqlmodel import select

from app.models import AuditLogEntry, User, UserRole, UserStatus
from app.services.audit import log_audit


def test_build_system_settings_audit_details_detects_changes():
    from app.api.settings import _build_system_settings_audit_details

    before = {"enable_telemetry": False, "is_setup_completed": False}
    after = {"enable_telemetry": True, "is_setup_completed": False}
    d = _build_system_settings_audit_details(before, after)
    assert d is not None
    assert "enable_telemetry" in d["changed_fields"]


def test_build_orchestrator_settings_audit_details_secret_flags():
    from app.api.settings import _build_orchestrator_settings_audit_details

    before: dict = {}
    after = {"smtp_password_encrypted": "x"}
    d = _build_orchestrator_settings_audit_details(before, after)
    assert d is not None
    assert d.get("smtp_password_updated") is True
    assert d.get("changed_fields") == []


def test_log_audit_user_delete_persists(test_session):
    admin = User(
        username="adm",
        email="adm@example.com",
        role=UserRole.ADMIN,
        status=UserStatus.ACTIVE,
    )
    test_session.add(admin)
    test_session.commit()
    test_session.refresh(admin)

    log_audit(
        test_session,
        "user_delete",
        "user",
        "00000000-0000-0000-0000-000000000001",
        {"username": "gone"},
        admin,
    )

    rows = list(test_session.exec(select(AuditLogEntry).where(AuditLogEntry.action == "user_delete")).all())
    assert rows
    assert rows[-1].details.get("username") == "gone"
