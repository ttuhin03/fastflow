"""
Zentrale OAuth-Logik für GitHub, Google, Microsoft und Custom OAuth.

- process_oauth_login: einheitliche Auswertung (Direkt-Login, Auto-Match, Link, INITIAL_ADMIN, Einladung)
- get_or_create_initial_admin: erster Admin über INITIAL_ADMIN_EMAIL (alle Provider)
- create_oauth_user: neuer User aus OAuth-Daten (Einladungs-Flow)
"""

import logging
from datetime import datetime, timezone
from typing import Literal, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import config
from app.core.database import retry_on_sqlite_io
from app.auth.github_oauth import delete_oauth_state, get_oauth_state
from app.models import Invitation, User, UserRole, UserStatus
from app.services.notifications import notify_admin_join_request

logger = logging.getLogger(__name__)
Provider = Literal["github", "google", "microsoft", "custom"]


def _provider_id_attr(provider: Provider) -> str:
    """Name des User-Felds für die Provider-Subject-ID."""
    if provider == "github":
        return "github_id"
    if provider == "google":
        return "google_id"
    if provider == "microsoft":
        return "microsoft_id"
    return "custom_oauth_id"


def _unique_username(session: Session, login: str, provider_id: str) -> str:
    base = (login or "user").replace(" ", "_")[:50]
    for cand in (base, f"{base}_{provider_id[:12]}" if len(provider_id) > 8 else f"{base}_{provider_id}"):
        stmt = select(User).where(User.username == cand)
        if retry_on_sqlite_io(lambda: session.exec(stmt).first(), session=session) is None:
            return cand
    return f"{base}_{provider_id}"


def get_or_create_initial_admin(
    session: Session,
    oauth_data: dict,
    provider: Provider,
) -> Tuple[Optional[User], bool]:
    """
    Holt oder erstellt den ersten Admin (INITIAL_ADMIN_EMAIL) für GitHub oder Google.
    Returns:
        (user, is_newly_created): is_newly_created=True nur wenn ein neuer User angelegt wurde.
    """
    id_attr = _provider_id_attr(provider)
    provider_id = str(oauth_data.get("id") or "")
    email = oauth_data.get("email")
    login = oauth_data.get("login") or oauth_data.get("name") or "user"
    avatar = oauth_data.get("avatar_url") or oauth_data.get("picture")

    # 1. Bereits mit dieser Provider-ID vorhanden
    stmt = select(User).where(getattr(User, id_attr) == provider_id)
    user = retry_on_sqlite_io(lambda: session.exec(stmt).first(), session=session)
    if user:
        logger.info("OAuth initial_admin: user=%s bereits mit %s verknüpft", user.username, provider)
        return (user, False)

    # 2. INITIAL_ADMIN_EMAIL: bestehenden User verknüpfen oder neuen Admin anlegen
    if email and config.INITIAL_ADMIN_EMAIL and email == config.INITIAL_ADMIN_EMAIL:
        stmt = select(User).where(User.email == email)
        user = retry_on_sqlite_io(lambda: session.exec(stmt).first(), session=session)
        if user:
            setattr(user, id_attr, provider_id)
            if avatar:
                user.avatar_url = avatar
            if provider == "github":
                user.github_login = oauth_data.get("login")
            user.role = UserRole.ADMIN
            session.add(user)
            session.commit()
            session.refresh(user)
            logger.info("OAuth initial_admin: bestehender User user=%s mit %s verknüpft, role=ADMIN", user.username, provider)
            return (user, False)
        username = _unique_username(session, login, provider_id)
        kwargs: dict = {id_attr: provider_id}
        if provider == "github":
            kwargs["github_login"] = oauth_data.get("login")
        user = User(
            username=username,
            email=email,
            role=UserRole.ADMIN,
            avatar_url=avatar,
            **kwargs,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        logger.info("OAuth initial_admin: neuer Admin user=%s angelegt (provider=%s)", user.username, provider)
        return (user, True)

    return (None, False)


def create_oauth_user(
    session: Session,
    oauth_data: dict,
    role: UserRole,
    provider: Provider,
    status: UserStatus = UserStatus.ACTIVE,
) -> User:
    """
    Erstellt einen neuen User aus OAuth-Daten (Einladungs-Flow oder Anklopfen).
    status: UserStatus.ACTIVE für Einladung/Initial-Admin, UserStatus.PENDING für Beitrittsanfrage.
    """
    id_attr = _provider_id_attr(provider)
    provider_id = str(oauth_data.get("id") or "")
    email = oauth_data.get("email") or ""
    login = oauth_data.get("login") or oauth_data.get("name") or "user"
    avatar = oauth_data.get("avatar_url") or oauth_data.get("picture")
    username = _unique_username(session, login, provider_id)
    kwargs: dict = {id_attr: provider_id}
    if provider == "github":
        kwargs["github_login"] = oauth_data.get("login")
    user = User(
        username=username,
        email=email or None,
        role=role,
        avatar_url=avatar,
        status=status,
        **kwargs,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _oauth_return(
    user: User, link_only: bool, anklopfen_only: bool, is_new_user: bool = False, registration_source: Optional[str] = None
) -> Tuple[User, bool, bool, bool, Optional[str]]:
    return (user, link_only, anklopfen_only, is_new_user, registration_source)


async def process_oauth_login(
    *,
    provider: Provider,
    provider_id: str,
    email: Optional[str],
    session: Session,
    oauth_data: dict,
    state: Optional[str] = None,
) -> Tuple[User, bool, bool, bool, Optional[str]]:
    """
    Zentrale OAuth-Auswertung für Login, Link und Anklopfen.

    Returns:
        (user, link_only, anklopfen_only, is_new_user, registration_source):
        - link_only=True: Link-Flow, Redirect zu /settings?linked=...
        - anklopfen_only=True: Kein Token/Session, Redirect zu /request-sent oder /request-rejected
        - is_new_user=True: User wurde in diesem Flow neu angelegt
        - registration_source: "invitation" | "initial_admin" | "anklopfen" | None
    """
    id_attr = _provider_id_attr(provider)
    avatar = oauth_data.get("avatar_url") or oauth_data.get("picture")

    # 3) Link-Flow: state mit purpose link_google / link_github / link_microsoft / link_custom
    link_purposes = ("link_google", "link_github", "link_microsoft", "link_custom")
    if state:
        stored = get_oauth_state(state)
        if stored and stored.get("purpose") in link_purposes:
            purpose = stored.get("purpose")
            if (purpose == "link_google" and provider == "google") or (
                purpose == "link_github" and provider == "github"
            ) or (purpose == "link_microsoft" and provider == "microsoft") or (
                purpose == "link_custom" and provider == "custom"
            ):
                try:
                    uid = UUID(stored["user_id"])
                except (TypeError, ValueError):
                    logger.warning("OAuth: Link-Flow fehlgeschlagen provider=%s (ungültiger user_id im State)", provider)
                    raise HTTPException(status_code=403, detail="Ungültiger Link-State.")
                user = retry_on_sqlite_io(
                    lambda: session.exec(select(User).where(User.id == uid)).first(),
                    session=session,
                )
                if not user or user.blocked:
                    logger.warning("OAuth: Link-Flow fehlgeschlagen provider=%s (user_id=%s nicht gefunden oder blockiert)", provider, stored["user_id"])
                    raise HTTPException(status_code=403, detail="Benutzer nicht gefunden oder blockiert.")
                setattr(user, id_attr, provider_id)
                if avatar:
                    user.avatar_url = avatar
                if provider == "github":
                    user.github_login = oauth_data.get("login")
                session.add(user)
                session.commit()
                session.refresh(user)
                delete_oauth_state(state)
                logger.info(
                    "OAuth: match=link provider=%s user=%s (%s-Konto verknüpft)",
                    provider,
                    user.username,
                    provider,
                )
                return _oauth_return(user, True, False)

    # 1) Direkt-Login: User mit dieser Provider-ID
    stmt = select(User).where(getattr(User, id_attr) == provider_id)
    user = retry_on_sqlite_io(lambda: session.exec(stmt).first(), session=session)
    if user:
        st = getattr(user, "status", UserStatus.ACTIVE)
        if st == UserStatus.PENDING or user.blocked:
            logger.info("OAuth: match=direct anklopfen_only provider=%s user=%s (pending oder blocked)", provider, user.username)
            return _oauth_return(user, False, True)
        logger.info("OAuth: match=direct provider=%s user=%s (bereits verknüpft)", provider, user.username)
        return _oauth_return(user, False, False)

    # 2) Auto-Match: User mit gleicher E-Mail
    if email:
        stmt = select(User).where(User.email == email)
        user = retry_on_sqlite_io(lambda: session.exec(stmt).first(), session=session)
        if user and not user.blocked:
            setattr(user, id_attr, provider_id)
            if avatar:
                user.avatar_url = avatar
            if provider == "github":
                user.github_login = oauth_data.get("login")
            session.add(user)
            session.commit()
            session.refresh(user)
            logger.info(
                "OAuth: match=email provider=%s user=%s (E-Mail-Match, %s-Konto verknüpft)",
                provider,
                user.username,
                provider,
            )
            return _oauth_return(user, False, False)

    # 4) INITIAL_ADMIN_EMAIL
    user, created = get_or_create_initial_admin(session, oauth_data, provider)
    if user:
        logger.info("OAuth: match=initial_admin provider=%s user=%s", provider, user.username)
        return _oauth_return(user, False, False, is_new_user=created, registration_source="initial_admin" if created else None)

    # 5) Einladung: Invitation.token aus state oder aus gespeichertem invitation_token (Custom OAuth)
    invitation_token = None
    if state:
        stored = get_oauth_state(state)
        invitation_token = (stored.get("invitation_token") if stored else None) or state
    if invitation_token:
        stmt = (
            select(Invitation)
            .where(
                Invitation.token == invitation_token,
                Invitation.is_used == False,
                Invitation.expires_at > datetime.now(timezone.utc),
            )
        )
        inv = retry_on_sqlite_io(lambda: session.exec(stmt).first(), session=session)
        if inv and email and inv.recipient_email.lower() == email.lower():
            inv.is_used = True
            session.add(inv)
            session.commit()
            if state:
                delete_oauth_state(state)
            user = create_oauth_user(session, oauth_data, inv.role, provider, status=UserStatus.ACTIVE)
            logger.info("OAuth: match=invitation provider=%s user=%s role=%s recipient=%s", provider, user.username, inv.role.value, inv.recipient_email)
            return _oauth_return(user, False, False, is_new_user=True, registration_source="invitation")

    # 7) Anklopfen: unbekannter Nutzer → Beitrittsanfrage (pending), kein Token/Session
    user = create_oauth_user(session, oauth_data, UserRole.READONLY, provider, status=UserStatus.PENDING)
    try:
        await notify_admin_join_request(user)
    except Exception as e:
        logger.warning("notify_admin_join_request fehlgeschlagen für user=%s: %s", user.username, e)
    logger.info("OAuth: anklopfen provider=%s user=%s (Beitrittsanfrage angelegt)", provider, user.username)
    return _oauth_return(user, False, True, is_new_user=True, registration_source="anklopfen")
