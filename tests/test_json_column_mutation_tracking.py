"""
Tests für den Schreib-Kontrakt der JSON-Spalten in app/models.py.

Bei einer nackten ``Column(JSON)`` erkennt SQLAlchemy ein In-Place-Schreiben
(``d["k"] = v``) nicht, nimmt die Spalte nicht ins UPDATE auf und verwirft den
Wert still. Auf ``PipelineRun.env_vars`` hat das den Fehlertyp gescheiterter Runs
gekostet, auf ``RunCellLog.outputs`` schon vorher ein Notebook-Bild — dort steht
seit damals ein Reassign-Workaround in cell_logs.py.

Alle JSON-Spalten sind deshalb ``MutableDict.as_mutable(JSON)``. Diese Tests
halten beides fest: dass In-Place-Schreiben auf der obersten Ebene ankommt, und
dass es *eine Ebene tiefer* weiterhin nicht ankommt. Die zweite Hälfte ist keine
Marotte, sondern der Grund, warum der Workaround in cell_logs.py stehen bleiben
muss.
"""

from uuid import uuid4

import pytest

from app.models import AuditLogEntry, PipelineRun, RunCellLog, RunStatus


def _pipeline_run(**kwargs):
    return PipelineRun(
        pipeline_name="demo",
        status=RunStatus.PENDING,
        log_file=f"/tmp/{uuid4()}.log",
        **kwargs,
    )


# (Label, Objekt-Factory, Spaltenname) — je eine JSON-Spalte pro Modell.
JSON_COLUMNS = [
    ("PipelineRun.env_vars", lambda: _pipeline_run(env_vars={"A": "1"}), "env_vars"),
    ("PipelineRun.parameters", lambda: _pipeline_run(parameters={"A": "1"}), "parameters"),
    (
        "RunCellLog.outputs",
        lambda: RunCellLog(run_id=uuid4(), cell_index=0, outputs={"A": "1"}),
        "outputs",
    ),
    (
        "AuditLogEntry.details",
        lambda: AuditLogEntry(action="run_start", resource_type="run", details={"A": "1"}),
        "details",
    ),
]


def _reload(session, obj, column):
    """Committet, wirft den Identity-Map-Stand weg und liest die Spalte neu."""
    session.add(obj)
    session.commit()
    session.expire_all()
    key = obj.id if hasattr(obj, "id") else (obj.run_id, obj.cell_index)
    return getattr(session.get(type(obj), key), column)


@pytest.mark.parametrize("label,factory,column", JSON_COLUMNS, ids=[c[0] for c in JSON_COLUMNS])
def test_in_place_write_survives_the_commit(test_session, label, factory, column):
    obj = factory()
    test_session.add(obj)
    test_session.commit()

    getattr(obj, column)["B"] = "2"

    assert _reload(test_session, obj, column) == {"A": "1", "B": "2"}


@pytest.mark.parametrize("label,factory,column", JSON_COLUMNS, ids=[c[0] for c in JSON_COLUMNS])
def test_whole_value_assignment_still_works(test_session, label, factory, column):
    """Die bisherige Schreibweise darf MutableDict nicht kaputt machen."""
    obj = factory()
    test_session.add(obj)
    test_session.commit()

    setattr(obj, column, {"C": "3"})

    assert _reload(test_session, obj, column) == {"C": "3"}


@pytest.mark.parametrize(
    "label,factory,column",
    [c for c in JSON_COLUMNS if c[0] != "PipelineRun.env_vars"],
    ids=[c[0] for c in JSON_COLUMNS if c[0] != "PipelineRun.env_vars"],
)
def test_none_assignment_still_works(test_session, label, factory, column):
    """
    MutableDict.coerce lässt None durch.

    Relevant, weil parameters=None tatsächlich zugewiesen wird (siehe
    kubernetes_backend.py) und outputs/details ohnehin Optional sind.
    """
    obj = factory()
    test_session.add(obj)
    test_session.commit()

    setattr(obj, column, None)

    assert _reload(test_session, obj, column) is None


def test_nested_mutation_is_still_not_tracked(test_session):
    """
    Die Schranke von MutableDict: eine Ebene, nicht mehr.

    Genau deshalb baut cell_logs.py das outputs-Dict für ein neues Bild neu auf
    statt an outputs["images"] zu appenden. Wer diesen Test kippen sieht, hat
    entweder MutableList/ein verschachteltes Tracking eingezogen — dann darf der
    Workaround weg — oder die Spalte verloren.
    """
    row = RunCellLog(run_id=uuid4(), cell_index=0, outputs={"images": []})
    test_session.add(row)
    test_session.commit()

    row.outputs["images"].append({"mime": "image/png", "data": "BASE64"})

    assert _reload(test_session, row, "outputs") == {"images": []}


def test_reassigning_the_nested_value_does_work(test_session):
    """Der Weg, den cell_logs.py nimmt — die Gegenprobe zum Test darüber."""
    row = RunCellLog(run_id=uuid4(), cell_index=0, outputs={"images": []})
    test_session.add(row)
    test_session.commit()

    outputs = dict(row.outputs or {})
    outputs["images"] = list(outputs.get("images", [])) + [
        {"mime": "image/png", "data": "BASE64"}
    ]
    row.outputs = outputs

    persisted = _reload(test_session, row, "outputs")
    assert persisted == {"images": [{"mime": "image/png", "data": "BASE64"}]}
