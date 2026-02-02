from fastapi import APIRouter
from pydantic import BaseModel
import logging
from typing import Optional
from datetime import datetime
from app.services.version_checker import get_cached_version_info, check_version_update

router = APIRouter(prefix="/system", tags=["system"])
logger = logging.getLogger(__name__)

class VersionInfo(BaseModel):
    version: str
    latest_version: Optional[str] = None
    update_available: bool = False
    last_checked: Optional[datetime] = None
    check_error: Optional[str] = None


@router.get("/version", response_model=VersionInfo)
async def get_version_info(force_check: bool = False):
    """
    Get version information.
    
    Args:
        force_check: If True, force a fresh check against GitHub (bypasses cache)
    
    Returns:
        VersionInfo with current version, latest version, and update availability
    """
    if force_check:
        # Force a fresh check
        logger.info("Forcing fresh version check")
        version_data = await check_version_update()
    else:
        # Return cached data
        version_data = get_cached_version_info()
    
    return VersionInfo(**version_data)
