"""Digest of notification API tokens for database lookup.

Tokens are created with ``secrets.token_urlsafe`` (high entropy). A plain
SHA-256 digest is standard for storing a non-reversible identifier for lookup;
this is not password hashing (use Argon2/bcrypt for passwords).
"""

from __future__ import annotations

import hashlib


def digest_notification_api_token(value: str) -> str:
    """Return hex digest stored as ``NotificationApiKey.key_hash``.

    ``value`` is high-entropy material from ``secrets.token_urlsafe`` (not a
    user password). ``usedforsecurity=False`` marks a non-password digest use.
    """
    return hashlib.sha256(value.encode("utf-8"), usedforsecurity=False).hexdigest()
