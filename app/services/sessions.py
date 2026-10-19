"""Opaque login credentials, with server-side revocation and expiry."""

import hashlib
import re
import secrets
import time

from flask import current_app, g, session
from flask_login import login_user
from sqlalchemy import delete, select, update

from app.extensions import db
from app.models import AuthSession, User, UserRole


def now_seconds():
    return int(time.time())


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def issue_session(user, *, remember=False):
    """Only the digest is stored in the DB; tokens contain no user data."""
    now = now_seconds()
    remembered = remember and user.role in (UserRole.STUDENT, UserRole.PROFESSOR)
    absolute = int((current_app.config["REMEMBER_COOKIE_DURATION"] if remembered
                    else current_app.config["AUTH_ABSOLUTE_TIMEOUT"]).total_seconds())
    idle = int((current_app.config["REMEMBER_IDLE_TIMEOUT"] if remembered
                else current_app.config["AUTH_IDLE_TIMEOUT"]).total_seconds())
    token = secrets.token_urlsafe(32)
    db.session.add(AuthSession(
        token_hash=digest(token), user_id=user.id,
        password_fingerprint=digest(user.password_hash), created_at=now,
        last_seen_at=now, expires_at=now + absolute, idle_seconds=idle,
    ))
    db.session.commit()
    return token


def begin_login(user, *, remember=False):
    # Clear CSRF, anonymous checkout state, and any previous identity on login.
    revoke_session(session.get("_user_id"))
    session.clear()
    g.pop("csrf_token", None)
    g.clear_site_data = False
    g.clear_browser_cookies = False
    remember = remember and user.role in (UserRole.STUDENT, UserRole.PROFESSOR)
    token = issue_session(user, remember=remember)
    g.database_actor_id = user.id
    login_user(user, remember=remember)
    session["_user_id"] = token
    session.permanent = True


def revoke_session(token):
    if isinstance(token, str) and re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        with db.engine.begin() as connection:
            connection.execute(delete(AuthSession).where(AuthSession.token_hash == digest(token)))


def clear_client_auth(*, clear_browser_cookies=False):
    session.clear()
    g.pop("csrf_token", None)
    session["_remember"] = "clear"
    g.clear_site_data = True
    g.clear_browser_cookies = clear_browser_cookies
    g.database_actor_id = None
    g.database_erasure_id = None


def load_session_user(token):
    # Reject legacy signed user IDs as well as malformed credentials.
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        clear_client_auth()
        return None
    now = now_seconds()
    token_hash = digest(token)
    # Finish this short security transaction before acquiring the ORM connection
    # used by the page; each worker needs only one pooled connection at a time.
    with db.engine.begin() as connection:
        record = connection.execute(select(
            AuthSession.__table__, User.is_active, User.password_hash
        ).join(User, User.id == AuthSession.user_id).where(
            AuthSession.token_hash == token_hash
        )).mappings().first()
        if (not record or not record["is_active"] or now >= record["expires_at"]
                or now - record["last_seen_at"] >= record["idle_seconds"]
                or not secrets.compare_digest(record["password_fingerprint"], digest(record["password_hash"]))):
            connection.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash))
            clear_client_auth()
            return None
        # A simultaneous logout cannot recreate a deleted session.
        touched = connection.execute(update(AuthSession).where(
            AuthSession.token_hash == token_hash,
            AuthSession.expires_at > now,
            AuthSession.last_seen_at > now - AuthSession.idle_seconds,
        ).values(last_seen_at=now))
    if touched.rowcount != 1:
        clear_client_auth()
        return None
    g.database_actor_id = record["user_id"]
    user = db.session.get(User, record["user_id"], populate_existing=True)
    return user if user and user.is_active else None
