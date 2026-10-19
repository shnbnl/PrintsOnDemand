"""Revocable authentication and shared, bounded abuse counters."""

from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


class AuthSession(db.Model):
    __tablename__ = "auth_sessions"

    token_hash: Mapped[str] = mapped_column(db.String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    password_fingerprint: Mapped[str] = mapped_column(db.String(64), nullable=False)
    created_at: Mapped[int] = mapped_column(db.BigInteger, nullable=False)
    last_seen_at: Mapped[int] = mapped_column(db.BigInteger, nullable=False)
    expires_at: Mapped[int] = mapped_column(db.BigInteger, nullable=False, index=True)
    idle_seconds: Mapped[int] = mapped_column(db.Integer, nullable=False)


class RateLimitBucket(db.Model):
    __tablename__ = "rate_limit_buckets"

    key: Mapped[str] = mapped_column(db.String(64), primary_key=True)
    expires_at: Mapped[int] = mapped_column(db.BigInteger, nullable=False, index=True)
    count: Mapped[int] = mapped_column(db.Integer, nullable=False)
