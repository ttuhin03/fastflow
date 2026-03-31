from app.models import User


def test_unlink_provider_success(authenticated_client, test_session, test_user):
    test_user.github_id = "gh-123"
    test_user.google_id = "g-456"
    test_session.add(test_user)
    test_session.commit()

    response = authenticated_client.delete("/api/auth/link/github")
    assert response.status_code == 200
    body = response.json()
    assert body["has_github"] is False
    assert body["has_google"] is True

    refreshed = test_session.get(User, test_user.id)
    assert refreshed is not None
    assert refreshed.github_id is None
    assert refreshed.google_id == "g-456"


def test_unlink_provider_fails_when_not_linked(authenticated_client, test_session, test_user):
    test_user.google_id = "g-456"
    test_session.add(test_user)
    test_session.commit()

    response = authenticated_client.delete("/api/auth/link/github")
    assert response.status_code == 400
    assert "nicht verknüpft" in response.json()["detail"]


def test_unlink_provider_fails_for_last_linked_provider(authenticated_client, test_session, test_user):
    test_user.github_id = "gh-123"
    test_session.add(test_user)
    test_session.commit()

    response = authenticated_client.delete("/api/auth/link/github")
    assert response.status_code == 400
    assert "letzte verknüpfte" in response.json()["detail"]

    refreshed = test_session.get(User, test_user.id)
    assert refreshed is not None
    assert refreshed.github_id == "gh-123"

