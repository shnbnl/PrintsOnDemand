"""Managed professors eligible for a future direct handoff."""

from __future__ import annotations

from datetime import datetime

from email_validator import EmailNotValidError, validate_email
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.extensions import db
from app.models.user import utc_now


class Professor(db.Model):
    __tablename__ = "professors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(db.String(120), nullable=False)
    email: Mapped[str] = mapped_column(db.String(254), unique=True, nullable=False, index=True)
    department: Mapped[str | None] = mapped_column(db.String(120), nullable=True)
    office: Mapped[str | None] = mapped_column(db.String(120), nullable=True)
    is_active: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True)
    direct_send_approved: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    orders: Mapped[list[Order]] = relationship(back_populates="professor")

    @validates("name")
    def validate_name(self, key: str, value: str) -> str:
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 120:
            raise ValueError("Professor name is required and must be at most 120 characters.")
        return value.strip()

    @validates("email")
    def validate_email_address(self, key: str, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("A valid professor email is required.")
        try:
            email = validate_email(value.strip(), check_deliverability=False).normalized.casefold()
        except (EmailNotValidError, TypeError, ValueError) as error:
            raise ValueError("A valid professor email is required.") from error
        if len(email) > 254:
            raise ValueError("Professor email is too long.")
        return email
