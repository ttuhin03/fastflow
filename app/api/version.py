from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx
import logging
from typing import Optional
from app.config import config
from datetime import datetime, timedelta

router = APIRouter(prefix="/system", tags=["system"])
logger = logging.getLogger(__name__)

class VersionInfo(BaseModel):
    version: str
    latest_version: Optional[str] = None
    update_available: bool = False
    last_checked: Optional[datetime] = None

# Simple in-memory cache
_version_cache: Optional[VersionInfo] = None
_last_check: Optional[datetime] = None
CACHE_DURATION = timedelta(hours=1)

@router.get("/version", response_model=VersionInfo)
async def get_version_info():
    global _version_cache, _last_check
    
    current_time = datetime.now()
    
    # Return cached result if valid
    if _version_cache and _last_check and (current_time - _last_check < CACHE_DURATION):
        return _version_cache

    current_version = config.VERSION
    latest_version = current_version
    update_available = False

    try:
        # Check GitHub for latest release
        # Assumes the repo connects to a specific GitHub repo. 
        # Using a generic placeholder or config if available.
        # For now, we will try to look for a repository URL in git config or use a default if known.
        # Since we don't have a specific repo URL in config, we'll skip the actual HTTP check for now
        # OR better: Add a TODO/Placeholder or use a known repo if this is a known project (FastFlow).
        # Assuming 'fastflow' is the name, but need user/org.
        # Let's check if we can get it from git_sync.py logic or similar, but for now safe default.
        
        # NOTE: To make this work for a specific repo, we would need:
        # repo_owner = "ttuhin03" # derived from path in context /Users/tuhin/cursor_repos/fastflow -> ttuhin03/fastflow
        # repo_name = "fastflow"
        
        # Let's try to fetch from GitHub API for the current repo
        # We'll use a hardcoded repo for now based on the user context: ttuhin03/fastflow
        
        async with httpx.AsyncClient() as client:
            headers = {"Accept": "application/vnd.github.v3+json"}
            # Use public endpoint
            response = await client.get(
                "https://api.github.com/repos/ttuhin03/fastflow/releases/latest",
                headers=headers,
                timeout=5.0
            )
            
            if response.status_code == 200:
                data = response.json()
                tag_name = data.get("tag_name", "").lstrip("v")
                if tag_name:
                    latest_version = tag_name
                    # Simple string comparison or semver parse could be done here
                    # For simplicity: string inequality check, assuming proper semantic versioning
                    update_available = latest_version != current_version
            elif response.status_code == 404:
                logger.warning("GitHub repository or release not found called 'ttuhin03/fastflow'")
            else:
                logger.warning(f"Failed to check GitHub version: {response.status_code}")

    except Exception as e:
        logger.warning(f"Error checking for updates: {e}")

    _version_cache = VersionInfo(
        version=current_version,
        latest_version=latest_version,
        update_available=update_available,
        last_checked=current_time
    )
    _last_check = current_time
    
    return _version_cache
