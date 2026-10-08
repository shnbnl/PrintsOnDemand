"""Durable, privacy-preserving counters for sensitive POST requests."""

from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


class RateLimitBucket(db.Model):
    __tablename__ = "rate_limit_buckets"

    key: Mapped[str] = mapped_column(db.String(64), primary_key=True)
    window_start: Mapped[int] = mapped_column(db.BigInteger, nullable=False, index=True)
    hits: Mapped[int] = mapped_column(db.Integer, nullable=False)
