"""
Git Sync Repository Config: URL + PAT oder Deploy Key (DB + Env).

Konfiguration für Git-Sync per Repository-URL. Authentifizierung entweder per
Personal Access Token (HTTPS-URL) oder Deploy Key (SSH-URL).
Werte können in der Sync-UI (DB) oder per Umgebungsvariablen gesetzt werden.
Env-Variablen haben Vorrang vor DB-Werten.
"""

import logging
from typing import Any, Dict, Optional

from sqlmodel import Session

from app.core.config import config
from app.models import OrchestratorSettings
from app.services.orchestrator_settings import get_orchestrator_settings_or_default
from app.services.secrets import decrypt, encrypt

logger = logging.getLogger(__name__)


def _is_ssh_url(url: str) -> bool:
    """True wenn URL SSH-Format hat (git@... oder ssh://...)."""
    u = (url or "").strip()
    return u.startswith("git@") or u.startswith("ssh://")


def get_sync_repo_config(session: Session) -> Optional[Dict[str, Any]]:
    """
    Liest die effektive Sync-Repo-Konfiguration (Env hat Vorrang vor DB).

    Returns:
        Dict mit repo_url, token (entschlüsselt oder None), deploy_key (entschlüsselt oder None), branch.
        None wenn weder Env noch DB eine repo_url setzen.
    """
    repo_url = config.GIT_REPO_URL
    token_plain: Optional[str] = config.GIT_SYNC_TOKEN
    deploy_key_plain: Optional[str] = config.GIT_SYNC_DEPLOY_KEY
    branch = config.GIT_BRANCH

    settings = session.get(OrchestratorSettings, 1)
    if settings:
        if repo_url is None or (isinstance(repo_url, str) and not repo_url.strip()):
            repo_url = (settings.git_sync_repo_url or "").strip() or None
        if token_plain is None and settings.git_sync_token_encrypted:
            try:
                token_plain = decrypt(settings.git_sync_token_encrypted)
            except Exception as e:
                logger.warning("Git-Sync-Token aus DB konnte nicht entschlüsselt werden: %s", e)
        if deploy_key_plain is None and getattr(settings, "git_sync_deploy_key_encrypted", None):
            try:
                deploy_key_plain = decrypt(settings.git_sync_deploy_key_encrypted)
            except Exception as e:
                logger.warning("Git-Sync-Deploy-Key aus DB konnte nicht entschlüsselt werden: %s", e)
        if (settings.git_sync_branch or "").strip():
            branch = (settings.git_sync_branch or "").strip()

    if not repo_url:
        return None
    return {
        "repo_url": repo_url,
        "token": token_plain if token_plain else None,
        "deploy_key": deploy_key_plain if deploy_key_plain else None,
        "branch": branch or "main",
    }


def get_sync_repo_config_public(session: Session) -> Dict[str, Any]:
    """
    Liest die Sync-Repo-Konfiguration für API-Antwort (ohne Token/Key).

    Returns:
        Dict mit repo_url (oder None), branch, configured (bool), pipelines_subdir, auth_mode (pat|deploy_key).
    """
    cfg = get_sync_repo_config(session)
    subdir = (config.PIPELINES_SUBDIR or "").strip().strip("/") or None
    if not cfg:
        return {
            "repo_url": None,
            "branch": config.GIT_BRANCH,
            "configured": False,
            "pipelines_subdir": subdir,
            "auth_mode": "pat",
        }
    auth_mode = "deploy_key" if _is_ssh_url(cfg["repo_url"]) else "pat"
    return {
        "repo_url": cfg["repo_url"],
        "branch": cfg["branch"],
        "configured": True,
        "pipelines_subdir": subdir,
        "auth_mode": auth_mode,
    }


def save_sync_repo_config(
    session: Session,
    repo_url: str,
    token: Optional[str] = None,
    deploy_key: Optional[str] = None,
    branch: Optional[str] = None,
    pipelines_subdir: Optional[str] = None,
) -> None:
    """Speichert Repo-URL, optional Token oder Deploy Key (verschlüsselt), Branch und Pipelines-Unterordner in der DB."""
    settings = get_orchestrator_settings_or_default(session)
    url = (repo_url or "").strip() or None
    settings.git_sync_repo_url = url
    settings.git_sync_branch = (branch or "").strip() or None
    settings.pipelines_subdir = (pipelines_subdir or "").strip().strip("/") or None
    if _is_ssh_url(url or ""):
        if deploy_key is not None:
            settings.git_sync_deploy_key_encrypted = encrypt(deploy_key) if deploy_key.strip() else None
        settings.git_sync_token_encrypted = None
    else:
        if token is not None:
            settings.git_sync_token_encrypted = encrypt(token) if token.strip() else None
        settings.git_sync_deploy_key_encrypted = None
    session.add(settings)
    session.commit()
    session.refresh(settings)


def delete_sync_repo_config(session: Session) -> None:
    """Löscht die Sync-Repo-Konfiguration aus der DB (Env-Werte bleiben unberührt)."""
    settings = session.get(OrchestratorSettings, 1)
    if settings:
        settings.git_sync_repo_url = None
        settings.git_sync_token_encrypted = None
        settings.git_sync_deploy_key_encrypted = None
        settings.git_sync_branch = None
        settings.pipelines_subdir = None
        session.add(settings)
        session.commit()
