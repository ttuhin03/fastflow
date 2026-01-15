"""
Pipeline Discovery & Validation Module.

Dieses Modul scannt das Pipelines-Verzeichnis und erkennt verfügbare Pipelines:
- Pipeline-Name-Erkennung (Verzeichnisname)
- Pipeline-Validierung (main.py erforderlich)
- Metadaten-JSON-Erkennung (pipeline.json oder {pipeline_name}.json)
- Cache für Pipeline-Liste
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from app.config import config


class PipelineMetadata:
    """
    Pipeline-Metadaten aus JSON-Datei.
    
    Enthält alle optionalen Metadaten-Felder aus pipeline.json oder
    {pipeline_name}.json. Alle Felder sind optional.
    """
    
    def __init__(
        self,
        cpu_hard_limit: Optional[float] = None,
        mem_hard_limit: Optional[str] = None,
        cpu_soft_limit: Optional[float] = None,
        mem_soft_limit: Optional[str] = None,
        timeout: Optional[int] = None,
        retry_attempts: Optional[int] = None,
        retry_strategy: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        enabled: bool = True,
        default_env: Optional[Dict[str, str]] = None,
        webhook_key: Optional[str] = None
    ):
        """
        Initialisiert Pipeline-Metadaten.
        
        Args:
            cpu_hard_limit: CPU-Limit in Kernen (z.B. 1.0 = 1 Kern)
            mem_hard_limit: Memory-Limit (z.B. "512m", "1g")
            cpu_soft_limit: CPU-Soft-Limit für Monitoring (wird überwacht, keine Limitierung)
            mem_soft_limit: Memory-Soft-Limit für Monitoring (wird überwacht, keine Limitierung)
            timeout: Timeout in Sekunden (pipeline-spezifisch, überschreibt CONTAINER_TIMEOUT)
            retry_attempts: Retry-Versuche bei Fehlern (pipeline-spezifisch, überschreibt RETRY_ATTEMPTS)
            retry_strategy: Retry-Strategie (Dict mit "type" und weiteren Parametern)
                - type: "exponential_backoff", "fixed_delay", oder "custom_schedule"
                - Für exponential_backoff: "initial_delay" (Sekunden), "max_delay" (Sekunden), "multiplier" (Float)
                - Für fixed_delay: "delay" (Sekunden)
                - Für custom_schedule: "delays" (Liste von Sekunden)
            description: Beschreibung der Pipeline (wird in UI angezeigt)
            tags: Tags für Kategorisierung/Filterung in UI
            enabled: Pipeline aktiviert/deaktiviert (Standard: true)
            default_env: Pipeline-spezifische Default-Env-Vars (werden bei jedem Start gesetzt)
            webhook_key: Webhook-Schlüssel für externe Trigger (optional, None oder leer = Webhooks deaktiviert)
        """
        self.cpu_hard_limit = cpu_hard_limit
        self.mem_hard_limit = mem_hard_limit
        self.cpu_soft_limit = cpu_soft_limit
        self.mem_soft_limit = mem_soft_limit
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self.retry_strategy = retry_strategy
        self.description = description
        self.tags = tags or []
        self.enabled = enabled
        self.default_env = default_env or {}
        # Normalize empty strings to None (webhooks disabled)
        self.webhook_key = webhook_key if webhook_key and webhook_key.strip() else None
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Konvertiert Metadaten zu Dictionary.
        
        Returns:
            Dictionary mit allen gesetzten Metadaten-Feldern
        """
        result: Dict[str, Any] = {}
        if self.cpu_hard_limit is not None:
            result["cpu_hard_limit"] = self.cpu_hard_limit
        if self.mem_hard_limit is not None:
            result["mem_hard_limit"] = self.mem_hard_limit
        if self.cpu_soft_limit is not None:
            result["cpu_soft_limit"] = self.cpu_soft_limit
        if self.mem_soft_limit is not None:
            result["mem_soft_limit"] = self.mem_soft_limit
        if self.timeout is not None:
            result["timeout"] = self.timeout
        if self.retry_attempts is not None:
            result["retry_attempts"] = self.retry_attempts
        if self.retry_strategy is not None:
            result["retry_strategy"] = self.retry_strategy
        if self.description is not None:
            result["description"] = self.description
        if self.tags:
            result["tags"] = self.tags
        if not self.enabled:
            result["enabled"] = self.enabled
        if self.default_env:
            result["default_env"] = self.default_env
        # Only include webhook_key if it's set and non-empty
        if self.webhook_key:
            result["webhook_key"] = self.webhook_key
        return result


class DiscoveredPipeline:
    """
    Entdeckte Pipeline mit Metadaten.
    
    Repräsentiert eine Pipeline, die im Pipelines-Verzeichnis gefunden wurde,
    inklusive Validierung und Metadaten.
    """
    
    def __init__(
        self,
        name: str,
        path: Path,
        has_requirements: bool,
        metadata: Optional[PipelineMetadata] = None
    ):
        """
        Initialisiert eine entdeckte Pipeline.
        
        Args:
            name: Pipeline-Name (Verzeichnisname)
            path: Pfad zum Pipeline-Verzeichnis
            has_requirements: Ob requirements.txt vorhanden ist
            metadata: Optionale Metadaten aus JSON-Datei
        """
        self.name = name
        self.path = path
        self.has_requirements = has_requirements
        self.metadata = metadata or PipelineMetadata()
    
    def is_enabled(self) -> bool:
        """
        Prüft ob Pipeline aktiviert ist.
        
        Returns:
            True wenn Pipeline aktiviert ist, sonst False
        """
        return self.metadata.enabled
    
    def get_timeout(self) -> Optional[int]:
        """
        Gibt pipeline-spezifisches Timeout zurück.
        
        Returns:
            Timeout in Sekunden (None = unbegrenzt) oder None wenn nicht gesetzt
        """
        return self.metadata.timeout
    
    def get_retry_attempts(self) -> Optional[int]:
        """
        Gibt pipeline-spezifische Retry-Attempts zurück.
        
        Returns:
            Anzahl Retry-Versuche oder None wenn nicht gesetzt
        """
        return self.metadata.retry_attempts


# Cache für Pipeline-Liste
_pipeline_cache: Optional[List[DiscoveredPipeline]] = None
_cache_timestamp: Optional[datetime] = None


def discover_pipelines(force_refresh: bool = False) -> List[DiscoveredPipeline]:
    """
    Scannt das Pipelines-Verzeichnis und erkennt verfügbare Pipelines.
    
    Pipelines werden automatisch erkannt basierend auf:
    - Verzeichnisstruktur: Jede Pipeline in eigenem Unterverzeichnis
    - Pipeline-Name: Entspricht dem Verzeichnisnamen
    - Validierung: Pipeline muss main.py enthalten, sonst wird sie ignoriert
    - Metadaten: Optionale pipeline.json oder {pipeline_name}.json werden erkannt
    
    Args:
        force_refresh: Wenn True, Cache wird ignoriert und neu gescannt
    
    Returns:
        Liste aller entdeckten und validierten Pipelines
    
    Raises:
        FileNotFoundError: Wenn PIPELINES_DIR nicht existiert
        PermissionError: Wenn kein Zugriff auf PIPELINES_DIR
    """
    global _pipeline_cache, _cache_timestamp
    
    # Cache verwenden wenn vorhanden und nicht erzwungen
    if not force_refresh and _pipeline_cache is not None:
        return _pipeline_cache
    
    pipelines_dir = config.PIPELINES_DIR
    
    # Verzeichnis prüfen
    if not pipelines_dir.exists():
        raise FileNotFoundError(
            f"Pipelines-Verzeichnis existiert nicht: {pipelines_dir}"
        )
    
    if not pipelines_dir.is_dir():
        raise ValueError(
            f"Pipelines-Pfad ist kein Verzeichnis: {pipelines_dir}"
        )
    
    discovered: List[DiscoveredPipeline] = []
    
    # Alle Unterverzeichnisse scannen
    for item in pipelines_dir.iterdir():
        # Nur Verzeichnisse berücksichtigen (ignoriere Dateien)
        if not item.is_dir():
            continue
        
        # Versteckte Verzeichnisse ignorieren (z.B. .git)
        if item.name.startswith("."):
            continue
        
        pipeline_name = item.name
        main_py_path = item / "main.py"
        
        # Validierung: Pipeline muss main.py enthalten
        if not main_py_path.exists() or not main_py_path.is_file():
            continue
        
        # Prüfe ob requirements.txt vorhanden ist
        requirements_path = item / "requirements.txt"
        has_requirements = requirements_path.exists() and requirements_path.is_file()
        
        # Metadaten-JSON laden (optional)
        metadata = _load_pipeline_metadata(item, pipeline_name)
        
        # Pipeline zur Liste hinzufügen
        pipeline = DiscoveredPipeline(
            name=pipeline_name,
            path=item,
            has_requirements=has_requirements,
            metadata=metadata
        )
        discovered.append(pipeline)
    
    # Cache aktualisieren
    _pipeline_cache = discovered
    _cache_timestamp = datetime.utcnow()
    
    return discovered


def _load_pipeline_metadata(
    pipeline_dir: Path,
    pipeline_name: str
) -> Optional[PipelineMetadata]:
    """
    Lädt Pipeline-Metadaten aus JSON-Datei.
    
    Sucht nach pipeline.json oder {pipeline_name}.json im Pipeline-Verzeichnis.
    pipeline.json hat Vorrang vor {pipeline_name}.json.
    
    Args:
        pipeline_dir: Pfad zum Pipeline-Verzeichnis
        pipeline_name: Name der Pipeline (für {pipeline_name}.json)
    
    Returns:
        PipelineMetadata-Objekt oder None wenn keine Metadaten gefunden wurden
    
    Raises:
        json.JSONDecodeError: Wenn JSON-Datei ungültig ist (wird geloggt und None zurückgegeben)
    """
    # Zuerst nach pipeline.json suchen
    metadata_path = pipeline_dir / "pipeline.json"
    
    # Falls nicht vorhanden, nach {pipeline_name}.json suchen
    if not metadata_path.exists():
        metadata_path = pipeline_dir / f"{pipeline_name}.json"
    
    # Wenn keine Metadaten-Datei gefunden, None zurückgeben
    if not metadata_path.exists() or not metadata_path.is_file():
        return None
    
    try:
        # JSON-Datei laden
        with open(metadata_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Metadaten-Objekt erstellen
        # Normalize webhook_key: empty string or null becomes None
        webhook_key = data.get("webhook_key")
        if webhook_key == "" or webhook_key is None:
            webhook_key = None
        else:
            webhook_key = str(webhook_key).strip()
            if not webhook_key:
                webhook_key = None
        
        metadata = PipelineMetadata(
            cpu_hard_limit=data.get("cpu_hard_limit"),
            mem_hard_limit=data.get("mem_hard_limit"),
            cpu_soft_limit=data.get("cpu_soft_limit"),
            mem_soft_limit=data.get("mem_soft_limit"),
            timeout=data.get("timeout"),
            retry_attempts=data.get("retry_attempts"),
            retry_strategy=data.get("retry_strategy"),
            description=data.get("description"),
            tags=data.get("tags"),
            enabled=data.get("enabled", True),  # Standard: true
            default_env=data.get("default_env", {}),
            webhook_key=webhook_key
        )
        
        return metadata
    
    except json.JSONDecodeError as e:
        # Ungültige JSON-Datei: Fehler loggen, aber Pipeline nicht ignorieren
        # (Pipeline kann auch ohne Metadaten funktionieren)
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(
            f"Ungültige JSON-Datei für Pipeline {pipeline_name}: {metadata_path}. "
            f"Fehler: {e}. Pipeline wird ohne Metadaten geladen."
        )
        return None
    
    except Exception as e:
        # Andere Fehler (z.B. PermissionError): Loggen und None zurückgeben
        import logging
        logger = logging.getLogger(__name__)
        logger.error(
            f"Fehler beim Laden der Metadaten für Pipeline {pipeline_name}: {metadata_path}. "
            f"Fehler: {e}. Pipeline wird ohne Metadaten geladen."
        )
        return None


def get_pipeline(name: str) -> Optional[DiscoveredPipeline]:
    """
    Gibt eine spezifische Pipeline nach Name zurück.
    
    Args:
        name: Pipeline-Name (Verzeichnisname)
    
    Returns:
        DiscoveredPipeline-Objekt oder None wenn Pipeline nicht gefunden wurde
    """
    pipelines = discover_pipelines()
    for pipeline in pipelines:
        if pipeline.name == name:
            return pipeline
    return None


def invalidate_cache() -> None:
    """
    Invalidiert den Pipeline-Cache.
    
    Wird nach Git-Sync aufgerufen, um sicherzustellen, dass neue oder
    geänderte Pipelines erkannt werden.
    """
    global _pipeline_cache, _cache_timestamp
    _pipeline_cache = None
    _cache_timestamp = None


def set_pipeline_webhook_key(name: str, webhook_key: Optional[str]) -> None:
    """
    Setzt oder entfernt den Webhook-Schlüssel einer Pipeline durch Aktualisierung der pipeline.json.
    
    Aktualisiert das `webhook_key` Feld in pipeline.json oder {pipeline_name}.json.
    Die Datei wird atomar geschrieben (mit temporärer Datei) um Race-Conditions zu vermeiden.
    
    Args:
        name: Pipeline-Name
        webhook_key: Webhook-Schlüssel (None oder leer = Webhooks deaktivieren)
    
    Raises:
        ValueError: Wenn Pipeline nicht gefunden wurde
        IOError: Wenn Datei nicht geschrieben werden kann
    """
    # Pipeline finden
    pipeline = get_pipeline(name)
    if pipeline is None:
        raise ValueError(f"Pipeline nicht gefunden: {name}")
    
    pipeline_dir = pipeline.path
    
    # Metadaten-Datei finden (pipeline.json oder {pipeline_name}.json)
    metadata_path = pipeline_dir / "pipeline.json"
    if not metadata_path.exists():
        metadata_path = pipeline_dir / f"{name}.json"
    
    # Wenn keine Metadaten-Datei existiert, erstelle eine
    if not metadata_path.exists():
        # Neue pipeline.json erstellen
        metadata_path = pipeline_dir / "pipeline.json"
        data = {}
    else:
        # Bestehende Datei laden
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise IOError(f"Ungültige JSON-Datei: {metadata_path}. Fehler: {e}")
        except Exception as e:
            raise IOError(f"Fehler beim Lesen der Metadaten-Datei: {e}")
    
    # webhook_key normalisieren: None oder leerer String = entfernen
    if webhook_key is None or (isinstance(webhook_key, str) and webhook_key.strip() == ""):
        # Webhook-Schlüssel entfernen (Webhooks deaktivieren)
        data.pop("webhook_key", None)
    else:
        # Webhook-Schlüssel setzen (Webhooks aktivieren)
        data["webhook_key"] = str(webhook_key).strip()
    
    # Atomar schreiben (mit temporärer Datei)
    temp_path = metadata_path.with_suffix(metadata_path.suffix + ".tmp")
    
    try:
        # In temporäre Datei schreiben
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        # Atomar umbenennen (ersetzt Original-Datei)
        temp_path.replace(metadata_path)
        
        # Cache invalidieren, damit Änderung sofort sichtbar ist
        invalidate_cache()
        
    except Exception as e:
        # Temporäre Datei aufräumen bei Fehler
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        raise IOError(f"Fehler beim Schreiben der Metadaten-Datei: {e}") from e


def get_cache_info() -> Dict[str, Any]:
    """
    Gibt Informationen über den Pipeline-Cache zurück.
    
    Returns:
        Dictionary mit Cache-Status (timestamp, pipeline_count)
    """
    return {
        "timestamp": _cache_timestamp.isoformat() if _cache_timestamp else None,
        "pipeline_count": len(_pipeline_cache) if _pipeline_cache else 0,
        "cached": _pipeline_cache is not None
    }


def set_pipeline_enabled(name: str, enabled: bool) -> None:
    """
    Aktiviert oder deaktiviert eine Pipeline durch Aktualisierung der pipeline.json.
    
    Aktualisiert das `enabled` Feld in pipeline.json oder {pipeline_name}.json.
    Die Datei wird atomar geschrieben (mit temporärer Datei) um Race-Conditions zu vermeiden.
    
    Args:
        name: Pipeline-Name
        enabled: True um Pipeline zu aktivieren, False um zu deaktivieren
    
    Raises:
        ValueError: Wenn Pipeline nicht gefunden wurde
        IOError: Wenn Datei nicht geschrieben werden kann
    """
    # Pipeline finden
    pipeline = get_pipeline(name)
    if pipeline is None:
        raise ValueError(f"Pipeline nicht gefunden: {name}")
    
    pipeline_dir = pipeline.path
    
    # Metadaten-Datei finden (pipeline.json oder {pipeline_name}.json)
    metadata_path = pipeline_dir / "pipeline.json"
    if not metadata_path.exists():
        metadata_path = pipeline_dir / f"{name}.json"
    
    # Wenn keine Metadaten-Datei existiert, erstelle eine
    if not metadata_path.exists():
        # Neue pipeline.json erstellen
        metadata_path = pipeline_dir / "pipeline.json"
        data = {"enabled": enabled}
    else:
        # Bestehende Datei laden
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise IOError(f"Ungültige JSON-Datei: {metadata_path}. Fehler: {e}")
        except Exception as e:
            raise IOError(f"Fehler beim Lesen der Metadaten-Datei: {e}")
    
    # enabled-Feld aktualisieren
    data["enabled"] = enabled
    
    # Atomar schreiben (mit temporärer Datei)
    temp_path = metadata_path.with_suffix(metadata_path.suffix + ".tmp")
    
    try:
        # In temporäre Datei schreiben
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        # Atomar umbenennen (ersetzt Original-Datei)
        temp_path.replace(metadata_path)
        
        # Cache invalidieren, damit Änderung sofort sichtbar ist
        invalidate_cache()
        
    except Exception as e:
        # Temporäre Datei aufräumen bei Fehler
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        raise IOError(f"Fehler beim Schreiben der Metadaten-Datei: {e}") from e
