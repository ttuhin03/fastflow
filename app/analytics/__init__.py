"""
Analytics package: tracking, PostHog client.
"""

from app.analytics.analytics import (
    run_instance_heartbeat_sync,
    schedule_telemetry_heartbeat,
    track_pipeline_run_finished,
    track_pipeline_run_started,
    track_sync_completed,
    track_sync_failed,
    track_user_logged_in,
    track_user_registered,
)
from app.analytics.posthog_client import (
    capture_exception,
    capture_startup_test_exception,
    get_system_settings,
    shutdown_posthog,
)

__all__ = [
    "run_instance_heartbeat_sync",
    "schedule_telemetry_heartbeat",
    "track_pipeline_run_finished",
    "track_pipeline_run_started",
    "track_sync_completed",
    "track_sync_failed",
    "track_user_logged_in",
    "track_user_registered",
    "capture_exception",
    "capture_startup_test_exception",
    "get_system_settings",
    "shutdown_posthog",
]
