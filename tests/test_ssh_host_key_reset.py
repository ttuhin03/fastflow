"""
Tests für den admin-gesteuerten SSH-Host-Key-Reset (TE-73, Follow-up zu TE-23).

Deckt ab:
- URL-Parsing (scp-like und ssh://)
- Status: kein Mismatch / Mismatch / nicht zuständig (GIT_SSH_KNOWN_HOSTS per Env, kein Repo, HTTPS-Repo)
- Reset: falsche Bestätigung wird abgelehnt, korrekter Reset entfernt alten Key und pinnt neuen
- API: Endpoints sind admin-only

Netzwerkzugriffe (ssh-keyscan) werden über _ssh_keyscan_raw gemockt, damit die Tests
deterministisch und offline laufen. ssh-keygen -F/-R laufen echt gegen eine
tmp_path-known_hosts-Datei (rein lokale Dateioperationen, kein Netzwerk).
"""

import subprocess

import pytest

from app.core.config import config
from app.services import ssh_host_key as svc


def _pin(known_hosts_path, host, key_type, key_b64):
    """Pinnt einen Host-Key wie es _ssh_key_env/accept-new tun würde (echtes ssh-keyscan-Format)."""
    known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
    with open(known_hosts_path, "a") as f:
        f.write(f"{host} {key_type} {key_b64}\n")


# Echte (aber beliebig generierte, nicht sicherheitsrelevante) Ed25519-Public-Key-Blobs,
# damit ssh-keygen -lf (echt, kein Mock) die Fingerprints berechnen kann.
OLD_ED25519 = "AAAAC3NzaC1lZDI1NTE5AAAAIHUrNTYmoPjerg2eOqKooVWrWWgEFdyp6AkUu7XiCkSi"
NEW_ED25519 = "AAAAC3NzaC1lZDI1NTE5AAAAIC4p3piOhLZ8VvE9TQ2bcRzFOucAD9B9YCyJ7cN/prhA"


@pytest.fixture
def repo_config(monkeypatch):
    monkeypatch.setattr(
        svc, "get_sync_repo_config",
        lambda session: {"repo_url": "git@github.com:acme/pipelines.git", "branch": "main"},
    )


@pytest.fixture
def known_hosts(temp_data_dir, monkeypatch):
    monkeypatch.setattr(config, "GIT_SSH_KNOWN_HOSTS", None)
    return temp_data_dir / "ssh_known_hosts"


class TestParseSshHost:
    def test_scp_like(self):
        assert svc._parse_ssh_host("git@github.com:acme/repo.git") == ("github.com", 22)

    def test_ssh_url_with_port(self):
        assert svc._parse_ssh_host("ssh://git@example.com:2222/acme/repo.git") == ("example.com", 2222)

    def test_ssh_url_default_port(self):
        assert svc._parse_ssh_host("ssh://git@example.com/acme/repo.git") == ("example.com", 22)

    def test_https_returns_none(self):
        assert svc._parse_ssh_host("https://github.com/acme/repo.git") is None


class TestGetHostKeyStatus:
    def test_not_applicable_when_env_known_hosts_set(self, test_session, monkeypatch):
        monkeypatch.setattr(config, "GIT_SSH_KNOWN_HOSTS", "github.com ssh-ed25519 AAAA...")
        result = svc.get_host_key_status(test_session)
        assert result["applicable"] is False
        assert "GIT_SSH_KNOWN_HOSTS" in result["reason"]

    def test_not_applicable_when_no_repo_configured(self, test_session, known_hosts, monkeypatch):
        monkeypatch.setattr(svc, "get_sync_repo_config", lambda session: None)
        result = svc.get_host_key_status(test_session)
        assert result["applicable"] is False

    def test_not_applicable_for_https_repo(self, test_session, known_hosts, monkeypatch):
        monkeypatch.setattr(
            svc, "get_sync_repo_config",
            lambda session: {"repo_url": "https://github.com/acme/repo.git", "branch": "main"},
        )
        result = svc.get_host_key_status(test_session)
        assert result["applicable"] is False

    def test_no_mismatch_when_keys_match(self, test_session, repo_config, known_hosts, monkeypatch):
        _pin(known_hosts, "github.com", "ssh-ed25519", OLD_ED25519)
        monkeypatch.setattr(
            svc, "_ssh_keyscan_raw",
            lambda host, port, hashed=False: ([f"github.com ssh-ed25519 {OLD_ED25519}"], None),
        )
        result = svc.get_host_key_status(test_session)
        assert result["applicable"] is True
        assert result["pinned"] is True
        assert result["mismatch"] is False
        assert result["entries"][0]["matches"] is True

    def test_mismatch_when_key_rotated(self, test_session, repo_config, known_hosts, monkeypatch):
        _pin(known_hosts, "github.com", "ssh-ed25519", OLD_ED25519)
        monkeypatch.setattr(
            svc, "_ssh_keyscan_raw",
            lambda host, port, hashed=False: ([f"github.com ssh-ed25519 {NEW_ED25519}"], None),
        )
        result = svc.get_host_key_status(test_session)
        assert result["mismatch"] is True
        entry = result["entries"][0]
        assert entry["old_fingerprint"] != entry["new_fingerprint"]
        assert entry["matches"] is False

    def test_no_pinned_entry_yet(self, test_session, repo_config, known_hosts, monkeypatch):
        monkeypatch.setattr(
            svc, "_ssh_keyscan_raw",
            lambda host, port, hashed=False: ([f"github.com ssh-ed25519 {NEW_ED25519}"], None),
        )
        result = svc.get_host_key_status(test_session)
        assert result["pinned"] is False
        assert result["mismatch"] is False


class TestResetPinnedHostKey:
    def test_rejects_wrong_confirmation(self, test_session, repo_config, known_hosts, monkeypatch):
        _pin(known_hosts, "github.com", "ssh-ed25519", OLD_ED25519)
        monkeypatch.setattr(
            svc, "_ssh_keyscan_raw",
            lambda host, port, hashed=False: ([f"github.com ssh-ed25519 {NEW_ED25519}"], None),
        )
        with pytest.raises(ValueError, match="stimmt nicht"):
            svc.reset_pinned_host_key(test_session, "not-the-repo-url")

    def test_rejects_when_not_applicable(self, test_session, known_hosts, monkeypatch):
        monkeypatch.setattr(svc, "get_sync_repo_config", lambda session: None)
        with pytest.raises(ValueError):
            svc.reset_pinned_host_key(test_session, "git@github.com:acme/pipelines.git")

    def test_reset_replaces_old_key_with_new(self, test_session, repo_config, known_hosts, monkeypatch):
        _pin(known_hosts, "github.com", "ssh-ed25519", OLD_ED25519)
        monkeypatch.setattr(
            svc, "_ssh_keyscan_raw",
            lambda host, port, hashed=False: ([f"github.com ssh-ed25519 {NEW_ED25519}"], None),
        )
        result = svc.reset_pinned_host_key(test_session, "git@github.com:acme/pipelines.git")

        assert result["host"] == "github.com"
        assert len(result["old_entries"]) == 1
        assert result["old_entries"][0]["fingerprint"] != result["new_entries"][0]["fingerprint"]

        # Alter Key darf nicht mehr im known_hosts stehen; ssh-keygen -F -l muss den
        # neuen (gehashten) Eintrag mit dem korrekten Fingerprint finden.
        found = subprocess.run(
            ["ssh-keygen", "-F", "github.com", "-f", str(known_hosts), "-l"],
            capture_output=True, text=True,
        )
        assert OLD_ED25519 not in known_hosts.read_text()
        assert result["new_entries"][0]["fingerprint"] in found.stdout

        # Status danach zeigt keinen Mismatch mehr.
        status_after = svc.get_host_key_status(test_session)
        assert status_after["mismatch"] is False
        assert status_after["entries"][0]["old_fingerprint"] == status_after["entries"][0]["new_fingerprint"]

    def test_reset_fails_if_current_scan_fails(self, test_session, repo_config, known_hosts, monkeypatch):
        _pin(known_hosts, "github.com", "ssh-ed25519", OLD_ED25519)
        monkeypatch.setattr(
            svc, "_ssh_keyscan_raw",
            lambda host, port, hashed=False: ([], "connection refused"),
        )
        with pytest.raises(ValueError, match="Aktueller Host-Key"):
            svc.reset_pinned_host_key(test_session, "git@github.com:acme/pipelines.git")


class TestHostKeyApiEndpoints:
    def _admin_client(self, client, test_session, monkeypatch):
        from app.auth import get_current_user, require_admin
        from app.models import User, UserRole, UserStatus
        from app.main import app

        admin = User(username="admin", email="admin@example.com", role=UserRole.ADMIN, status=UserStatus.ACTIVE)
        test_session.add(admin)
        test_session.commit()
        test_session.refresh(admin)

        app.dependency_overrides[get_current_user] = lambda: admin
        app.dependency_overrides[require_admin] = lambda: admin
        return client, admin

    def test_status_requires_admin(self, client):
        response = client.get("/api/sync/host-key/status")
        assert response.status_code in (401, 403)

    def test_reset_requires_admin(self, client):
        response = client.post("/api/sync/host-key/reset", json={"confirm_text": "x"})
        assert response.status_code in (401, 403, 422)

    def test_status_ok_for_admin(self, client, test_session, known_hosts, repo_config, monkeypatch):
        client, admin = self._admin_client(client, test_session, monkeypatch)
        monkeypatch.setattr(
            svc, "_ssh_keyscan_raw",
            lambda host, port, hashed=False: ([f"github.com ssh-ed25519 {NEW_ED25519}"], None),
        )
        response = client.get("/api/sync/host-key/status")
        assert response.status_code == 200
        assert response.json()["applicable"] is True

    def test_reset_writes_audit_log(self, client, test_session, known_hosts, repo_config, monkeypatch):
        client, admin = self._admin_client(client, test_session, monkeypatch)
        _pin(known_hosts, "github.com", "ssh-ed25519", OLD_ED25519)
        monkeypatch.setattr(
            svc, "_ssh_keyscan_raw",
            lambda host, port, hashed=False: ([f"github.com ssh-ed25519 {NEW_ED25519}"], None),
        )
        response = client.post(
            "/api/sync/host-key/reset",
            json={"confirm_text": "git@github.com:acme/pipelines.git"},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

        from app.models import AuditLogEntry
        from sqlmodel import select
        entries = test_session.exec(select(AuditLogEntry).where(AuditLogEntry.action == "sync_host_key_reset")).all()
        assert len(entries) == 1
        assert entries[0].username == "admin"
        assert entries[0].details["repo_url"] == "git@github.com:acme/pipelines.git"
