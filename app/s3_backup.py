"""
S3 Log-Backup Service.

Lädt Pipeline-Logs und Metrics vor der lokalen Löschung (Cleanup) auf einen
S3-kompatiblen Speicher (z.B. MinIO). Lokale Löschung erfolgt nur bei
erfolgreichem Upload. Stream-basierter Upload mit boto3 (upload_fileobj)
für geringen Speicherverbrauch.
"""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from app.config import config
from app.models import PipelineRun
from app.resilience import circuit_s3, CircuitBreakerOpenError, with_retry_async

logger = logging.getLogger(__name__)

# Modul-Singleton
_s3_client: Optional[Any] = None

# In-Memory-Liste der letzten S3-Backup-Fehler (für UI/API), max 50
_backup_failures: List[Dict[str, str]] = []
_MAX_BACKUP_FAILURES = 50

# Zeitstempel des letzten erfolgreichen S3-Backups (für UI)
_last_backup_at: Optional[datetime] = None


def set_last_backup_timestamp() -> None:
    """Setzt den Zeitstempel des letzten erfolgreichen S3-Backups."""
    global _last_backup_at
    _last_backup_at = datetime.now(timezone.utc)


def get_last_backup_timestamp() -> Optional[datetime]:
    """Gibt den Zeitstempel des letzten erfolgreichen S3-Backups zurück (für UI)."""
    return _last_backup_at


def append_backup_failure(run_id: str, pipeline_name: str, error_message: str) -> None:
    """Hängt einen S3-Backup-Fehler an (für UI und GET /api/settings/backup-failures)."""
    global _backup_failures
    _backup_failures = (
        [
            {
                "run_id": run_id,
                "pipeline_name": pipeline_name,
                "error_message": error_message,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        ]
        + _backup_failures
    )[: _MAX_BACKUP_FAILURES]


def get_backup_failures() -> List[Dict[str, str]]:
    """Gibt die letzten S3-Backup-Fehler zurück (für GET /api/settings/backup-failures)."""
    return list(_backup_failures)


def _get_client():
    """Erzeugt den boto3 S3-Client lazy (MinIO-kompatibel)."""
    global _s3_client
    if _s3_client is not None:
        return _s3_client
    boto_cfg = None
    if config.S3_USE_PATH_STYLE:
        boto_cfg = BotoConfig(s3={"addressing_style": "path"})
    _s3_client = boto3.client(
        "s3",
        endpoint_url=config.S3_ENDPOINT_URL,
        aws_access_key_id=config.S3_ACCESS_KEY,
        aws_secret_access_key=config.S3_SECRET_ACCESS_KEY,
        region_name=config.S3_REGION,
        config=boto_cfg,
    )
    return _s3_client


class S3BackupService:
    """
    Service für S3-Backup von Pipeline-Logs vor der lokalen Löschung.
    """

    def is_configured(self) -> bool:
        """
        Prüft, ob S3-Backup aktiv und Endpoint, Bucket, Access/Secret gesetzt sind.
        """
        if not config.S3_BACKUP_ENABLED:
            return False
        return bool(
            config.S3_ENDPOINT_URL
            and config.S3_BUCKET
            and config.S3_ACCESS_KEY
            and config.S3_SECRET_ACCESS_KEY
        )

    def _build_metadata(self, run: PipelineRun) -> Dict[str, str]:
        """Baut S3-Metadaten aus dem Run (alle Werte als str, S3-Limit 2 KB)."""
        return {
            "pipeline_name": str(run.pipeline_name),
            "run_id": str(run.id),
            "started_at": run.started_at.isoformat() if run.started_at else "",
            "finished_at": run.finished_at.isoformat() if run.finished_at else "",
            "status": str(run.status),
            "triggered_by": str(run.triggered_by),
        }

    def _resolve_path(self, raw: str) -> Path:
        """Löst relativen Pfad gegen LOGS_DIR auf."""
        p = Path(raw)
        if not p.is_absolute():
            p = config.LOGS_DIR / p
        return p

    def _upload_file_streaming(
        self, path: Path, bucket: str, key: str, metadata: Dict[str, str]
    ) -> None:
        """
        Stream-Upload mit boto3 upload_fileobj (chunked, geringer RAM).
        Wirft bei Fehlern (ClientError, IOError, ...).
        """
        client = _get_client()
        with open(path, "rb") as f:
            client.upload_fileobj(
                f,
                Bucket=bucket,
                Key=key,
                ExtraArgs={"Metadata": metadata},
            )

    async def upload_run_logs(self, run: PipelineRun) -> Tuple[bool, Optional[str]]:
        """
        Lädt Log- und ggf. Metrics-Datei des Runs nach S3.
        Returns (True, None) wenn Backup erfolgreich oder nicht nötig;
        (False, error_message) bei Fehler.
        """
        if not self.is_configured():
            return (True, None)

        has_log = run.log_file and self._resolve_path(run.log_file).exists()
        has_metrics = (
            run.metrics_file and self._resolve_path(run.metrics_file).exists()
        )
        if not has_log and not has_metrics:
            return (True, None)

        metadata = self._build_metadata(run)
        bucket = config.S3_BUCKET
        prefix = config.S3_PREFIX.rstrip("/")
        base_key = f"{prefix}/{run.pipeline_name}/{run.id}"

        if has_log:
            path = self._resolve_path(run.log_file)
            key = f"{base_key}/run.log"
            try:
                def _do_upload_log():
                    circuit_s3.call(
                        lambda: self._upload_file_streaming(path, bucket, key, metadata)
                    )
                await with_retry_async(
                    lambda: asyncio.to_thread(_do_upload_log),
                    stop_attempts=3,
                    min_wait=2.0,
                    max_wait=30.0,
                )
            except CircuitBreakerOpenError as e:
                err = str(e)
                logger.error("S3 Circuit Breaker offen: %s", err)
                return (False, err)
            except (ClientError, OSError) as e:
                err = str(e)
                logger.error(
                    "S3-Backup fehlgeschlagen (run.log) für Run %s: %s",
                    run.id,
                    err,
                    exc_info=True,
                )
                return (False, err)

        if has_metrics:
            path = self._resolve_path(run.metrics_file)
            key = f"{base_key}/metrics.jsonl"
            try:
                def _do_upload_metrics():
                    circuit_s3.call(
                        lambda: self._upload_file_streaming(path, bucket, key, metadata)
                    )
                await with_retry_async(
                    lambda: asyncio.to_thread(_do_upload_metrics),
                    stop_attempts=3,
                    min_wait=2.0,
                    max_wait=30.0,
                )
            except CircuitBreakerOpenError as e:
                err = str(e)
                logger.error("S3 Circuit Breaker offen: %s", err)
                return (False, err)
            except (ClientError, OSError) as e:
                err = str(e)
                logger.error(
                    "S3-Backup fehlgeschlagen (metrics) für Run %s: %s",
                    run.id,
                    err,
                    exc_info=True,
                )
                return (False, err)

        set_last_backup_timestamp()
        return (True, None)


# Singleton für Cleanup-Integration
_s3_backup = S3BackupService()
