"""
Tests dafür, dass ein Infrastruktur-Fehler den Weg bis in die UI findet.

Der Executor hielt den Fehlertyp eines gescheiterten Runs mit
``run.env_vars["_fastflow_error_type"] = ...`` fest — einer In-Place-Mutation auf
einer nackten JSON-Spalte. SQLAlchemy sieht solche Mutationen nicht, nimmt die
Spalte nicht ins UPDATE auf und verwirft sie still. Der Status kam an (skalare
Zuweisung, also getrackt), Fehlertyp und Meldung nie: Die Detailseite zeigte
einen Run auf FAILED, ohne Typ, ohne Meldung — und ohne Logs, weil ein
Infrastruktur-Fehler entsteht, bevor der Container überhaupt läuft.

Verdeckt wurde das vom ``if run.env_vars is None``-Zweig in den Handlern: Nur in
diesem Fall gab es eine echte Zuweisung und damit einen getrackten Wert. Mit
``default_factory=dict`` ist env_vars aber nie None, der Zweig griff nie.

API und Frontend waren in Ordnung — beide lesen error_type/error_message seit
immer. Kaputt war allein die Persistenz.
"""

import pytest

from app.executor.core import (
    INFRASTRUCTURE_ERROR_MESSAGE_CHARS,
    mark_infrastructure_error,
)
from app.models import PipelineRun, RunStatus

ENOSPC = OSError("[Errno 28] No space left on device")


def _failed_run(session, log_file, env_vars=None):
    """Ein Run mit gefüllten env_vars — der Normalfall, in dem die Mutation verloren ging."""
    run = PipelineRun(
        pipeline_name="demo_instanz_energy",
        status=RunStatus.PENDING,
        log_file=str(log_file),
        env_vars=env_vars if env_vars is not None else {"SOME_VAR": "wert"},
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def test_error_type_survives_the_commit(test_session, tmp_path):
    """
    Die Regression. Ohne MutableDict auf der Spalte ist error_type nach dem
    Commit wieder weg, während der Status ankommt.
    """
    run = _failed_run(test_session, tmp_path / "run.log")

    run.status = RunStatus.FAILED
    mark_infrastructure_error(run, ENOSPC)
    test_session.add(run)
    test_session.commit()
    test_session.expire_all()

    reloaded = test_session.get(PipelineRun, run.id)
    assert reloaded.status == RunStatus.FAILED
    assert reloaded.env_vars["_fastflow_error_type"] == "infrastructure_error"
    assert "No space left on device" in reloaded.env_vars["_fastflow_error_message"]


def test_existing_env_vars_are_kept(test_session, tmp_path):
    """Die Fehler-Metadaten kommen dazu, sie ersetzen die Env-Vars nicht."""
    run = _failed_run(test_session, tmp_path / "run.log", env_vars={"DB_HOST": "db.intern"})

    mark_infrastructure_error(run, ENOSPC)
    test_session.add(run)
    test_session.commit()
    test_session.expire_all()

    assert test_session.get(PipelineRun, run.id).env_vars["DB_HOST"] == "db.intern"


def test_run_detail_exposes_error_type_and_message(authenticated_client, test_session, tmp_path):
    """Der Weg, über den die Detailseite Badge und Meldung rendert."""
    run = _failed_run(test_session, tmp_path / "run.log")
    run.status = RunStatus.FAILED
    run.exit_code = -1
    mark_infrastructure_error(run, ENOSPC)
    test_session.add(run)
    test_session.commit()

    body = authenticated_client.get(f"/api/runs/{run.id}").json()

    assert body["status"] == "FAILED"
    assert body["error_type"] == "infrastructure_error"
    assert "No space left on device" in body["error_message"]


def test_runs_list_exposes_error_type(authenticated_client, test_session, tmp_path):
    """Die Übersicht zeigt dasselbe Badge und liest aus einem anderen Endpoint."""
    run = _failed_run(test_session, tmp_path / "run.log")
    run.status = RunStatus.FAILED
    mark_infrastructure_error(run, ENOSPC)
    test_session.add(run)
    test_session.commit()

    runs = authenticated_client.get("/api/runs?limit=10").json()["runs"]

    entry = next(r for r in runs if r["id"] == str(run.id))
    assert entry["error_type"] == "infrastructure_error"


def test_secrets_stay_masked_next_to_the_error_metadata(
    authenticated_client, test_session, tmp_path
):
    """
    Die Fehler-Metadaten liegen in derselben Spalte wie die Secrets.

    _mask_env_vars gibt nur _fastflow_*-Schlüssel im Klartext heraus; dass der
    Fix daran nichts verschiebt, gehört mitgeprüft.
    """
    run = _failed_run(test_session, tmp_path / "run.log", env_vars={"SMTP_PASSWORD": "geheim"})
    mark_infrastructure_error(run, ENOSPC)
    test_session.add(run)
    test_session.commit()

    env_vars = authenticated_client.get(f"/api/runs/{run.id}").json()["env_vars"]

    assert env_vars["SMTP_PASSWORD"] == "***"
    assert env_vars["_fastflow_error_type"] == "infrastructure_error"


def test_run_log_explains_why_it_is_empty(test_session, tmp_path):
    """
    Der zweite Teil des Befunds: kein Container, also keine Container-Logs.

    Statt eines leeren Log-Tabs ohne Hinweis stehen dort jetzt zwei Zeilen.
    """
    log_file = tmp_path / "run.log"
    run = _failed_run(test_session, log_file)

    mark_infrastructure_error(run, ENOSPC)

    content = log_file.read_text(encoding="utf-8")
    assert "Infrastruktur-Fehler beendet" in content
    assert "No space left on device" in content


def test_run_log_marker_is_appended_not_overwritten(test_session, tmp_path):
    """Hat der Run schon etwas geloggt, bleibt das stehen."""
    log_file = tmp_path / "run.log"
    log_file.write_text("vorher geschriebene Zeile\n", encoding="utf-8")
    run = _failed_run(test_session, log_file)

    mark_infrastructure_error(run, ENOSPC)

    content = log_file.read_text(encoding="utf-8")
    assert content.startswith("vorher geschriebene Zeile\n")
    assert "Infrastruktur-Fehler" in content


def test_long_message_is_capped(test_session, tmp_path):
    """
    copytree sammelt bei ENOSPC einen Eintrag pro Datei ein.

    Bei einer Pipeline mit dreistellig vielen Dateien sind das Dutzende
    Kilobyte — nichts, was in ein Fehler-Banner gehört.
    """
    run = _failed_run(test_session, tmp_path / "run.log")
    huge = OSError("x" * (INFRASTRUCTURE_ERROR_MESSAGE_CHARS * 3))

    mark_infrastructure_error(run, huge)

    message = run.env_vars["_fastflow_error_message"]
    assert len(message) < INFRASTRUCTURE_ERROR_MESSAGE_CHARS * 2
    assert "gekürzt" in message
    assert str(run.id) in message


def test_short_message_is_not_touched(test_session, tmp_path):
    run = _failed_run(test_session, tmp_path / "run.log")

    mark_infrastructure_error(run, ENOSPC)

    assert run.env_vars["_fastflow_error_message"] == str(ENOSPC)


@pytest.mark.parametrize("log_file", ["", "/nicht/beschreibbar/run.log"])
def test_unwritable_log_does_not_lose_the_error_type(test_session, log_file):
    """
    Das Log ist die Zugabe, der Fehlertyp am Run die Hauptsache.

    Ein nicht beschreibbarer Pfad darf den Fehlerpfad nicht kapern — sonst
    verschluckt ein zweiter Fehler im except-Block den ersten.
    """
    run = _failed_run(test_session, log_file)

    mark_infrastructure_error(run, ENOSPC)

    assert run.env_vars["_fastflow_error_type"] == "infrastructure_error"


def test_missing_log_directory_is_created(test_session, tmp_path):
    """Der Pfad kann auf ein Verzeichnis zeigen, das es noch nicht gibt."""
    log_file = tmp_path / "noch" / "nicht" / "da" / "run.log"
    run = _failed_run(test_session, log_file)

    mark_infrastructure_error(run, ENOSPC)

    assert "Infrastruktur-Fehler" in log_file.read_text(encoding="utf-8")


def test_null_env_vars_from_the_database_still_get_the_error_type(test_session, tmp_path):
    """
    Die Spalte ist nullable — der Default aus dem Modell gilt nur in Python.

    Eine Zeile mit SQL NULL lädt als ``None``, und genau so kommt der Run hier
    an: aus ``session.get()`` im except-Block. Ein TypeError an dieser Stelle
    verschluckt nicht nur die Fehler-Metadaten, er verhindert auch den Commit
    darunter — der Run bliebe auf RUNNING stehen, also in dem Zustand, gegen den
    diese Funktion überhaupt geschrieben ist.
    """
    run = _failed_run(test_session, tmp_path / "run.log")
    run.env_vars = None
    test_session.add(run)
    test_session.commit()
    test_session.expire_all()

    reloaded = test_session.get(PipelineRun, run.id)
    assert reloaded.env_vars is None

    reloaded.status = RunStatus.FAILED
    mark_infrastructure_error(reloaded, ENOSPC)
    test_session.add(reloaded)
    test_session.commit()
    test_session.expire_all()

    persisted = test_session.get(PipelineRun, run.id)
    assert persisted.status == RunStatus.FAILED
    assert persisted.env_vars["_fastflow_error_type"] == "infrastructure_error"


def test_a_log_path_that_is_not_even_openable_does_not_hijack_the_error_path(test_session):
    """
    Die Zugabe darf auch dann nicht knallen, wenn sie nicht nur an Rechten scheitert.

    Ein Nullbyte im Pfad ist kein ``OSError``, sondern ein ``ValueError`` aus
    ``mkdir``/``open``. Ein zu enges except hier kostet den Fehlertyp am Run und
    damit den Grund, aus dem der Run rot ist.
    """
    run = _failed_run(test_session, "/tmp/kein\x00pfad.log")

    mark_infrastructure_error(run, ENOSPC)

    assert run.env_vars["_fastflow_error_type"] == "infrastructure_error"
    assert "No space left on device" in run.env_vars["_fastflow_error_message"]

