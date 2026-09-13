"""Integrationstests: API-Tokens gegen die tatsächlichen Lese-Endpoints.

tests/test_api_tokens.py prüft Erzeugung, Auflösung und Widerruf. Hier geht es
um die Wirkung: welcher Scope öffnet welchen Endpoint, und was passiert mit
Nutzdaten, wenn der passende Scope fehlt.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.core.api_token_hash import generate_api_token
from app.models import (
    ApiToken,
    ApiTokenScope,
    PipelineRun,
    RunCellLog,
    RunStatus,
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
        username=f"scoped-{uuid4().hex[:8]}",
        email=f"{uuid4().hex[:8]}@example.com",
        role=role,
        status=UserStatus.ACTIVE,
    )
    test_session.add(user)
    test_session.commit()
    test_session.refresh(user)
    return user


def _token(test_session, user: User, *scopes: ApiTokenScope) -> str:
    generated = generate_api_token()
    now = datetime.now(timezone.utc)
    test_session.add(
        ApiToken(
            token_hash=generated.token_hash,
            prefix=generated.prefix,
            label="scope test",
            user_id=user.id,
            scopes=[s.value for s in scopes],
            expires_at=now + timedelta(days=1),
            created_at=now,
        )
    )
    test_session.commit()
    return generated.token


def _run(test_session, *, with_cells: bool = False) -> PipelineRun:
    run = PipelineRun(
        id=uuid4(),
        pipeline_name="etl",
        status=RunStatus.FAILED,
        log_file="/logs/etl.log",
        started_at=datetime.now(timezone.utc),
        exit_code=1,
    )
    test_session.add(run)
    test_session.commit()
    if with_cells:
        test_session.add(
            RunCellLog(
                run_id=run.id,
                cell_index=0,
                status="failed",
                stdout="geheime Ausgabe der Zelle",
                stderr="",
            )
        )
        test_session.commit()
    test_session.refresh(run)
    return run


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# read
# --------------------------------------------------------------------------- #


def test_read_scope_opens_the_run_list(client, test_session):
    user = _user(test_session)
    token = _token(test_session, user, ApiTokenScope.READ)
    _run(test_session)

    response = client.get("/api/runs", headers=_auth(token))

    assert response.status_code == 200
    assert response.json()["total"] == 1


def test_read_scope_opens_the_pipeline_list(client, test_session):
    user = _user(test_session)
    token = _token(test_session, user, ApiTokenScope.READ)

    assert client.get("/api/pipelines", headers=_auth(token)).status_code == 200


def test_without_read_scope_the_run_list_is_closed(client, test_session):
    user = _user(test_session)
    token = _token(test_session, user, ApiTokenScope.LOGS)

    response = client.get("/api/runs", headers=_auth(token))

    assert response.status_code == 403
    assert "read" in response.json()["detail"]


def test_no_token_no_access(client, test_session):
    _run(test_session)

    assert client.get("/api/runs").status_code == 401


# --------------------------------------------------------------------------- #
# logs
# --------------------------------------------------------------------------- #


def test_logs_scope_is_required_for_the_log_endpoint(client, test_session, tmp_path):
    user = _user(test_session)
    token = _token(test_session, user, ApiTokenScope.READ)
    run = _run(test_session)

    response = client.get(f"/api/runs/{run.id}/logs", headers=_auth(token))

    assert response.status_code == 403
    assert "logs" in response.json()["detail"]


def test_cell_output_is_withheld_without_the_logs_scope(client, test_session):
    """Der read-Scope öffnet das Run-Detail, aber nicht die Zell-Ausgaben.

    Ohne diese Trennung wäre der logs-Scope wirkungslos: derselbe Inhalt käme
    einfach über das Run-Detail heraus.
    """
    user = _user(test_session)
    token = _token(test_session, user, ApiTokenScope.READ)
    run = _run(test_session, with_cells=True)

    body = client.get(f"/api/runs/{run.id}", headers=_auth(token)).json()

    assert body["status"] == "FAILED"          # Metadaten bleiben nutzbar
    assert body["cell_logs"] == []
    assert body["cell_logs_withheld"] is True


def test_cell_output_is_returned_with_the_logs_scope(client, test_session):
    user = _user(test_session)
    token = _token(test_session, user, ApiTokenScope.READ, ApiTokenScope.LOGS)
    run = _run(test_session, with_cells=True)

    body = client.get(f"/api/runs/{run.id}", headers=_auth(token)).json()

    assert body["cell_logs_withheld"] is False
    assert body["cell_logs"][0]["stdout"] == "geheime Ausgabe der Zelle"


def test_browser_session_always_sees_cell_output(authenticated_client, test_session):
    """Die UI ist von der Scope-Trennung nicht betroffen.

    Eine Session erhält alle Scopes ihrer Rolle – sonst wäre die Umstellung
    eine stille Funktionsminderung im Frontend.
    """
    run = _run(test_session, with_cells=True)

    body = authenticated_client.get(f"/api/runs/{run.id}").json()

    assert body["cell_logs_withheld"] is False
    assert body["cell_logs"][0]["stdout"] == "geheime Ausgabe der Zelle"


# --------------------------------------------------------------------------- #
# source
# --------------------------------------------------------------------------- #


def test_source_scope_is_required_for_source_files(client, test_session):
    user = _user(test_session)
    token = _token(test_session, user, ApiTokenScope.READ, ApiTokenScope.LOGS)

    response = client.get("/api/pipelines/etl/source", headers=_auth(token))

    assert response.status_code == 403
    assert "source" in response.json()["detail"]


# --------------------------------------------------------------------------- #
# Der Nutzer bleibt die Obergrenze
# --------------------------------------------------------------------------- #


def test_blocking_a_user_invalidates_their_tokens_immediately(client, test_session):
    """Ein gesperrter Nutzer verliert den Zugriff, ohne dass Tokens einzeln
    widerrufen werden müssen – dieselbe Prüfung wie im Session-Pfad."""
    user = _user(test_session)
    token = _token(test_session, user, ApiTokenScope.READ)
    _run(test_session)
    assert client.get("/api/runs", headers=_auth(token)).status_code == 200

    user.blocked = True
    test_session.add(user)
    test_session.commit()

    assert client.get("/api/runs", headers=_auth(token)).status_code == 401


def test_readonly_role_caps_what_a_token_can_do(client, test_session):
    """Die Rolle begrenzt den Scope auch dann, wenn er in der Zeile steht.

    Das Token trägt run; READONLY lässt das nicht zu. Übrig bleibt read –
    lesen geht also weiter, der überschüssige Scope verpufft.
    """
    user = _user(test_session, UserRole.READONLY)
    token = _token(test_session, user, ApiTokenScope.READ, ApiTokenScope.RUN)
    _run(test_session)

    assert client.get("/api/runs", headers=_auth(token)).status_code == 200
