"""
Security Headers Middleware.

Dieses Modul stellt eine Middleware bereit, die wichtige HTTP Security Headers
zu allen Response hinzufügt.

Security Headers:
- Content-Security-Policy: Schutz vor XSS-Angriffen
- X-Frame-Options: Schutz vor Clickjacking
- X-Content-Type-Options: Verhindert MIME-Sniffing
- Strict-Transport-Security: Erzwingt HTTPS (wenn HTTPS aktiviert)
- Referrer-Policy: Kontrolliert welche Informationen im Referer-Header gesendet werden
- X-XSS-Protection: Zusätzlicher XSS-Schutz (veraltet, aber für Kompatibilität)
"""

import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import config

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware für HTTP Security Headers.
    
    Fügt wichtige Security Headers zu allen HTTP-Responses hinzu:
    - Content-Security-Policy: Schutz vor XSS
    - X-Frame-Options: Schutz vor Clickjacking
    - X-Content-Type-Options: Verhindert MIME-Sniffing
    - Strict-Transport-Security: Erzwingt HTTPS (nur in Produktion mit HTTPS)
    - Referrer-Policy: Kontrolliert Referer-Informationen
    """
    
    async def dispatch(self, request: Request, call_next):
        """
        Fügt Security Headers zur Response hinzu.
        
        Args:
            request: FastAPI Request
            call_next: Next middleware/handler
            
        Returns:
            Response mit Security Headers
        """
        response = await call_next(request)
        
        # Content-Security-Policy
        # Erlaubt:
        # - self: Eigene Domain
        # - 'unsafe-inline' für inline scripts/styles (notwendig für React in Dev)
        # - 'unsafe-eval' für eval (notwendig für React Dev Mode)
        # PostHog: script-src + connect-src für eu-assets (array.js, config), eu.i (Ingest), eu (App)
        posthog_script = "https://eu-assets.i.posthog.com"
        posthog_connect = "https://eu.i.posthog.com https://eu.posthog.com https://eu-assets.i.posthog.com"
        # OAuth-Provider für Login (connect-src für Fetch, falls nötig)
        oauth_connect = "https://github.com https://api.github.com https://accounts.google.com https://oauth2.googleapis.com https://login.microsoftonline.com https://graph.microsoft.com"
        if config.ENVIRONMENT == "production":
            # Produktion: Restriktive CSP
            # style-src: fonts.googleapis.com für Google Fonts CSS; font-src: fonts.gstatic.com für Font-Dateien (.woff2)
            csp = (
                "default-src 'self'; "
                f"script-src 'self' 'unsafe-inline' 'unsafe-eval' {posthog_script}; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "img-src 'self' data: https:; "
                "font-src 'self' data: https://fonts.gstatic.com; "
                f"connect-src 'self' {posthog_connect} {oauth_connect}; "
                "frame-ancestors 'none';"
            )
        else:
            # Development: Weniger restriktiv für Dev-Tools
            csp = (
                "default-src 'self'; "
                f"script-src 'self' 'unsafe-inline' 'unsafe-eval' {posthog_script}; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "img-src 'self' data: https:; "
                "font-src 'self' data: https://fonts.gstatic.com; "
                f"connect-src 'self' ws: wss: {posthog_connect} {oauth_connect}; "
                "frame-ancestors 'none';"
            )
        
        response.headers["Content-Security-Policy"] = csp
        
        # X-Frame-Options: Verhindert Einbettung in Frames (Clickjacking-Schutz)
        response.headers["X-Frame-Options"] = "DENY"
        
        # X-Content-Type-Options: Verhindert MIME-Sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # Referrer-Policy: Begrenzt Referer-Informationen
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # X-XSS-Protection: Zusätzlicher XSS-Schutz (veraltet, aber für Kompatibilität)
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # Strict-Transport-Security: Erzwingt HTTPS (nur wenn HTTPS aktiviert ist)
        # Prüfe ob Request über HTTPS kam
        # In Produktion sollte HTTPS verwendet werden
        if config.ENVIRONMENT == "production":
            # HSTS nur setzen wenn wir sicher sind, dass HTTPS verwendet wird
            # In Produktion sollte hinter einem Reverse-Proxy mit HTTPS sein
            # Der Reverse-Proxy sollte diesen Header setzen, aber wir setzen ihn auch
            # als Fallback
            hsts_max_age = 31536000  # 1 Jahr
            response.headers["Strict-Transport-Security"] = f"max-age={hsts_max_age}; includeSubDomains"
        
        return response
