"""Transport, privacy headers, and database-shared request throttling."""

import hashlib
import hmac
import re

from flask import abort, current_app, g, redirect, render_template, request, session
from sqlalchemy import case, delete, select
from werkzeug.middleware.proxy_fix import ProxyFix

from app.extensions import db
from app.models import AuthSession, RateLimitBucket
from app.services.sessions import digest, now_seconds


def consume_limit(scope, identity, limit, window):
    """Atomic counters shared by every worker; no raw IPs/emails persisted."""
    now = now_seconds()
    key = hmac.new(str(current_app.secret_key).encode(),
                   f"{scope}:{identity}".encode(), hashlib.sha256).hexdigest()
    dialect = db.engine.dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise RuntimeError("Request throttling requires SQLite or PostgreSQL.")
    statement = insert(RateLimitBucket).values(key=key, count=1, expires_at=now + window)
    statement = statement.on_conflict_do_update(
        index_elements=[RateLimitBucket.key],
        set_={"count": case((RateLimitBucket.expires_at <= now, 1), else_=RateLimitBucket.count + 1),
              "expires_at": case((RateLimitBucket.expires_at <= now, now + window),
                                 else_=RateLimitBucket.expires_at)},
    ).returning(RateLimitBucket.count, RateLimitBucket.expires_at)
    with db.engine.begin() as connection:
        count, expires = connection.execute(statement).one()
    if count > limit:
        abort(429, description=str(max(1, expires - now)))


def init_security(app):
    hops = app.config["PROXY_FIX_HOPS"]
    if hops:
        # Enable only behind the documented number of proxies, never trust Host.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=0, x_port=0, x_prefix=0)

    @app.before_request
    def enforce_security():
        if app.config["FORCE_HTTPS"] and not request.is_secure:
            # Do not forward submitted credentials or uploads over an HTTP redirect.
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                abort(400, description="HTTPS is required.")
            return redirect(request.url.replace("http://", "https://", 1), code=308)
        if request.method != "POST":
            return None
        remote = request.remote_addr or "unknown"
        if request.endpoint in {"auth.login", "auth.shop_login"}:
            consume_limit("login-ip", remote, app.config["AUTH_RATE_LIMIT"], 900)
            identifier = (request.form.get("email") or request.form.get("identifier")
                          or request.form.get("name") or "").strip().casefold()[:254]
            consume_limit("login-identifier", identifier, app.config["AUTH_IDENTIFIER_RATE_LIMIT"], 900)
        elif request.endpoint == "auth.register":
            consume_limit("register-ip", remote, app.config["REGISTRATION_RATE_LIMIT"], 3600)
        elif request.endpoint in {"account.delete_account"}:
            consume_limit("sensitive-ip", remote, 20, 900)
        elif request.endpoint in {"files.upload", "checkout.upload_files"}:
            # Resolve the rate identity without opening a long-lived ORM
            # transaction before the counter's independent commit.
            credential = session.get("_user_id", "")
            identity = f"ip:{remote}"
            if isinstance(credential, str) and re.fullmatch(r"[A-Za-z0-9_-]{43}", credential):
                now = now_seconds()
                with db.engine.connect() as connection:
                    owner = connection.execute(select(AuthSession.user_id).where(
                        AuthSession.token_hash == digest(credential), AuthSession.expires_at > now,
                        AuthSession.last_seen_at > now - AuthSession.idle_seconds,
                    )).scalar_one_or_none()
                if owner is not None:
                    identity = f"user:{owner}"
            consume_limit("upload", identity, app.config["UPLOAD_RATE_LIMIT"], 900)
        return None

    @app.after_request
    def protect_response(response):
        if g.get("clear_site_data"):
            response.headers["Clear-Site-Data"] = (
                '"cache", "cookies", "storage"' if g.get("clear_browser_cookies")
                else '"cache", "storage"'
            )
        response.headers["Content-Security-Policy"] = "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(self)"
        if request.is_secure and app.config["FORCE_HTTPS"]:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["Pragma"] = "no-cache"
        return response

    @app.errorhandler(429)
    def rate_limited(error):
        response = app.make_response((render_template(
            "main/error.html", message="Too many attempts. Please wait before trying again."
        ), 429))
        response.headers["Retry-After"] = error.description
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.cli.command("cleanup-security-state")
    def cleanup_security_state():
        """Remove expired login sessions and expired rate-limit counters."""
        import click
        now = now_seconds()
        sessions = db.session.execute(delete(AuthSession).where(
            (AuthSession.expires_at <= now) | (AuthSession.last_seen_at <= now - AuthSession.idle_seconds)
        )).rowcount
        counters = db.session.execute(delete(RateLimitBucket).where(RateLimitBucket.expires_at <= now)).rowcount
        db.session.commit()
        click.echo(f"Removed {sessions} expired sessions and {counters} expired counters.")
