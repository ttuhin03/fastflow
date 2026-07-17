"""
Regression-Tests für Secrets-Scoping bei der Pipeline-Execution (TE-19).

Vor dem Fix injizierte der Executor get_all_secrets() (ALLE DB-Secrets) ungefiltert
in den Env von JEDEM Pipeline-Run - Pipeline A konnte damit Secrets sehen, die für
Pipeline B gedacht waren. Diese Tests stellen sicher, dass eine Pipeline zur Laufzeit
nur die Secrets erhält, die sie in pipeline.json (Feld "secrets") explizit deklariert.
"""

from unittest.mock import AsyncMock

from app.models import Secret
from app.services.pipeline_discovery import discover_pipelines
from app.services.secrets import encrypt, get_all_secrets, get_secrets_by_keys
from app.executor import core as executor_core


def _make_secret(key: str, value: str) -> Secret:
    return Secret(key=key, value=encrypt(value), is_parameter=False)


class TestGetSecretsByKeys:
    def test_returns_only_requested_keys(self, test_session):
        test_session.add(_make_secret("SECRET_A", "value-a"))
        test_session.add(_make_secret("SECRET_B", "value-b"))
        test_session.commit()

        result = get_secrets_by_keys(test_session, ["SECRET_A"])

        assert result == {"SECRET_A": "value-a"}

    def test_empty_key_list_returns_empty_dict(self, test_session):
        test_session.add(_make_secret("SECRET_A", "value-a"))
        test_session.commit()

        assert get_secrets_by_keys(test_session, []) == {}

    def test_unknown_key_is_ignored(self, test_session):
        test_session.add(_make_secret("SECRET_A", "value-a"))
        test_session.commit()

        result = get_secrets_by_keys(test_session, ["SECRET_A", "DOES_NOT_EXIST"])

        assert result == {"SECRET_A": "value-a"}

    def test_get_all_secrets_still_returns_everything(self, test_session):
        """get_all_secrets() bleibt bewusst ungeschützt - Aufrufer außerhalb der
        Pipeline-Execution (z.B. Admin-Tools) sind dafür verantwortlich, es nicht
        pipeline-ungebunden zu verwenden."""
        test_session.add(_make_secret("SECRET_A", "value-a"))
        test_session.add(_make_secret("SECRET_B", "value-b"))
        test_session.commit()

        result = get_all_secrets(test_session)

        assert result == {"SECRET_A": "value-a", "SECRET_B": "value-b"}


class TestPipelineRunSecretScoping:
    """End-to-end: run_pipeline() darf nur deklarierte Secrets injizieren."""

    async def test_pipeline_does_not_see_other_pipelines_secrets(
        self, test_session, temp_pipelines_dir, monkeypatch
    ):
        # Zwei Secrets in der DB: eines für pipeline_a, eines für pipeline_b
        test_session.add(_make_secret("PIPELINE_A_SECRET", "secret-a-value"))
        test_session.add(_make_secret("PIPELINE_B_SECRET", "secret-b-value"))
        test_session.commit()

        pipeline_a_dir = temp_pipelines_dir / "pipeline_a"
        pipeline_a_dir.mkdir()
        (pipeline_a_dir / "main.py").write_text("print('a')")
        (pipeline_a_dir / "pipeline.json").write_text(
            '{"secrets": ["PIPELINE_A_SECRET"]}'
        )

        discover_pipelines(force_refresh=True)

        # Container-Start abkoppeln (kein echtes Docker/K8s im Unit-Test nötig)
        monkeypatch.setattr(executor_core, "_run_container_task", AsyncMock())

        run = await executor_core.run_pipeline("pipeline_a", session=test_session)

        assert run.env_vars.get("PIPELINE_A_SECRET") == "secret-a-value"
        assert "PIPELINE_B_SECRET" not in run.env_vars

    async def test_pipeline_without_secrets_declaration_gets_none(
        self, test_session, temp_pipelines_dir, monkeypatch
    ):
        test_session.add(_make_secret("SOME_OTHER_SECRET", "value"))
        test_session.commit()

        pipeline_dir = temp_pipelines_dir / "no_secrets_pipeline"
        pipeline_dir.mkdir()
        (pipeline_dir / "main.py").write_text("print('ok')")

        discover_pipelines(force_refresh=True)

        monkeypatch.setattr(executor_core, "_run_container_task", AsyncMock())

        run = await executor_core.run_pipeline("no_secrets_pipeline", session=test_session)

        assert "SOME_OTHER_SECRET" not in run.env_vars
