"""User identity and application roles."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from flask_login import UserMixin
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


class UserRole(StrEnum):
    STUDENT = "STUDENT"
    PROFESSOR = "PROFESSOR"
    SHOP_STAFF = "SHOP_STAFF"
    ADMIN = "ADMIN"


class ProfessorVerificationStatus(StrEnum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


BLUE_STAFF_EMAIL_DOMAIN = "blue-staff.invalid"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("professor_id", name="uq_users_professor_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(db.String(120), nullable=False)
    email: Mapped[str] = mapped_column(db.String(254), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(db.String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        db.Enum(UserRole, name="user_role", native_enum=False, create_constraint=True),
        nullable=False,
        default=UserRole.STUDENT,
    )
    is_active: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    shop_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("printing_shops.id", name="fk_users_shop_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    shop: Mapped[PrintingShop | None] = relationship(back_populates="staff")
    professor_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("professors.id", name="fk_users_professor_id", ondelete="RESTRICT"),
        nullable=True,
    )
    professor: Mapped[Professor | None] = relationship(back_populates="account")
    professor_verification_status: Mapped[ProfessorVerificationStatus] = mapped_column(
        db.Enum(ProfessorVerificationStatus, name="professor_verification_status", native_enum=False),
        nullable=False, default=ProfessorVerificationStatus.PENDING,
        server_default=ProfessorVerificationStatus.PENDING.value,
    )
    professor_department: Mapped[str | None] = mapped_column(db.String(120), nullable=True)
    professor_faculty: Mapped[str | None] = mapped_column(db.String(120), nullable=True)
    student_delivery_preference: Mapped[bool] = mapped_column(
        db.Boolean, nullable=False, default=False, server_default=db.false()
    )
    uploaded_files: Mapped[list[UploadedFile]] = relationship(back_populates="user")
    orders: Mapped[list[Order]] = relationship(back_populates="user")

    @staticmethod
    def normalize_email(value: str) -> str:
        return value.strip().casefold()

    @property
    def uses_name_login(self) -> bool:
        return self.role == UserRole.SHOP_STAFF and self.email.endswith(f"@{BLUE_STAFF_EMAIL_DOMAIN}")

    @property
    def login_identifier(self) -> str:
        return self.name if self.uses_name_login else self.email

    @validates("email")
    def validate_email(self, key: str, value: str) -> str:
        return self.normalize_email(value)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)
