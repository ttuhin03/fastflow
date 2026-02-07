"""
Unit-Tests für PipelineMetadata (app.services.pipeline_discovery).

Testet PipelineMetadata-Initialisierung, _normalize_downstream_triggers und to_dict.
"""

import pytest
from pathlib import Path

from app.services.pipeline_discovery import PipelineMetadata, DiscoveredPipeline


class TestPipelineMetadata:
    """Tests für PipelineMetadata-Klasse."""

    def test_default_values(self):
        """Default-Werte bei minimaler Initialisierung."""
        meta = PipelineMetadata()
        assert meta.enabled is True
        assert meta.tags == []
        assert meta.default_env == {}
        assert meta.webhook_key is None
        assert meta.python_version is None
        assert meta.type == "script"
        assert meta.restart_on_crash is False
        assert meta.restart_cooldown == 60

    def test_webhook_key_empty_string_becomes_none(self):
        """Leerer webhook_key wird zu None normalisiert."""
        meta = PipelineMetadata(webhook_key="")
        assert meta.webhook_key is None
        meta2 = PipelineMetadata(webhook_key="   ")
        assert meta2.webhook_key is None

    def test_webhook_key_valid(self):
        """Valider webhook_key bleibt erhalten."""
        meta = PipelineMetadata(webhook_key="my-secret-key")
        assert meta.webhook_key == "my-secret-key"

    def test_python_version_empty_becomes_none(self):
        """Leerer python_version wird zu None."""
        meta = PipelineMetadata(python_version="")
        assert meta.python_version is None

    def test_type_normalized_to_script(self):
        """Unbekannter type wird zu 'script'."""
        meta = PipelineMetadata(type="unknown")
        assert meta.type == "script"

    def test_type_notebook(self):
        """type='notebook' wird akzeptiert."""
        meta = PipelineMetadata(type="notebook")
        assert meta.type == "notebook"

    def test_tags_default_empty_list(self):
        """tags=None wird zu []."""
        meta = PipelineMetadata(tags=None)
        assert meta.tags == []

    def test_downstream_triggers_stored(self):
        """downstream_triggers werden normalisiert gespeichert."""
        raw = [
            {"pipeline": "p2", "on_success": True, "on_failure": False},
        ]
        meta = PipelineMetadata(downstream_triggers=raw)
        assert len(meta.downstream_triggers) == 1
        assert meta.downstream_triggers[0]["pipeline"] == "p2"


class TestNormalizeDownstreamTriggers:
    """Tests für _normalize_downstream_triggers."""

    def test_valid_single_trigger(self):
        """Valider Trigger wird normalisiert."""
        raw = [{"pipeline": "downstream_pipeline", "on_success": True, "on_failure": False}]
        result = PipelineMetadata._normalize_downstream_triggers(raw)
        assert len(result) == 1
        assert result[0]["pipeline"] == "downstream_pipeline"
        assert result[0]["on_success"] is True
        assert result[0]["on_failure"] is False

    def test_default_on_success_on_failure(self):
        """Default on_success=True, on_failure=False."""
        raw = [{"pipeline": "p2"}]
        result = PipelineMetadata._normalize_downstream_triggers(raw)
        assert result[0]["on_success"] is True
        assert result[0]["on_failure"] is False

    def test_run_config_id_in_trigger(self):
        """run_config_id wird aus dem Trigger übernommen."""
        raw = [{"pipeline": "p2", "on_success": True, "on_failure": False, "run_config_id": "prod"}]
        result = PipelineMetadata._normalize_downstream_triggers(raw)
        assert len(result) == 1
        assert result[0]["run_config_id"] == "prod"

    def test_run_config_id_empty_ignored(self):
        """Leeres run_config_id wird zu None."""
        raw = [{"pipeline": "p2", "run_config_id": ""}]
        result = PipelineMetadata._normalize_downstream_triggers(raw)
        assert result[0]["run_config_id"] is None

    def test_empty_pipeline_skipped(self):
        """Trigger mit leerem pipeline wird übersprungen."""
        raw = [
            {"pipeline": "valid"},
            {"pipeline": ""},
            {"pipeline": "   "},
        ]
        result = PipelineMetadata._normalize_downstream_triggers(raw)
        assert len(result) == 1
        assert result[0]["pipeline"] == "valid"

    def test_non_dict_skipped(self):
        """Nicht-Dict-Einträge werden übersprungen."""
        raw = [{"pipeline": "p1"}, "invalid", {"pipeline": "p2"}]
        result = PipelineMetadata._normalize_downstream_triggers(raw)
        assert len(result) == 2

    def test_pipeline_whitespace_stripped(self):
        """Whitespace um pipeline wird entfernt."""
        raw = [{"pipeline": "  my_pipeline  "}]
        result = PipelineMetadata._normalize_downstream_triggers(raw)
        assert result[0]["pipeline"] == "my_pipeline"

    def test_empty_list(self):
        """Leere Liste bleibt leer."""
        result = PipelineMetadata._normalize_downstream_triggers([])
        assert result == []


class TestPipelineMetadataToDict:
    """Tests für to_dict()."""

    def test_to_dict_minimal(self):
        """Minimale Metadaten: nur gesetzte Felder."""
        meta = PipelineMetadata(enabled=True)
        d = meta.to_dict()
        assert "enabled" not in d  # enabled=True wird weggelassen (Default)
        assert "tags" not in d

    def test_to_dict_with_values(self):
        """Gesetzte Werte erscheinen im Dict."""
        meta = PipelineMetadata(
            description="Test",
            timeout=300,
            tags=["a", "b"],
        )
        d = meta.to_dict()
        assert d["description"] == "Test"
        assert d["timeout"] == 300
        assert d["tags"] == ["a", "b"]


class TestDiscoveredPipeline:
    """Tests für DiscoveredPipeline."""

    def test_is_enabled_default(self):
        """DiscoveredPipeline mit Default-Metadata ist enabled."""
        p = DiscoveredPipeline(name="test", path=Path("/x"), has_requirements=False)
        assert p.is_enabled() is True

    def test_is_enabled_false(self):
        """Metadata.enabled=False -> is_enabled() False."""
        meta = PipelineMetadata(enabled=False)
        p = DiscoveredPipeline(name="test", path=Path("/x"), has_requirements=False, metadata=meta)
        assert p.is_enabled() is False

    def test_get_timeout_none(self):
        """timeout=None -> get_timeout() None."""
        p = DiscoveredPipeline(name="test", path=Path("/x"), has_requirements=False)
        assert p.get_timeout() is None

    def test_get_timeout_zero_unlimited(self):
        """timeout=0 bedeutet unbegrenzt (None)."""
        meta = PipelineMetadata(timeout=0)
        p = DiscoveredPipeline(name="test", path=Path("/x"), has_requirements=False, metadata=meta)
        assert p.get_timeout() is None

    def test_get_timeout_value(self):
        """timeout=300 -> get_timeout() 300."""
        meta = PipelineMetadata(timeout=300)
        p = DiscoveredPipeline(name="test", path=Path("/x"), has_requirements=False, metadata=meta)
        assert p.get_timeout() == 300

    def test_get_entry_type_script_default(self):
        """Default type ist script."""
        p = DiscoveredPipeline(name="test", path=Path("/x"), has_requirements=False)
        assert p.get_entry_type() == "script"

    def test_get_entry_type_notebook(self):
        """type=notebook in Metadata."""
        meta = PipelineMetadata(type="notebook")
        p = DiscoveredPipeline(name="test", path=Path("/x"), has_requirements=False, metadata=meta)
        assert p.get_entry_type() == "notebook"
