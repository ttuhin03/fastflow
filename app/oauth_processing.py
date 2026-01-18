"""
Zentrale OAuth-Logik für GitHub und Google.

- process_oauth_login: einheitliche Auswertung (Direkt-Login, Auto-Match, Link, INITIAL_ADMIN, Einladung)
- get_or_create_initial_admin: erster Admin über INITIAL_ADMIN_EMAIL (beide Provider)
- create_oauth_user: neuer User aus OAuth-Daten (Einladungs-Flow)
"""

import logging
from datetime import datetime
from typing import Literal, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlmodel import Session, select

from app.config import config
from app.github_oauth import delete_oauth_state, get_oauth_state
from app.models import Invitation, User, UserRole

logger = logging.getLogger(__name__)
Provider = Literal["github", "google"]


def _unique_username(session: Session, login: str, provider_id: str) -> str:
    base = (login or "user").replace(" ", "_")[:50]
    for cand in (base, f"{base}_{provider_id[:12]}" if len(provider_id) > 8 else f"{base}_{provider_id}"):
        stmt = select(User).where(User.username == cand)
        if session.exec(stmt).first() is None:
            return cand
    return f"{base}_{provider_id}"


def get_or_create_initial_admin(
    session: Session,
    oauth_data: dict,
    provider: Provider,
) -> Optional[User]:
    """
    Holt oder erstellt den ersten Admin (INITIAL_ADMIN_EMAIL) für GitHub oder Google.
    """
    id_attr = "github_id" if provider == "github" else "google_id"
    provider_id = str(oauth_data.get("id") or "")
    email = oauth_data.get("email")
    login = oauth_data.get("login") or oauth_data.get("name") or "user"
    avatar = oauth_data.get("avatar_url") or oauth_data.get("picture")

    # 1. Bereits mit dieser Provider-ID vorhanden
    stmt = select(User).where(getattr(User, id_attr) == provider_id)
    user = session.exec(stmt).first()
    if user:
        logger.info("OAuth initial_admin: user=%s bereits mit %s verknüpft", user.username, provider)
        return user

    # 2. INITIAL_ADMIN_EMAIL: bestehenden User verknüpfen oder neuen Admin anlegen
    if email and config.INITIAL_ADMIN_EMAIL and email == config.INITIAL_ADMIN_EMAIL:
        stmt = select(User).where(User.email == email)
        user = session.exec(stmt).first()
        if user:
            setattr(user, id_attr, provider_id)
            if avatar:
                user.avatar_url = avatar
            user.role = UserRole.ADMIN
            session.add(user)
            session.commit()
            session.refresh(user)
            logger.info("OAuth initial_admin: bestehender User user=%s mit %s verknüpft, role=ADMIN", user.username, provider)
            return user
        username = _unique_username(session, login, provider_id)
        user = User(
            username=username,
            email=email,
            role=UserRole.ADMIN,
            avatar_url=avatar,
            **{id_attr: provider_id},
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        logger.info("OAuth initial_admin: neuer Admin user=%s angelegt (provider=%s)", user.username, provider)
        return user

    return None


def create_oauth_user(
    session: Session,
    oauth_data: dict,
    role: UserRole,
    provider: Provider,
) -> User:
    """
    Erstellt einen neuen User aus OAuth-Daten (Einladungs-Flow).
    """
    id_attr = "github_id" if provider == "github" else "google_id"
    provider_id = str(oauth_data.get("id") or "")
    email = oauth_data.get("email") or ""
    login = oauth_data.get("login") or oauth_data.get("name") or "user"
    avatar = oauth_data.get("avatar_url") or oauth_data.get("picture")
    username = _unique_username(session, login, provider_id)
    user = User(
        username=username,
        email=email or None,
        role=role,
        avatar_url=avatar,
        **{id_attr: provider_id},
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def process_oauth_login(
    *,
    provider: Provider,
    provider_id: str,
    email: Optional[str],
    session: Session,
    oauth_data: dict,
    state: Optional[str] = None,
) -> Tuple[User, bool]:
    """
    Zentrale OAuth-Auswertung für Login und Link.

    Returns:
        (user, link_only): link_only=True wenn Link-Flow (Redirect zu /settings?linked=... ohne neues Token).

    Raises:
        HTTPException 403: Kein Zutritt (unbekannte E-Mail, keine Einladung, etc.)
    """
    id_attr = "github_id" if provider == "github" else "google_id"
    avatar = oauth_data.get("avatar_url") or oauth_data.get("picture")

    # 3) Link-Flow: state mit purpose link_google / link_github
    if state:
        stored = get_oauth_state(state)
        if stored and stored.get("purpose") in ("link_google", "link_github"):
            purpose = stored.get("purpose")
            if (purpose == "link_google" and provider == "google") or (
                purpose == "link_github" and provider == "github"
            ):
                try:
                    uid = UUID(stored["user_id"])
                except (TypeError, ValueError):
                    logger.warning("OAuth: Link-Flow fehlgeschlagen provider=%s (ungültiger user_id im State)", provider)
                    raise HTTPException(status_code=403, detail="Ungültiger Link-State.")
                user = session.exec(select(User).where(User.id == uid)).first()
                if not user or user.blocked:
                    logger.warning("OAuth: Link-Flow fehlgeschlagen provider=%s (user_id=%s nicht gefunden oder blockiert)", provider, stored["user_id"])
                    raise HTTPException(status_code=403, detail="Benutzer nicht gefunden oder blockiert.")
                setattr(user, id_attr, provider_id)
                if avatar:
                    user.avatar_url = avatar
                session.add(user)
                session.commit()
                session.refresh(user)
                delete_oauth_state(state)
                logger.info("OAuth: match=link provider=%s user=%s (%s-Konto verknüpft)", provider, user.username, provider)
                return (user, True)

    # 1) Direkt-Login: User mit dieser Provider-ID
    stmt = select(User).where(getattr(User, id_attr) == provider_id)
    user = session.exec(stmt).first()
    if user and not user.blocked:
        logger.info("OAuth: match=direct provider=%s user=%s (bereits verknüpft)", provider, user.username)
        return (user, False)

    # 2) Auto-Match: User mit gleicher E-Mail
    if email:
        stmt = select(User).where(User.email == email)
        user = session.exec(stmt).first()
        if user and not user.blocked:
            setattr(user, id_attr, provider_id)
            if avatar:
                user.avatar_url = avatar
            session.add(user)
            session.commit()
            session.refresh(user)
            logger.info("OAuth: match=email provider=%s user=%s (E-Mail-Match, %s-Konto verknüpft)", provider, user.username, provider)
            return (user, False)

    # 4) INITIAL_ADMIN_EMAIL
    user = get_or_create_initial_admin(session, oauth_data, provider)
    if user:
        logger.info("OAuth: match=initial_admin provider=%s user=%s", provider, user.username)
        return (user, False)

    # 5) Einladung: state = Invitation.token, E-Mail muss recipient_email entsprechen
    if state:
        stmt = (
            select(Invitation)
            .where(
                Invitation.token == state,
                Invitation.is_used == False,
                Invitation.expires_at > datetime.utcnow(),
            )
        )
        inv = session.exec(stmt).first()
        if inv and email and inv.recipient_email.lower() == email.lower():
            inv.is_used = True
            session.add(inv)
            session.commit()
            user = create_oauth_user(session, oauth_data, inv.role, provider)
            logger.info("OAuth: match=invitation provider=%s user=%s role=%s recipient=%s", provider, user.username, inv.role.value, inv.recipient_email)
            return (user, False)

    # 6) Kein Zutritt
    logger.warning("OAuth: Zutritt verweigert provider=%s (kein direkter Match, kein E-Mail-Match, kein INITIAL_ADMIN, keine gültige Einladung)", provider)
    raise HTTPException(status_code=403, detail="Zutritt verweigert. Keine gültige Einladung gefunden.")
