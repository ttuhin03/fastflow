"""
Unit-Tests für SSH-Host-Key-Pinning in app.git_sync.sync._ssh_key_env.

Regression-Test für TE-23: Wenn GIT_SSH_KNOWN_HOSTS nicht gesetzt ist, darf
UserKnownHostsFile nicht /dev/null sein (das würde jeden Sync ungeprüft
akzeptieren). Stattdessen muss ein persistenter Pfad unter config.DATA_DIR
verwendet werden, sodass der Host-Key nach dem ersten Connect gepinnt bleibt.
"""

from app.core.config import config
from app.git_sync.sync import _ssh_key_env


def test_known_hosts_persisted_when_not_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "GIT_SSH_KNOWN_HOSTS", None)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    with _ssh_key_env("fake-deploy-key-content") as env:
        cmd = env["GIT_SSH_COMMAND"]
        assert "UserKnownHostsFile=/dev/null" not in cmd
        known_hosts_path = tmp_path / "ssh_known_hosts"
        assert f"UserKnownHostsFile={known_hosts_path}" in cmd
        assert known_hosts_path.exists()
        assert "StrictHostKeyChecking=accept-new" in cmd


def test_known_hosts_file_persists_across_calls(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "GIT_SSH_KNOWN_HOSTS", None)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    known_hosts_path = tmp_path / "ssh_known_hosts"
    with _ssh_key_env("fake-deploy-key-content"):
        pass
    known_hosts_path.write_text("example.com ssh-ed25519 AAAAfake\n")

    with _ssh_key_env("fake-deploy-key-content"):
        pass

    assert known_hosts_path.read_text() == "example.com ssh-ed25519 AAAAfake\n"


def test_explicit_known_hosts_still_used_and_not_persisted(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "GIT_SSH_KNOWN_HOSTS", "example.com ssh-ed25519 AAAAfake")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    with _ssh_key_env("fake-deploy-key-content") as env:
        cmd = env["GIT_SSH_COMMAND"]
        assert "StrictHostKeyChecking=yes" in cmd
        assert "UserKnownHostsFile=/dev/null" not in cmd
