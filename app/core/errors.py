"""
HTTP-Fehler-Hilfen.

Liefert get_500_detail() für einheitliche 500-Antworten: In Produktion
wird nur eine generische Meldung zurückgegeben; in Development wird
die Exception-Meldung mit ausgegeben. Aufrufer sollten die Exception
(z. B. per logger.exception) vor dem Auslösen loggen.
"""

from app.core.config import config


def get_500_detail(e: Exception) -> str:
    """
    Liefert den Detail-Text für HTTP-500-Antworten.
    In Produktion: generische Meldung; in Development: str(e).
    Aufrufer sollten die Exception (z. B. logger.exception) loggen.
    """
    if config.ENVIRONMENT == "production":
        return "Ein interner Fehler ist aufgetreten."
    return str(e)
