"""Password recovery with durable throttles and one-use random grants."""

import hashlib
import hmac
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from flask import current_app, request, url_for
from sqlalchemy import delete, func, select, update

from app.extensions import db
from app.models import PasswordResetAttempt, PasswordResetGrant, User, UserRole


def now_utc():
    # The existing SQLite model stores UTC as naive datetime values on retrieval.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def throttle_key(kind, value):
    return hmac.new(current_app.secret_key.encode("utf-8"),
                    f"reset:{kind}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()


def permit_request(email):
    """Count both address and direct peer IP attempts, including unknown addresses."""
    now = now_utc()
    db.session.execute(delete(PasswordResetAttempt).where(
        PasswordResetAttempt.created_at < now - timedelta(days=1)))
    checks = ((throttle_key("email", email), 3),
              (throttle_key("ip", request.remote_addr or "unknown"), 15))
    allowed = True
    for key, limit in checks:
        recent = db.session.scalar(select(func.count(PasswordResetAttempt.id)).where(
            PasswordResetAttempt.throttle_key == key,
            PasswordResetAttempt.created_at >= now - timedelta(hours=1)))
        if recent >= limit:
            allowed = False
        db.session.add(PasswordResetAttempt(throttle_key=key, created_at=now))
    db.session.commit()
    return allowed


def mail_is_configured():
    base = current_app.config["PASSWORD_RESET_BASE_URL"]
    secure_base = base.startswith("https://") if current_app.config["ENV_NAME"] == "production" else base.startswith(("http://", "https://"))
    return bool(current_app.config["MAIL_HOST"] and current_app.config["MAIL_FROM"] and secure_base)


def send_reset_email(address, link):
    settings = current_app.config
    message = EmailMessage()
    message["Subject"] = "Reset your Prints On Demand password"
    message["From"] = settings["MAIL_FROM"]
    message["To"] = address
    message.set_content(
        "A password reset was requested for your Prints On Demand account.\n\n"
        f"Open this link within {settings['RESET_TOKEN_MINUTES']} minutes:\n{link}\n\n"
        "If you did not request this, you can ignore this email."
    )
    connection = smtplib.SMTP_SSL if settings["MAIL_USE_SSL"] else smtplib.SMTP
    with connection(settings["MAIL_HOST"], settings["MAIL_PORT"], timeout=10) as smtp:
        if not settings["MAIL_USE_SSL"]:
            smtp.starttls()
        if settings["MAIL_USERNAME"]:
            smtp.login(settings["MAIL_USERNAME"], settings["MAIL_PASSWORD"])
        smtp.send_message(message)


def request_reset(email):
    if not permit_request(email) or not mail_is_configured():
        return
    user = db.session.scalar(select(User).where(User.email == email, User.is_active.is_(True),
                                               User.role.in_((UserRole.STUDENT, UserRole.PROFESSOR))))
    if user is None:
        return
    token = secrets.token_urlsafe(32)
    grant = PasswordResetGrant(user_id=user.id, token_digest=digest(token), created_at=now_utc(),
                               expires_at=now_utc() + timedelta(minutes=current_app.config["RESET_TOKEN_MINUTES"]))
    db.session.add(grant)
    db.session.commit()
    try:
        link = current_app.config["PASSWORD_RESET_BASE_URL"] + url_for("auth.reset_password", token=token)
        send_reset_email(user.email, link)
    except (OSError, smtplib.SMTPException):
        db.session.delete(grant)
        db.session.commit()
        current_app.logger.warning("Password reset email delivery failed")


def valid_grant(token):
    grant = db.session.scalar(select(PasswordResetGrant).where(
        PasswordResetGrant.token_digest == digest(token), PasswordResetGrant.used_at.is_(None),
        PasswordResetGrant.expires_at > now_utc()))
    if grant is None:
        return None
    user = db.session.get(User, grant.user_id)
    return grant if user and user.is_active and user.role in (UserRole.STUDENT, UserRole.PROFESSOR) else None


def consume_grant(grant, password):
    now = now_utc()
    claimed = db.session.execute(update(PasswordResetGrant).where(
        PasswordResetGrant.id == grant.id, PasswordResetGrant.used_at.is_(None),
        PasswordResetGrant.expires_at > now).values(used_at=now))
    if claimed.rowcount != 1:
        db.session.rollback()
        return False
    user = db.session.get(User, grant.user_id)
    user.set_password(password)
    db.session.execute(update(PasswordResetGrant).where(
        PasswordResetGrant.user_id == user.id, PasswordResetGrant.used_at.is_(None)).values(used_at=now))
    db.session.commit()
    return True
