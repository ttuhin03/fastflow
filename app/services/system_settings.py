"""SystemSettings singleton helpers."""

from sqlmodel import Session

from app.models import SystemSettings


def get_system_settings(session: Session) -> SystemSettings:
    """Read SystemSettings singleton (id=1). Creates with defaults if missing."""
    ss = session.get(SystemSettings, 1)
    if ss is None:
        ss = SystemSettings(
            id=1,
            is_setup_completed=False,
            enable_telemetry=False,
            enable_error_reporting=False,
            dependency_audit_enabled=True,
            dependency_audit_cron="0 3 * * *",
            ui_show_attribution=True,
            ui_show_version=True,
            show_unconfigured_oauth_on_login=True,
            ui_login_background="video",
        )
        session.add(ss)
        session.commit()
        session.refresh(ss)
    return ss
