"""
Tests für den Session-Cleanup-Job.

Der Job lief nie. startup.py übergab scheduler.add_job eine in
run_startup_tasks verschachtelte Funktion, und der Scheduler persistiert seine
Jobs im SQLAlchemyJobStore — er braucht dafür eine importierbare Referenz
(modul:name), die eine verschachtelte Funktion nicht hat. add_job lehnte den Job
ab, der Startup-Schritt wurde als "nicht kritisch" geloggt, und abgelaufene
Sessions und Ephemeral-Tokens blieben liegen.

Aufgefallen ist es erst im Boot-Log von Prod, und zwar an derselben Meldung, die
der neu dazugebaute pipeline_runs-Cleanup erzeugte — dessen Code war von hier
kopiert. Für die beiden Cleanup-Funktionen gab es bis dahin keine Tests.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.auth.auth import run_session_cleanup_job
from app.models import EphemeralToken, EphemeralTokenType, Session as SessionModel, User

PAST = datetime.now(timezone.utc) - timedelta(hours=1)
FUTURE = datetime.now(timezone.utc) + timedelta(hours=1)


def _user(session):
    user = User(username=f"u{uuid4().hex[:8]}", email=f"{uuid4().hex[:8]}@example.com")
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


# Die Helper geben die ID zurück, nicht die Zeile: run_session_cleanup_job
# schliesst seine Session, und ein danach noch gehaltenes ORM-Objekt wäre
# detached — jeder Attributzugriff darauf wirft DetachedInstanceError.
def _session_row_id(session, user, expires_at):
    row = SessionModel(token=f"tok-{uuid4()}", user_id=user.id, expires_at=expires_at)
    session.add(row)
    session.commit()
    return row.id


def _token_row_id(session, expires_at):
    row = EphemeralToken(
        token=f"eph-{uuid4()}",
        token_type=EphemeralTokenType.LOG_DOWNLOAD,
        subject=str(uuid4()),
        expires_at=expires_at,
    )
    session.add(row)
    session.commit()
    return row.id


def test_scheduler_callable_has_an_importable_reference():
    """
    obj_to_ref ist genau der Aufruf, an dem Job.__getstate__ gescheitert ist.

    Für eine verschachtelte Funktion wirft er "Cannot create a reference to a
    nested function". Der Startup-Pfad selbst ist in Tests abgeschaltet
    (config.TESTING), deshalb prüft der Test die Eigenschaft, an der es
    scheiterte.
    """
    from apscheduler.util import obj_to_ref

    assert obj_to_ref(run_session_cleanup_job) == "app.auth.auth:run_session_cleanup_job"


def test_expired_sessions_and_tokens_are_deleted(test_session, monkeypatch):
    """Was der Job tun soll — bis jetzt ungetestet, weil er nie lief."""
    monkeypatch.setattr("app.auth.auth.get_session", lambda: iter([test_session]))
    user = _user(test_session)
    session_id = _session_row_id(test_session, user, PAST)
    token_id = _token_row_id(test_session, PAST)

    run_session_cleanup_job()

    assert test_session.get(SessionModel, session_id) is None
    assert test_session.get(EphemeralToken, token_id) is None


def test_valid_sessions_and_tokens_are_kept(test_session, monkeypatch):
    monkeypatch.setattr("app.auth.auth.get_session", lambda: iter([test_session]))
    user = _user(test_session)
    session_id = _session_row_id(test_session, user, FUTURE)
    token_id = _token_row_id(test_session, FUTURE)

    run_session_cleanup_job()

    assert test_session.get(SessionModel, session_id) is not None
    assert test_session.get(EphemeralToken, token_id) is not None


class _FakeSession:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_entrypoint_closes_its_own_session(monkeypatch):
    """Der Scheduler ruft ohne Argumente auf — die Session muss von innen kommen."""
    session = _FakeSession()
    monkeypatch.setattr("app.auth.auth.get_session", lambda: iter([session]))
    monkeypatch.setattr("app.auth.auth.cleanup_expired_sessions", lambda s: None)
    monkeypatch.setattr("app.auth.auth.cleanup_expired_ephemeral_tokens", lambda s: None)

    run_session_cleanup_job()

    assert session.closed


def test_entrypoint_closes_the_session_on_error(monkeypatch):
    """Ein halbstündlicher Job darf pro Fehlschlag keine Session liegen lassen."""
    session = _FakeSession()
    monkeypatch.setattr("app.auth.auth.get_session", lambda: iter([session]))

    def _boom(_session):
        raise RuntimeError("DB weg")

    monkeypatch.setattr("app.auth.auth.cleanup_expired_sessions", _boom)

    with pytest.raises(RuntimeError):
        run_session_cleanup_job()

    assert session.closed
