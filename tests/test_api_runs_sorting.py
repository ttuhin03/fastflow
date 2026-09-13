"""
Tests für die Sortierung von GET /api/runs (Query-Parameter sort_order).

Die Sortierung muss serverseitig über den gesamten gefilterten Datensatz laufen.
Vorher drehte das Frontend nur die aktuelle Seite um — "älteste zuerst" lieferte
damit die neuesten Runs in umgekehrter Reihenfolge statt der ältesten.
"""

from datetime import datetime, timedelta, timezone

from app.models import PipelineRun, RunStatus


def _make_run(name: str, minutes_ago: int) -> PipelineRun:
    return PipelineRun(
        pipeline_name=name,
        status=RunStatus.SUCCESS,
        log_file=f"/logs/{name}.log",
        started_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )


def _seed(test_session, count: int, name: str = "p") -> None:
    # minutes_ago=0 ist der neueste Run, minutes_ago=count-1 der älteste.
    for i in range(count):
        test_session.add(_make_run(name, minutes_ago=i))
    test_session.commit()


def test_default_sort_is_newest_first(authenticated_client, test_session):
    _seed(test_session, 5)

    response = authenticated_client.get("/api/runs")
    assert response.status_code == 200

    started = [r["started_at"] for r in response.json()["runs"]]
    assert started == sorted(started, reverse=True)


def test_sort_order_asc_returns_oldest_first(authenticated_client, test_session):
    _seed(test_session, 5)

    response = authenticated_client.get("/api/runs?sort_order=asc")
    assert response.status_code == 200

    started = [r["started_at"] for r in response.json()["runs"]]
    assert started == sorted(started)


def test_sort_order_asc_paginates_over_full_set(authenticated_client, test_session):
    """Kernfall: Seite 1 mit asc muss die global ältesten Runs liefern."""
    _seed(test_session, 5)

    all_desc = authenticated_client.get("/api/runs?limit=5").json()["runs"]
    expected_oldest = [r["id"] for r in reversed(all_desc)][:2]

    first_page_asc = authenticated_client.get("/api/runs?sort_order=asc&limit=2&offset=0")
    assert first_page_asc.status_code == 200
    assert [r["id"] for r in first_page_asc.json()["runs"]] == expected_oldest

    # Gegenprobe: das alte Verhalten hätte hier die zwei neuesten Runs
    # (umgedreht) geliefert.
    newest_two = [r["id"] for r in all_desc[:2]]
    assert [r["id"] for r in first_page_asc.json()["runs"]] != newest_two


def test_pagination_covers_every_run_without_duplicates(authenticated_client, test_session):
    """Identische started_at dürfen Runs nicht zwischen Seiten springen lassen."""
    same_moment = datetime.now(timezone.utc)
    for _ in range(6):
        test_session.add(
            PipelineRun(
                pipeline_name="tie",
                status=RunStatus.SUCCESS,
                log_file="/logs/tie.log",
                started_at=same_moment,
            )
        )
    test_session.commit()

    for order in ("asc", "desc"):
        seen: list[str] = []
        for offset in (0, 2, 4):
            page = authenticated_client.get(
                f"/api/runs?sort_order={order}&limit=2&offset={offset}"
            )
            assert page.status_code == 200
            seen.extend(r["id"] for r in page.json()["runs"])

        assert len(seen) == 6, f"{order}: unvollständige Pagination"
        assert len(set(seen)) == 6, f"{order}: Run mehrfach ausgeliefert"


def test_invalid_sort_order_is_rejected(authenticated_client):
    response = authenticated_client.get("/api/runs?sort_order=started_at;DROP")
    assert response.status_code == 422
