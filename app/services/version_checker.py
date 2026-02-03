"""
Version Checking Module.

This module provides functionality to periodically check for new versions
of FastFlow on GitHub and cache the results.
"""

import logging
import asyncio
import httpx
from datetime import datetime, timedelta
from typing import Optional
from app.core.config import config

logger = logging.getLogger(__name__)

# Global cache for version information
class VersionCache:
    def __init__(self):
        self.current_version: str = config.VERSION
        self.latest_version: Optional[str] = None
        self.update_available: bool = False
        self.last_checked: Optional[datetime] = None
        self.check_error: Optional[str] = None
    
    def to_dict(self):
        return {
            "version": self.current_version,
            "latest_version": self.latest_version,
            "update_available": self.update_available,
            "last_checked": self.last_checked,
            "check_error": self.check_error
        }

# Global instance
_version_cache = VersionCache()


async def check_version_update() -> dict:
    """
    Check GitHub for the latest version and update the cache.
    
    This function is called:
    1. On API startup
    2. Daily at 2:00 AM (via scheduler)
    3. On-demand via the /api/system/version endpoint
    
    Returns:
        Dictionary with version information
    """
    global _version_cache
    
    logger.info("Checking for version updates...")
    
    try:
        async with httpx.AsyncClient() as client:
            headers = {"Accept": "application/vnd.github.v3+json"}
            response = await client.get(
                "https://api.github.com/repos/ttuhin03/fastflow/releases/latest",
                headers=headers,
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                tag_name = data.get("tag_name", "").lstrip("v")
                
                if tag_name:
                    _version_cache.latest_version = tag_name
                    _version_cache.update_available = tag_name != _version_cache.current_version
                    _version_cache.check_error = None
                    
                    if _version_cache.update_available:
                        logger.info(
                            f"New version available: {tag_name} "
                            f"(current: {_version_cache.current_version})"
                        )
                    else:
                        logger.info(f"Running latest version: {_version_cache.current_version}")
                else:
                    logger.warning("GitHub release tag_name is empty")
                    _version_cache.check_error = "Invalid GitHub release format"
                    
            elif response.status_code == 404:
                logger.warning("GitHub repository or release not found (ttuhin03/fastflow)")
                _version_cache.check_error = "Repository or release not found"
                # Keep latest_version as current_version
                _version_cache.latest_version = _version_cache.current_version
                _version_cache.update_available = False
            else:
                logger.warning(f"Failed to check GitHub version: {response.status_code}")
                _version_cache.check_error = f"HTTP {response.status_code}"
                _version_cache.latest_version = _version_cache.current_version
                _version_cache.update_available = False
                
    except Exception as e:
        logger.warning(f"Error checking for updates: {e}")
        _version_cache.check_error = str(e)
        _version_cache.latest_version = _version_cache.current_version
        _version_cache.update_available = False
    
    _version_cache.last_checked = datetime.now()
    
    return _version_cache.to_dict()


def check_version_update_sync() -> dict:
    """
    Synchronous wrapper for check_version_update().
    
    Used by the scheduler which requires synchronous functions.
    
    Returns:
        Dictionary with version information
    """
    return asyncio.run(check_version_update())


def get_cached_version_info() -> dict:
    """
    Get cached version information without checking GitHub.
    
    Returns:
        Dictionary with cached version information
    """
    return _version_cache.to_dict()


def schedule_version_check() -> None:
    """
    Schedule periodic version check in the scheduler.
    
    Called on app startup to register automatic version checks.
    Runs daily at 2:00 AM (together with cleanup job).
    """
    try:
        from app.services.scheduler import get_scheduler
        from apscheduler.triggers.cron import CronTrigger
        
        scheduler = get_scheduler()
        if scheduler is None:
            logger.warning("Scheduler not available, version check not scheduled")
            return
        
        if not scheduler.running:
            logger.warning("Scheduler not running, version check not scheduled")
            return
        
        # Schedule version check (daily at 2:00 AM)
        scheduler.add_job(
            func="app.services.version_checker:check_version_update_sync",
            trigger=CronTrigger(hour=2, minute=0),
            id="version_check_job",
            name="Version Update Check",
            replace_existing=True
        )
        
        logger.info("Version check scheduled: Daily at 2:00 AM")
        
    except Exception as e:
        logger.error(f"Error scheduling version check: {e}", exc_info=True)
