"""
Pflege des UV-Paketcaches.

uv räumt seinen Cache nicht von selbst auf: jede je aufgelöste Paketversion bleibt
als entpacktes Archiv in ``archive-v0`` liegen. In Prod standen so 14,32 GB in
431.528 Dateien — 98,9 % eines 15,66-GB-Volumes — bis kein Byte mehr frei war und
jeder Pipeline-Run in ``_copy_pipeline_to_shared`` mit ENOSPC scheiterte, bei
durchgehend grünen Probes.

Geräumt wird mit ``uv cache prune --ci``, nicht mit dem nackten ``prune``. Gemessen
an einem frischen Cache mit requests+pandas:

    uv cache prune        "No unused entries found"        70 MB -> 70 MB
    uv cache prune --ci   "Removed 2735 files (59.1MiB)"   70 MB -> 4,9 MB

Das nackte ``prune`` entfernt nur hängengebliebene Einträge und ist für dieses
Problem ein No-Op. ``--ci`` wirft die von PyPI geladenen Wheels weg und behält die
selbst gebauten, deren Neubau teuer wäre. Der Preis ist ein Neuladen beim nächsten
Run; bei einem Zehnfachen an Altlast ist das der richtige Tausch.

``--force`` wird bewusst *nicht* gesetzt: uv prüft selbst, ob Einträge in Benutzung
sind, und diese Prüfung ist die innere von zwei Schranken. Die äussere ist
``has_active_runs``.
"""

import logging
import shutil
import subprocess
import time
from typing import Any, Dict, Optional

from app.core.config import config

logger = logging.getLogger(__name__)

_GIB = 1024 ** 3

# Ein am Timeout abgeschnittener Prune hat Platz gemacht, aber nicht aufgeräumt.
# Ohne diese Notiz würde der nächste Lauf an der Schwelle abbiegen ("genug Platz")
# und der Rest bliebe für immer liegen — beim ersten Aufräumen eines gewachsenen
# Caches ist genau das der wahrscheinliche Verlauf.
_letzter_prune_unvollstaendig = False


def uv_cache_free_bytes() -> Optional[int]:
    """Freier Platz auf dem Volume des UV-Caches; None wenn nicht messbar."""
    try:
        return shutil.disk_usage(str(config.UV_CACHE_DIR)).free
    except (OSError, PermissionError) as e:
        logger.warning("UV-Cache: freien Platz nicht ermittelbar: %s", e)
        return None


def prune_uv_cache() -> Dict[str, Any]:
    """
    Ruft ``uv cache prune --ci`` und berichtet, wie viel dadurch frei wurde.

    Der freigewordene Platz wird über das Dateisystem gemessen, nicht aus der
    Ausgabe von uv gelesen: Die Zahl soll sagen, was auf dem Volume ankommt.
    """
    global _letzter_prune_unvollstaendig
    cache_dir = str(config.UV_CACHE_DIR)
    free_before = uv_cache_free_bytes()
    started = time.monotonic()
    try:
        result = subprocess.run(
            ["uv", "cache", "prune", "--ci", "--cache-dir", cache_dir],
            capture_output=True,
            text=True,
            timeout=config.UV_CACHE_PRUNE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        _letzter_prune_unvollstaendig = True
        free_now = uv_cache_free_bytes()
        logger.error(
            "UV-Cache: prune nach %ds abgebrochen (UV_CACHE_PRUNE_TIMEOUT), jetzt %.2f GB "
            "frei. Bereits gelöschte Dateien bleiben gelöscht; der nächste Lauf setzt fort.",
            config.UV_CACHE_PRUNE_TIMEOUT,
            (free_now or 0) / _GIB,
        )
        return {"status": "timeout", "freed_bytes": max(0, (free_now or 0) - (free_before or 0))}
    except OSError as e:
        logger.error("UV-Cache: prune nicht startbar: %s", e)
        return {"status": "failed", "error": str(e), "freed_bytes": 0}

    duration = round(time.monotonic() - started, 1)
    if result.returncode != 0:
        logger.error(
            "UV-Cache: prune fehlgeschlagen (Code %s): %s",
            result.returncode,
            (result.stderr or result.stdout or "").strip()[:500],
        )
        return {"status": "failed", "returncode": result.returncode, "freed_bytes": 0}

    _letzter_prune_unvollstaendig = False
    free_after = uv_cache_free_bytes()
    freed = 0
    if free_before is not None and free_after is not None:
        freed = max(0, free_after - free_before)
    logger.info(
        "UV-Cache geräumt: %.2f GB frei geworden, jetzt %.2f GB verfügbar (%.1fs)",
        freed / _GIB,
        (free_after or 0) / _GIB,
        duration,
    )
    return {
        "status": "pruned",
        "freed_bytes": freed,
        "free_bytes_after": free_after,
        "duration_seconds": duration,
    }


def wipe_uv_cache() -> Dict[str, Any]:
    """
    Löscht UV_CACHE_DIR vollständig. Notbremse, kein Regelweg.

    Strikt schlechter als der Prune: der nimmt auch fast alles, behält aber die
    selbst gebauten Wheels und die Index-Metadaten. Gerechtfertigt nur, wenn der
    Prune selbst scheitert — etwa weil uv den Cache nicht mehr lesen kann.
    """
    cache_dir = config.UV_CACHE_DIR
    free_before = uv_cache_free_bytes()
    try:
        shutil.rmtree(cache_dir, ignore_errors=True)
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error("UV-Cache: Wipe fehlgeschlagen: %s", e)
        return {"status": "failed", "error": str(e), "freed_bytes": 0}
    free_after = uv_cache_free_bytes()
    freed = 0
    if free_before is not None and free_after is not None:
        freed = max(0, free_after - free_before)
    logger.warning(
        "UV-Cache vollständig gelöscht (UV_CACHE_WIPE_ON_START): %.2f GB frei geworden. "
        "Der erste Run jeder Pipeline lädt seine Abhängigkeiten neu.",
        freed / _GIB,
    )
    return {"status": "wiped", "freed_bytes": freed, "free_bytes_after": free_after}


def maintain_uv_cache() -> Dict[str, Any]:
    """
    Räumt den UV-Cache, wenn der Platz knapp wird. Sonst nichts.

    Oberhalb der Schwelle wird bewusst nicht geräumt: ein warmer Cache ist der
    Sinn des Caches, und ``--ci`` wirft ihn fast komplett weg. Erst wenn der Platz
    knapp wird, ist der kalte Cache der bessere von zwei schlechten Zuständen —
    denn ohne Platz scheitert *jeder* Run.

    Es gibt bewusst *keine* Prüfung auf laufende Runs. Ein erster Entwurf hatte
    eine, und sie hat in Prod genau das Gegenteil bewirkt: dort läuft im
    Minutentakt eine Pipeline, es gibt also kein Leerlauffenster, und das Gate
    verklemmte sich selbst — Volume voll, Runs hängen, sehen aktiv aus, es wird
    nicht geräumt, Volume bleibt voll. Geschützt wird stattdessen von uv selbst:
    ``prune`` ohne ``--force`` respektiert Einträge, die gerade benutzt werden,
    und das ist eine Prüfung an der Wirklichkeit statt an der DB-Buchhaltung.

    Die Abwägung ist asymmetrisch: Ohne Gate kann im schlimmsten Fall ein
    einzelner Run scheitern und wird wiederholt. Mit Gate scheitern alle Runs
    dauerhaft, weil nie geräumt wird.
    """
    if not config.UV_CACHE_PRUNE:
        return {"status": "disabled"}

    free = uv_cache_free_bytes()
    if free is None:
        return {"status": "unmeasurable"}

    free_gb = free / _GIB
    if free_gb >= config.UV_CACHE_PRUNE_MIN_FREE_GB and not _letzter_prune_unvollstaendig:
        return {"status": "skipped", "reason": "genug Platz", "free_gb": round(free_gb, 2)}
    if _letzter_prune_unvollstaendig:
        logger.info("UV-Cache: setze abgebrochenen Prune fort (%.2f GB frei)", free_gb)

    logger.warning(
        "UV-Cache: nur %.2f GB frei (Schwelle %.2f GB) — räume mit uv cache prune --ci",
        free_gb,
        config.UV_CACHE_PRUNE_MIN_FREE_GB,
    )
    return prune_uv_cache()


def run_uv_cache_maintenance_job() -> None:
    """
    Einstieg für den Scheduler.

    Muss auf Modulebene liegen: APScheduler legt seine Jobs im SQLAlchemyJobStore ab
    und braucht dafür eine importierbare Referenz. Eine verschachtelte Funktion
    lehnt ``add_job`` mit "cannot be serialized" ab — der Job fehlt dann still.
    """
    maintain_uv_cache()
