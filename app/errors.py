"""
HTTP error helpers.

Provides get_500_detail() for consistent 500 responses: in production
only a generic message is returned; in development the exception message
is included. Callers must log the exception before raising.
"""

from app.config import config


def get_500_detail(e: Exception) -> str:
    """
    Returns the detail string for HTTP 500 responses.
    In production returns a generic message; in development includes str(e).
    Callers must log the exception (e.g. logger.exception) before raising.
    """
    if config.ENVIRONMENT == "production":
        return "Ein interner Fehler ist aufgetreten."
    return str(e)
