"""Durable, one-use password reset grants and request throttling."""

from datetime import datetime, timezone

from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


def utc_now():
    return datetime.now(timezone.utc)


class PasswordResetGrant(db.Model):
    __tablename__ = "password_reset_grants"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_digest: Mapped[str] = mapped_column(db.String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)


class PasswordResetAttempt(db.Model):
    __tablename__ = "password_reset_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    throttle_key: Mapped[str] = mapped_column(db.String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, default=utc_now)
