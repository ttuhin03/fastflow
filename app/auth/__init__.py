"""
Auth package: session auth, OAuth (GitHub/Google/Microsoft/Custom), OAuth processing.
"""

from app.auth.auth import (
    create_access_token,
    create_log_download_token,
    create_session,
    delete_all_user_sessions,
    delete_session,
    get_current_user,
    get_session_by_token,
    require_admin,
    require_write,
    verify_log_download_token,
    verify_token,
)
from app.auth.github_oauth import (
    delete_oauth_state,
    generate_oauth_state,
    get_oauth_state,
    store_oauth_state,
)
from app.auth.github_oauth_user import (
    GITHUB_ACCESS_TOKEN_URL,
    GITHUB_AUTHORIZE_URL,
    get_github_authorize_url,
    get_github_user_data,
)
from app.auth.google_oauth_user import (
    GOOGLE_AUTHORIZE_URL,
    GOOGLE_TOKEN_URL,
    get_google_authorize_url,
    get_google_user_data,
)
from app.auth.microsoft_oauth_user import (
    MICROSOFT_AUTHORIZE_URL_BASE,
    get_microsoft_authorize_url,
    get_microsoft_user_data,
)
from app.auth.custom_oauth_user import (
    get_custom_oauth_authorize_url,
    get_custom_oauth_user_data,
)
from app.auth.oauth_processing import process_oauth_login

__all__ = [
    "create_access_token",
    "create_log_download_token",
    "create_session",
    "delete_all_user_sessions",
    "delete_session",
    "get_current_user",
    "get_session_by_token",
    "require_admin",
    "verify_log_download_token",
    "verify_token",
    "require_write",
    "delete_oauth_state",
    "generate_oauth_state",
    "get_oauth_state",
    "store_oauth_state",
    "GITHUB_ACCESS_TOKEN_URL",
    "GITHUB_AUTHORIZE_URL",
    "get_github_authorize_url",
    "get_github_user_data",
    "GOOGLE_AUTHORIZE_URL",
    "GOOGLE_TOKEN_URL",
    "get_google_authorize_url",
    "get_google_user_data",
    "MICROSOFT_AUTHORIZE_URL_BASE",
    "get_microsoft_authorize_url",
    "get_microsoft_user_data",
    "get_custom_oauth_authorize_url",
    "get_custom_oauth_user_data",
    "process_oauth_login",
]
