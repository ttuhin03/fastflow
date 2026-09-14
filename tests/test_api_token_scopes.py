"""Integrationstests: API-Tokens gegen die tatsächlichen Lese-Endpoints.

tests/test_api_tokens.py prüft Erzeugung, Auflösung und Widerruf. Hier geht es
um die Wirkung: welcher Scope öffnet welchen Endpoint, und was passiert mit
Nutzdaten, wenn der passende Scope fehlt.
"""

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlmodel import select

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


def _token(
    test_session, user: User, *scopes: ApiTokenScope, expires_in_days: int = 1
) -> str:
    generated = generate_api_token()
    now = datetime.now(timezone.utc)
    test_session.add(
        ApiToken(
            token_hash=generated.token_hash,
            prefix=generated.prefix,
            label="scope test",
            user_id=user.id,
            scopes=[s.value for s in scopes],
            expires_at=now + timedelta(days=expires_in_days),
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


def _as_session_user(user: User):
    """Überschreibt die Session-Authentifizierung für die /api/tokens-Endpoints."""
    from app.main import app
    from app.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: user
    return lambda: app.dependency_overrides.pop(get_current_user, None)


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


# --------------------------------------------------------------------------- #
# run: schreibende Endpoints
# --------------------------------------------------------------------------- #


def _running_run(test_session) -> PipelineRun:
    run = PipelineRun(
        id=uuid4(),
        pipeline_name="etl",
        status=RunStatus.RUNNING,
        log_file="/logs/etl.log",
        started_at=datetime.now(timezone.utc),
    )
    test_session.add(run)
    test_session.commit()
    test_session.refresh(run)
    return run


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/pipelines/etl/run"),
        ("post", "/api/runs/{run_id}/cancel"),
        ("post", "/api/runs/{run_id}/retry"),
    ],
)
def test_write_endpoints_require_the_run_scope(client, test_session, method, path):
    """Ein Token ohne run kommt nicht einmal in den Handler."""
    user = _user(test_session, UserRole.WRITE)
    token = _token(test_session, user, ApiTokenScope.READ, ApiTokenScope.LOGS)
    run = _running_run(test_session)

    response = getattr(client, method)(
        path.format(run_id=run.id), json={}, headers=_auth(token)
    )

    assert response.status_code == 403
    assert "run" in response.json()["detail"]


def test_readonly_user_can_never_reach_a_write_endpoint(client, test_session):
    """Selbst wenn run in der Token-Zeile steht: die Rolle streicht ihn."""
    user = _user(test_session, UserRole.READONLY)
    token = _token(test_session, user, ApiTokenScope.READ, ApiTokenScope.RUN)
    run = _running_run(test_session)

    response = client.post(f"/api/runs/{run.id}/cancel", headers=_auth(token))

    assert response.status_code == 403


def test_cancel_with_run_scope_succeeds_and_is_attributed(
    client, test_session, monkeypatch
):
    """Der Audit-Eintrag muss erkennen lassen, dass ein Token gehandelt hat.

    Ohne diese Attribution steht im Log nur der Benutzername – und mit
    wachsender Automatisierung ließe sich nicht mehr unterscheiden, ob ein
    Mensch im Browser oder ein CI-Job den Run abgebrochen hat.
    """
    from app.models import AuditLogEntry
    import app.api.runs as runs_api

    async def fake_cancel(run_id, session):
        return True

    monkeypatch.setattr(runs_api, "cancel_run", fake_cancel)

    user = _user(test_session, UserRole.WRITE)
    token = _token(test_session, user, ApiTokenScope.RUN)
    run = _running_run(test_session)

    response = client.post(f"/api/runs/{run.id}/cancel", headers=_auth(token))

    assert response.status_code == 200
    entry = test_session.exec(
        select(AuditLogEntry).where(AuditLogEntry.action == "run_cancel")
    ).first()
    assert entry is not None
    assert entry.username == user.username
    assert entry.details["auth_kind"] == "token"
    assert entry.details["token_label"] == "scope test"
    assert "token_id" in entry.details


def test_browser_session_is_attributed_as_session(
    authenticated_client, test_session, monkeypatch
):
    from app.models import AuditLogEntry
    import app.api.runs as runs_api

    async def fake_cancel(run_id, session):
        return True

    monkeypatch.setattr(runs_api, "cancel_run", fake_cancel)
    run = _running_run(test_session)

    response = authenticated_client.post(f"/api/runs/{run.id}/cancel")

    assert response.status_code == 200
    entry = test_session.exec(
        select(AuditLogEntry).where(AuditLogEntry.action == "run_cancel")
    ).first()
    assert entry.details["auth_kind"] == "session"
    assert "token_id" not in entry.details


# --------------------------------------------------------------------------- #
# Metadaten-Filter: der webhook_key ist ein Credential
# --------------------------------------------------------------------------- #


def _pipeline_with_metadata(temp_pipelines_dir) -> None:
    """Legt eine Pipeline mit Webhook-Key und Env-Overrides an.

    Nutzt die temp_pipelines_dir-Fixture und force_refresh wie die übrigen
    Pipeline-Tests – die Discovery cached sonst über Testgrenzen hinweg.
    """
    from app.services.pipeline_discovery import discover_pipelines

    pdir = temp_pipelines_dir / "leaky"
    pdir.mkdir()
    (pdir / "main.py").write_text("print('hi')\n")
    (pdir / "pipeline.json").write_text(json.dumps({
        "name": "leaky",
        "webhook_key": "SUPER-SECRET-WEBHOOK-KEY",
        "default_env": {"PLAIN": "wert"},
        "encrypted_env": {"DB_PASS": "gAAAAAB..."},
        "secrets": ["API_TOKEN"],
        "schedules": [{"id": "s1", "cron": "0 3 * * *", "webhook_key": "ZWEITER-KEY"}],
    }))
    discover_pipelines(force_refresh=True)


def test_webhook_key_is_never_handed_to_a_token(client, test_session, temp_pipelines_dir):
    """Der webhook_key umgeht die Authentifizierung vollständig.

    POST /webhooks/{pipeline}/{key} hat keine Auth-Dependency – wer den Key
    lesen kann, startet Runs ohne jeden Scope. Ein read-Token darf ihn deshalb
    unter keinen Umständen sehen.
    """
    _pipeline_with_metadata(temp_pipelines_dir)
    user = _user(test_session, UserRole.WRITE)
    token = _token(test_session, user, ApiTokenScope.READ, ApiTokenScope.SOURCE,
                   ApiTokenScope.RUN)

    body = client.get("/api/pipelines", headers=_auth(token)).json()

    raw = json.dumps(body)
    assert "SUPER-SECRET-WEBHOOK-KEY" not in raw
    assert "ZWEITER-KEY" not in raw, "schedules[] tragen eigene Keys"


def test_source_derived_metadata_needs_the_source_scope(client, test_session, temp_pipelines_dir):
    """encrypted_env, secrets und default_env stammen aus pipeline.json.

    Ohne diesen Filter käme der Inhalt der Datei, die /source hinter dem
    source-Scope schützt, einfach über /pipelines heraus.
    """
    _pipeline_with_metadata(temp_pipelines_dir)
    user = _user(test_session, UserRole.WRITE)

    read_only = _token(test_session, user, ApiTokenScope.READ)
    without = json.dumps(client.get("/api/pipelines", headers=_auth(read_only)).json())
    assert "DB_PASS" not in without
    assert "API_TOKEN" not in without
    assert "PLAIN" not in without

    with_source = _token(test_session, user, ApiTokenScope.READ, ApiTokenScope.SOURCE)
    got = json.dumps(client.get("/api/pipelines", headers=_auth(with_source)).json())
    assert "DB_PASS" in got
    assert "PLAIN" in got


def test_browser_session_keeps_the_full_metadata(authenticated_client, temp_pipelines_dir):
    """Die UI zeigt Webhook-URLs und Env-Chips – sie darf nicht still verarmen."""
    _pipeline_with_metadata(temp_pipelines_dir)

    raw = json.dumps(authenticated_client.get("/api/pipelines").json())

    assert "SUPER-SECRET-WEBHOOK-KEY" in raw
    assert "DB_PASS" in raw


def test_dependencies_expose_requirements_and_need_source(client, test_session):
    """/dependencies liefert den Inhalt von requirements.txt – also source."""
    user = _user(test_session, UserRole.WRITE)
    token = _token(test_session, user, ApiTokenScope.READ)

    response = client.get("/api/pipelines/etl/dependencies", headers=_auth(token))

    assert response.status_code == 403
    assert "source" in response.json()["detail"]


# --------------------------------------------------------------------------- #
# Zeitstempel und Download-Fallback
# --------------------------------------------------------------------------- #


def test_token_timestamps_carry_a_utc_offset(client, test_session):
    """Ohne Offset liest new Date() den Wert als Lokalzeit (ECMA-262)."""
    user = _user(test_session, UserRole.WRITE)
    clear = _as_session_user(user)
    try:
        created = client.post(
            "/api/tokens", json={"label": "zeit", "scopes": ["read"]}
        ).json()
        listed = client.get("/api/tokens").json()["tokens"][0]
    finally:
        clear()

    for value in (created["expires_at"], listed["expires_at"], listed["created_at"]):
        assert value.endswith("+00:00"), f"kein UTC-Offset: {value}"


def test_download_token_still_works_alongside_a_useless_bearer(
    client, test_session, tmp_path, monkeypatch
):
    """Ein abgelaufenes Token im Header darf den Direkt-Download nicht sperren.

    Vorher brach der Token-Zweig die Kette ab: derselbe Aufruf gelang mit einem
    *unbrauchbaren* Header und scheiterte mit einem abgelaufenen – ein Client
    mit pauschalem Authorization-Header verlor den Download beim Ablauf.
    """
    from app.auth.auth import create_log_download_token
    from app.core.config import config

    logdir = tmp_path / "logs"
    logdir.mkdir()
    monkeypatch.setattr(config, "LOGS_DIR", logdir)

    user = _user(test_session, UserRole.WRITE)
    expired = _token(test_session, user, ApiTokenScope.LOGS, expires_in_days=-1)

    run = PipelineRun(
        id=uuid4(), pipeline_name="etl", status=RunStatus.SUCCESS,
        log_file=str(logdir / "run.log"), started_at=datetime.now(timezone.utc),
    )
    (logdir / "run.log").write_text("Zeile eins\nZeile zwei\n")
    test_session.add(run)
    test_session.commit()

    dl = create_log_download_token(test_session, run.id)
    url = f"/api/runs/{run.id}/logs?download_token={dl}"

    assert client.get(url).status_code == 200
    assert client.get(url, headers=_auth("Bearer-Muell")).status_code == 200
    # Der entscheidende Fall: gültiger Download-Token, abgelaufenes API-Token.
    assert client.get(url, headers=_auth(expired)).status_code == 200
