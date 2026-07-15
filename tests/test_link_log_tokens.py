"""
Regression-Tests: Account-Link- und Log-Download-Tokens sind jetzt DB-gebunden
statt rein selbst-verifizierende JWTs (siehe TE-15 / TE-11 Finding 2).

Vorher reichte eine gültige JWT-Signatur allein aus, um ein Account-Link- oder
Log-Download-Token zu erzeugen. War JWT_SECRET_KEY jemals schwach/geleakt, konnte
ein Angreifer mit Kenntnis einer user_id einen Account-Link-Token fälschen und so
ein fremdes Konto per OAuth-Account-Linking übernehmen. Jetzt muss das Token
zusätzlich einer echten, nicht abgelaufenen (und beim Account-Link auch noch nicht
eingelösten) Zeile in der `ephemeral_tokens`-Tabelle entsprechen.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from jose import jwt

from app.auth.auth import (
    create_link_token,
    create_log_download_token,
    verify_link_token,
    verify_log_download_token,
)
from app.core.config import config
from app.models import EphemeralToken, EphemeralTokenType, PipelineRun, RunStatus


def _make_run(test_session) -> PipelineRun:
    run = PipelineRun(
        pipeline_name="demo",
        status=RunStatus.SUCCESS,
        log_file="/tmp/demo.log",
    )
    test_session.add(run)
    test_session.commit()
    test_session.refresh(run)
    return run


def test_link_token_round_trip_and_single_use(test_session, test_user):
    token = create_link_token(test_session, test_user.id)

    assert verify_link_token(test_session, token) == test_user.id
    # Single-use: der zweite Versuch mit demselben Token schlägt fehl.
    assert verify_link_token(test_session, token) is None


def test_link_token_expired_is_rejected(test_session, test_user):
    expired = EphemeralToken(
        token="expired-link-token",
        token_type=EphemeralTokenType.ACCOUNT_LINK,
        subject=str(test_user.id),
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    test_session.add(expired)
    test_session.commit()

    assert verify_link_token(test_session, "expired-link-token") is None


def test_link_token_forged_jwt_is_rejected(test_session, test_user):
    """
    Simuliert die alte Angriffsflaeche: ein Angreifer, der JWT_SECRET_KEY kennt
    (z.B. weil er schwach/geleakt ist), kann kein gueltiges Account-Link-Token mehr
    faelschen, weil verify_link_token jetzt eine echte DB-Zeile verlangt statt nur
    die Signatur zu pruefen.
    """
    forged = jwt.encode(
        {
            "sub": str(test_user.id),
            "exp": datetime.now(timezone.utc) + timedelta(seconds=60),
            "type": "account_link",
        },
        config.JWT_SECRET_KEY,
        algorithm=config.JWT_ALGORITHM,
    )

    assert verify_link_token(test_session, forged) is None


def test_log_download_token_multi_use_within_ttl(test_session):
    run = _make_run(test_session)
    token = create_log_download_token(test_session, run.id)

    assert verify_log_download_token(test_session, token, run.id) is True
    # Mehrfach nutzbar innerhalb der TTL (kein Single-Use, um den im Frontend
    # kurz gecachten Download-Link nicht zu brechen).
    assert verify_log_download_token(test_session, token, run.id) is True


def test_log_download_token_wrong_run_id_is_rejected(test_session):
    run = _make_run(test_session)
    other_run_id = uuid4()
    token = create_log_download_token(test_session, run.id)

    assert verify_log_download_token(test_session, token, other_run_id) is False


def test_log_download_token_expired_is_rejected(test_session):
    run = _make_run(test_session)
    expired = EphemeralToken(
        token="expired-log-token",
        token_type=EphemeralTokenType.LOG_DOWNLOAD,
        subject=str(run.id),
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    test_session.add(expired)
    test_session.commit()

    assert verify_log_download_token(test_session, "expired-log-token", run.id) is False


def test_log_download_token_forged_jwt_is_rejected(test_session):
    run = _make_run(test_session)
    forged = jwt.encode(
        {
            "sub": str(run.id),
            "exp": datetime.now(timezone.utc) + timedelta(seconds=60),
            "type": "log_download",
        },
        config.JWT_SECRET_KEY,
        algorithm=config.JWT_ALGORITHM,
    )

    assert verify_log_download_token(test_session, forged, run.id) is False
