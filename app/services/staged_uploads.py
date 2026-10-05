"""Expire only checkout uploads that were never attached to an order."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models import UploadedFile
from app.models.user import utc_now
from app.storage import get_account_deletion_storage


def cleanup_staged_uploads(*, retention_hours: int, limit: int = 100) -> int:
    if retention_hours < 1 or limit < 1:
        raise ValueError("Checkout cleanup limits must be positive.")
    cutoff = utc_now() - timedelta(hours=retention_hours)
    records = db.session.scalars(
        select(UploadedFile).where(
            UploadedFile.checkout_staged_at.is_not(None),
            UploadedFile.checkout_staged_at <= cutoff,
            ~UploadedFile.order_items.any(),
        ).order_by(UploadedFile.checkout_staged_at, UploadedFile.id).limit(limit).with_for_update()
    ).all()
    if not records:
        return 0
    storage = get_account_deletion_storage()
    staged = storage.stage_deletion([record.storage_key for record in records])
    try:
        for record in records:
            db.session.delete(record)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        staged.restore()
        raise
    staged.purge()
    return len(records)
