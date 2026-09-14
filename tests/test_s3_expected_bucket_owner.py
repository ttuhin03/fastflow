"""
Tests für ExpectedBucketOwner bei S3-Operationen.

S3_EXPECTED_BUCKET_OWNER ist bewusst optional: Ist die Account-ID gesetzt, muss
sie an jeder Operation hängen (Schutz gegen Bucket-Sniping); ist sie leer, darf
der Parameter nicht mitgeschickt werden, sonst brechen MinIO-Deployments.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.core.config import config
from app.main import app
from app.services.s3_backup import S3BackupService, bucket_owner_kwargs


@pytest.fixture
def expected_owner():
    """Setzt S3_EXPECTED_BUCKET_OWNER für einen Test und stellt den Wert danach zurück."""
    previous = getattr(config, "S3_EXPECTED_BUCKET_OWNER", None)

    def _set(value):
        config.S3_EXPECTED_BUCKET_OWNER = value

    yield _set
    config.S3_EXPECTED_BUCKET_OWNER = previous


def test_bucket_owner_kwargs_empty_when_unset(expected_owner):
    expected_owner(None)
    assert bucket_owner_kwargs() == {}


def test_bucket_owner_kwargs_empty_for_blank_value(expected_owner):
    # Leerer Env-Wert darf nicht als "gesetzt" durchgehen (sonst 400 von S3)
    expected_owner("")
    assert bucket_owner_kwargs() == {}


def test_bucket_owner_kwargs_set_when_configured(expected_owner):
    expected_owner("123456789012")
    assert bucket_owner_kwargs() == {"ExpectedBucketOwner": "123456789012"}


def _upload(tmp_path: Path, monkeypatch) -> MagicMock:
    """Führt _upload_file_streaming gegen einen Mock-Client aus und gibt ihn zurück."""
    client = MagicMock()
    monkeypatch.setattr("app.services.s3_backup._get_client", lambda: client)

    log = tmp_path / "run.log"
    log.write_text("line\n")
    S3BackupService()._upload_file_streaming(
        log, "fastflow-logs", "pipeline-logs/p/1/run.log", {"run_id": "1"}
    )
    return client


def test_upload_sends_expected_bucket_owner(tmp_path, monkeypatch, expected_owner):
    expected_owner("123456789012")
    client = _upload(tmp_path, monkeypatch)

    extra_args = client.upload_fileobj.call_args.kwargs["ExtraArgs"]
    assert extra_args["ExpectedBucketOwner"] == "123456789012"
    # Metadaten dürfen durch das Merge nicht verloren gehen
    assert extra_args["Metadata"] == {"run_id": "1"}


def test_upload_omits_expected_bucket_owner_when_unset(tmp_path, monkeypatch, expected_owner):
    expected_owner(None)
    client = _upload(tmp_path, monkeypatch)

    extra_args = client.upload_fileobj.call_args.kwargs["ExtraArgs"]
    assert "ExpectedBucketOwner" not in extra_args
    assert extra_args["Metadata"] == {"run_id": "1"}


@pytest.fixture
def admin_client(client, test_session, test_user):
    """Test-Client mit Admin-Override für POST /api/settings/s3/test."""
    from app.auth import get_current_user, require_admin

    app.dependency_overrides[get_current_user] = lambda: test_user
    app.dependency_overrides[require_admin] = lambda: test_user
    yield client
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(require_admin, None)


@pytest.fixture
def s3_configured(monkeypatch):
    """Setzt eine vollständige S3-Konfiguration, damit der Test bis HeadBucket kommt."""
    monkeypatch.setattr(config, "S3_BACKUP_ENABLED", True)
    monkeypatch.setattr(config, "S3_ENDPOINT_URL", "https://s3.eu-central-1.amazonaws.com")
    monkeypatch.setattr(config, "S3_BUCKET", "fastflow-logs")
    monkeypatch.setattr(config, "S3_ACCESS_KEY", "key")
    monkeypatch.setattr(config, "S3_SECRET_ACCESS_KEY", "secret")


def _head_bucket_raising(status_code: int, monkeypatch) -> MagicMock:
    """Verdrahtet boto3.client so, dass head_bucket einen ClientError wirft."""
    from botocore.exceptions import ClientError

    boto_client = MagicMock()
    boto_client.head_bucket.side_effect = ClientError(
        {
            "Error": {"Code": "AccessDenied", "Message": "Access Denied"},
            "ResponseMetadata": {"HTTPStatusCode": status_code},
        },
        "HeadBucket",
    )
    monkeypatch.setattr("app.api.settings.boto3.client", lambda *a, **kw: boto_client)
    return boto_client


def test_connectivity_test_sends_expected_bucket_owner(
    admin_client, s3_configured, monkeypatch, expected_owner
):
    expected_owner("123456789012")
    boto_client = MagicMock()
    monkeypatch.setattr("app.api.settings.boto3.client", lambda *a, **kw: boto_client)

    response = admin_client.post("/api/settings/s3/test")

    assert response.status_code == 200
    assert boto_client.head_bucket.call_args.kwargs["ExpectedBucketOwner"] == "123456789012"


def test_connectivity_test_omits_expected_bucket_owner_when_unset(
    admin_client, s3_configured, monkeypatch, expected_owner
):
    expected_owner(None)
    boto_client = MagicMock()
    monkeypatch.setattr("app.api.settings.boto3.client", lambda *a, **kw: boto_client)

    response = admin_client.post("/api/settings/s3/test")

    assert response.status_code == 200
    assert "ExpectedBucketOwner" not in boto_client.head_bucket.call_args.kwargs


def test_connectivity_test_403_names_bucket_owner_mismatch(
    admin_client, s3_configured, monkeypatch, expected_owner
):
    expected_owner("123456789012")
    _head_bucket_raising(403, monkeypatch)

    response = admin_client.post("/api/settings/s3/test")

    assert response.status_code == 400
    assert "S3_EXPECTED_BUCKET_OWNER" in response.json()["detail"]


def test_connectivity_test_403_stays_generic_without_expected_owner(
    admin_client, s3_configured, monkeypatch, expected_owner
):
    expected_owner(None)
    _head_bucket_raising(403, monkeypatch)

    response = admin_client.post("/api/settings/s3/test")

    assert response.status_code == 400
    assert "S3_EXPECTED_BUCKET_OWNER" not in response.json()["detail"]


def test_connectivity_test_non_403_stays_generic(
    admin_client, s3_configured, monkeypatch, expected_owner
):
    # 404 (Bucket fehlt) darf nicht als Owner-Mismatch fehlgedeutet werden
    expected_owner("123456789012")
    _head_bucket_raising(404, monkeypatch)

    response = admin_client.post("/api/settings/s3/test")

    assert response.status_code == 400
    assert "S3_EXPECTED_BUCKET_OWNER" not in response.json()["detail"]
