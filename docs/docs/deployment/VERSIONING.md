---
sidebar_position: 5
---

# Version Checking System

## Overview

FastFlow includes an automated version checking system that monitors GitHub for new releases and notifies users when updates are available.

## How It Works

### Version Check Schedule

The version check runs automatically:

1. **On API Startup** - Immediate check when the backend starts
2. **Daily at 2:00 AM** - Scheduled check via APScheduler (runs together with log and Docker cleanup)
3. **On-Demand** - Via the `/api/system/version` endpoint

### Version Storage

The current version is stored in the `VERSION` file in the project root **with the "v" prefix**:

```
VERSION
├── v0.1.0
```

This single source of truth is used by both:
- **Backend**: Read via `app/config.py` (strips "v" prefix automatically)
- **Frontend**: Injected via `vite.config.ts` (strips "v" prefix automatically)

## GitHub Tag Naming Convention

For the version checker to work correctly, GitHub releases **must** match the VERSION file format exactly.

### Required Format

Both the VERSION file and GitHub tags use the same format:

```
v{MAJOR}.{MINOR}.{PATCH}
```

### Examples

✅ **Correct:**
- VERSION file: `v0.1.0` → GitHub tag: `v0.1.0` ✓
- VERSION file: `v1.0.0` → GitHub tag: `v1.0.0` ✓
- VERSION file: `v2.3.5` → GitHub tag: `v2.3.5` ✓

❌ **Incorrect Tag Names:**
- `0.1.0` - Missing `v` prefix (won't match `v0.1.0`)
- `version-0.1.0` - Wrong prefix
- `release-v0.1.0` - Extra prefix
- `v0.1` - Missing patch version

### How to Create a Release

1. **Update the VERSION file:**
   ```bash
   echo "v0.2.0" > VERSION
   ```

2. **Commit the change:**
   ```bash
   git add VERSION
   git commit -m "Bump version to v0.2.0"
   ```

3. **Create and push a tag (same as VERSION file):**
   ```bash
   git tag v0.2.0
   git push origin v0.2.0
   ```

4. **Create a GitHub Release:**
   - Go to: https://github.com/ttuhin03/fastflow/releases/new
   - Select the tag: `v0.2.0`
   - Add release notes
   - Publish the release

> **Note:** The VERSION file and the GitHub tag must match exactly (both include the "v" prefix).

## API Usage

### Get Version Information

**Endpoint:** `GET /api/system/version`

**Query Parameters:**
- `force_check` (optional, boolean): Force a fresh GitHub check, bypassing cache

**Response:**
```json
{
  "version": "0.1.0",
  "latest_version": "0.2.0",
  "update_available": true,
  "last_checked": "2026-01-17T01:00:00",
  "check_error": null
}
```

> **Note:** The API returns versions without the "v" prefix (e.g., `0.1.0`) even though the VERSION file contains `v0.1.0`.

**Example Usage:**

```bash
# Get cached version info
curl http://localhost:8000/api/system/version

# Force fresh check
curl http://localhost:8000/api/system/version?force_check=true
```

## Frontend Integration

The version information is displayed in the frontend via the `VersionInfo` component:

- Shows current version
- Indicates when updates are available
- Displays last check time
- Shows any errors during version check

## Caching Strategy

- **In-Memory Cache**: Version information is cached globally
- **No Time-Based Expiration**: Cache persists until next scheduled check or manual refresh
- **Update Triggers**: 
  - API startup (always fresh)
  - Daily at 2:00 AM (scheduled)
  - Force check via API (`?force_check=true`)

## Error Handling

The version checker gracefully handles errors:

- **Network Failures**: Logs warning, keeps cached data
- **404 Not Found**: Indicates no releases published yet
- **Invalid Responses**: Logs error, assumes current version is latest
- **Non-Critical**: Version check failures never prevent app startup

## Logs

Version check activity is logged:

```
INFO - Checking for version updates...
INFO - New version available: 0.2.0 (current: 0.1.0)
INFO - Version check scheduled: Daily at 2:00 AM
```

## Configuration

The version checker uses these settings from `app/config.py`:

- `VERSION`: Current version (read from `VERSION` file)
- **GitHub Repository**: Hardcoded to `ttuhin03/fastflow`
  - To change: Edit `app/version_checker.py` line ~35

## Scheduled Job Details

The version check job is scheduled via APScheduler:

- **Job ID**: `version_check_job`
- **Name**: "Version Update Check"  
- **Trigger**: CronTrigger (hour=2, minute=0)
- **Function**: `app.version_checker:check_version_update_sync`

This runs at the same time as the cleanup job for efficiency.

## Troubleshooting

### Version check not working?

1. **Check logs** for error messages:
   ```bash
   docker-compose logs backend | grep -i version
   ```

2. **Verify GitHub release exists**:
   - Visit: https://github.com/ttuhin03/fastflow/releases/latest
   - Ensure tag format is `v{version}`

3. **Test manually**:
   ```bash
   curl http://localhost:8000/api/system/version?force_check=true
   ```

4. **Check scheduler is running**:
   ```bash
   curl http://localhost:8000/api/scheduler/jobs
   ```
   - Look for job ID: `version_check_job`

### No releases found (404)?

This is normal if you haven't created any GitHub releases yet. The checker will:
- Log a warning
- Assume current version is latest
- Continue checking on schedule

To fix: Create your first release following the tag naming convention above.
