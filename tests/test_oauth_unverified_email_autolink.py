"""
Regression-Test für TE-20 (Account-Takeover via unverified-email Auto-Linking).

Ein OAuth-Login mit einer E-Mail, die zu einem bestehenden fastflow-Konto passt,
darf NUR dann automatisch verknüpft werden, wenn der Provider die Adresse als
verifiziert (verified/email_verified=true) meldet. Andernfalls muss der Flow auf
Anklopfen (Beitrittsanfrage, kein Token/Session) zurückfallen statt das
bestehende Konto des Opfers stillschweigend zu übernehmen.
"""

from sqlmodel import select

from app.auth.oauth_processing import process_oauth_login
from app.models import User, UserRole, UserStatus


async def _make_victim(test_session, email="victim@example.com") -> User:
    user = User(username="victim", email=email, role=UserRole.WRITE, status=UserStatus.ACTIVE)
    test_session.add(user)
    test_session.commit()
    test_session.refresh(user)
    return user


async def test_unverified_email_does_not_autolink_to_existing_user(test_session):
    """Angreifer-Szenario: E-Mail des Opfers als unverifizierte Zweit-Adresse -> kein Auto-Match."""
    victim = await _make_victim(test_session)

    attacker_oauth_data = {
        "id": 999999,
        "login": "attacker",
        "email": victim.email,
        "email_verified": False,
        "avatar_url": None,
    }

    user, link_only, anklopfen_only, is_new_user, registration_source = await process_oauth_login(
        provider="github",
        provider_id=str(attacker_oauth_data["id"]),
        email=attacker_oauth_data["email"],
        session=test_session,
        oauth_data=attacker_oauth_data,
    )

    # Der Angreifer darf NICHT als das Opfer eingeloggt werden.
    assert user.id != victim.id
    assert user.github_id == str(attacker_oauth_data["id"])
    # Kein direkter Login/Session: muss auf Anklopfen (Beitrittsanfrage) laufen.
    assert anklopfen_only is True
    assert link_only is False
    assert registration_source == "anklopfen"
    assert user.status == UserStatus.PENDING

    # Das Opfer-Konto bleibt unverändert (kein github_id gesetzt).
    test_session.refresh(victim)
    assert victim.github_id is None


async def test_verified_email_still_autolinks_to_existing_user(test_session):
    """Kontrolle: verifizierte E-Mail darf weiterhin normal auto-verknüpfen (kein Regressions-Bruch)."""
    victim = await _make_victim(test_session, email="realuser@example.com")

    oauth_data = {
        "id": 12345,
        "login": "realuser",
        "email": victim.email,
        "email_verified": True,
        "avatar_url": None,
    }

    user, link_only, anklopfen_only, is_new_user, registration_source = await process_oauth_login(
        provider="github",
        provider_id=str(oauth_data["id"]),
        email=oauth_data["email"],
        session=test_session,
        oauth_data=oauth_data,
    )

    assert user.id == victim.id
    assert anklopfen_only is False
    assert link_only is False
    test_session.refresh(victim)
    assert victim.github_id == str(oauth_data["id"])


async def test_unverified_initial_admin_email_does_not_grant_admin(test_session, monkeypatch):
    """INITIAL_ADMIN_EMAIL-Pfad ist derselbe Bug-Fall (schlimmer: Admin-Übernahme) - auch hier
    darf eine unverifizierte E-Mail weder ein bestehendes Konto zum Admin machen noch einen
    neuen Admin-Account für den Angreifer anlegen."""
    from app.core.config import config

    monkeypatch.setattr(config, "INITIAL_ADMIN_EMAIL", "admin@example.com")
    victim = await _make_victim(test_session, email="admin@example.com")
    assert victim.role != UserRole.ADMIN

    attacker_oauth_data = {
        "id": 424242,
        "login": "attacker",
        "email": "admin@example.com",
        "email_verified": False,
        "avatar_url": None,
    }

    user, link_only, anklopfen_only, is_new_user, registration_source = await process_oauth_login(
        provider="github",
        provider_id=str(attacker_oauth_data["id"]),
        email=attacker_oauth_data["email"],
        session=test_session,
        oauth_data=attacker_oauth_data,
    )

    assert user.id != victim.id
    assert user.role != UserRole.ADMIN
    assert anklopfen_only is True

    test_session.refresh(victim)
    assert victim.role != UserRole.ADMIN
    assert victim.github_id is None
