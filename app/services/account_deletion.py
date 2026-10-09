"""Explicit customer-owned deletion graph and staged private-file cleanup."""

from __future__ import annotations

from sqlalchemy import delete, select, update

from app.extensions import db
from app.models import Order, OrderItem, Payment, PrintConfiguration, Professor, UploadedFile, User, UserRole
from app.storage import StorageError, get_account_deletion_storage


class AccountDeletionError(Exception):
    """The account was not removed; the transaction was rolled back."""


class AccountDeletionCleanupError(Exception):
    """The account was removed, but staged private bytes need operator cleanup."""


def delete_customer_account(user_id: int) -> None:
    """Remove a customer's complete owned graph, preserving shared shop data.

    Order snapshots and payments belong to the order owner and are removed.
    Other customers' order snapshots remain even when a professor's managed
    profile is removed. Private files are staged before
    commit and purged only after commit, so database failure restores the bytes.
    """
    staged = None
    try:
        user = db.session.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None or user.role not in (UserRole.STUDENT, UserRole.PROFESSOR):
            raise AccountDeletionError("Account deletion is unavailable.")

        # Fence new work by this account while taking its owned-record snapshot.
        user.is_active = False
        db.session.flush()
        orders = db.session.scalars(select(Order.id).where(Order.user_id == user_id)).all()
        uploads = db.session.execute(
            select(UploadedFile.id, UploadedFile.storage_key).where(UploadedFile.user_id == user_id)
        ).all()
        file_ids = [record.id for record in uploads]
        if uploads:
            storage = get_account_deletion_storage()
            staged = storage.stage_deletion([record.storage_key for record in uploads])

        # These RESTRICT references require explicit child-first deletion.
        if orders:
            db.session.execute(delete(Payment).where(Payment.order_id.in_(orders)))
            db.session.execute(delete(OrderItem).where(OrderItem.order_id.in_(orders)))
            db.session.execute(delete(Order).where(Order.id.in_(orders)))
        if file_ids:
            db.session.execute(delete(PrintConfiguration).where(PrintConfiguration.file_id.in_(file_ids)))
        db.session.execute(delete(UploadedFile).where(UploadedFile.user_id == user_id))

        # Normally only staff/admin review payments; this also handles an old
        # reviewer reference without deleting somebody else's payment.
        db.session.execute(update(Payment).where(Payment.reviewed_by_id == user_id).values(reviewed_by_id=None))
        professor_id = user.professor_id if user.role == UserRole.PROFESSOR else None
        if professor_id is not None:
            db.session.execute(update(Order).where(Order.professor_id == professor_id).values(professor_id=None))
        deleted = db.session.execute(delete(User).where(User.id == user_id))
        if deleted.rowcount != 1:
            raise AccountDeletionError("Account deletion did not complete.")
        if professor_id is not None:
            db.session.execute(delete(Professor).where(Professor.id == professor_id))
        db.session.commit()
    except Exception as error:
        db.session.rollback()
        if staged is not None:
            try:
                staged.restore()
            except (OSError, StorageError) as restore_error:
                raise AccountDeletionError("Account deletion failed and private-file recovery needs attention.") from restore_error
        raise AccountDeletionError("Account deletion failed.") from error

    if staged is not None:
        try:
            staged.purge()
        except (OSError, StorageError) as error:
            raise AccountDeletionCleanupError("Private-file cleanup needs attention.") from error
