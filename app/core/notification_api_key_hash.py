"""Digest of notification API tokens for database lookup.

Tokens are created with ``secrets.token_urlsafe`` (high entropy). A plain
SHA-256 digest is standard for storing a non-reversible identifier for lookup;
this is not password hashing (use Argon2/bcrypt for passwords).
"""

from __future__ import annotations

import hashlib


def digest_notification_api_token(token: str) -> str:
    """Return hex digest stored as ``NotificationApiKey.key_hash``."""
    # codeql[py/weak-sensitive-data-hashing]: High-entropy API token (token_urlsafe), not a password; SHA-256 is appropriate for storage lookup.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
