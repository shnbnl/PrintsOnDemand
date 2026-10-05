"""Private uploaded-file metadata and each file's active print settings."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.shop import ColorMode, PaperSize
from app.models.user import utc_now


class UploadedFile(db.Model):
    __tablename__ = "uploaded_files"
    __table_args__ = (CheckConstraint("file_size > 0", name="uploaded_file_size_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    original_filename: Mapped[str] = mapped_column(db.String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(db.String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(db.String(255), unique=True, nullable=False)
    mime_type: Mapped[str] = mapped_column(db.String(127), nullable=False)
    file_extension: Mapped[str] = mapped_column(db.String(8), nullable=False)
    file_size: Mapped[int] = mapped_column(db.BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(db.String(64), nullable=False)
    # Set only for uploads made in guided checkout. Legacy library rows remain
    # NULL, so a cleanup job can never mistake them for abandoned drafts.
    checkout_staged_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    user: Mapped[User] = relationship(back_populates="uploaded_files")
    configuration: Mapped[PrintConfiguration | None] = relationship(
        back_populates="uploaded_file", uselist=False, cascade="all, delete-orphan"
    )
    order_items: Mapped[list[OrderItem]] = relationship(back_populates="uploaded_file")


class PrintConfiguration(db.Model):
    __tablename__ = "print_configurations"
    __table_args__ = (
        UniqueConstraint("file_id", name="uq_print_configuration_file"),
        CheckConstraint("quantity >= 1", name="print_configuration_quantity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(
        db.ForeignKey("uploaded_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    paper_size: Mapped[PaperSize] = mapped_column(
        db.Enum(PaperSize, name="paper_size", native_enum=False, create_constraint=True), nullable=False
    )
    color_mode: Mapped[ColorMode] = mapped_column(
        db.Enum(ColorMode, name="color_mode", native_enum=False, create_constraint=True), nullable=False
    )
    quantity: Mapped[int] = mapped_column(db.Integer, nullable=False)
    is_rush: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    uploaded_file: Mapped[UploadedFile] = relationship(back_populates="configuration")
