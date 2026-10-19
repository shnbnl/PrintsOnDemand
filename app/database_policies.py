"""PostgreSQL transaction-local identity; SQLite retains route/service checks."""

from contextlib import contextmanager

from flask import g, has_request_context
from flask_login import current_user
from sqlalchemy import event, text

from app.extensions import db
from app.models import User, UserRole


PROTECTED_TABLES = ("orders", "order_items", "payments", "uploaded_files", "print_configurations")


def init_database_policies(app):
    with app.app_context():
        for engine in db.engines.values():
            if engine.dialect.name != "postgresql":
                continue

            @event.listens_for(engine, "begin")
            def apply_identity(connection):
                actor = g.get("database_actor_id") if has_request_context() else None
                erasure = g.get("database_erasure_id") if has_request_context() else None
                # A DBAPI cursor avoids recursively triggering SQLAlchemy begin.
                cursor = connection.connection.cursor()
                try:
                    cursor.execute(
                        "SELECT set_config('pod.user_id', %s, true), "
                        "set_config('pod.erase_user_id', %s, true)",
                        (str(actor or ""), str(erasure or "")),
                    )
                finally:
                    cursor.close()


@contextmanager
def account_erasure_scope(user_id):
    """Explicit exception for an authorized whole-account deletion only.

    Blue staff may erase a verified professor's account across their order
    history; normal shop queries still see only that staff member's shop.
    """
    if db.engine.dialect.name != "postgresql" or not has_request_context():
        yield
        return
    target = db.session.get(User, user_id)
    actor = current_user
    permitted = bool(target and actor.is_authenticated and (
        actor.id == target.id or actor.role == UserRole.ADMIN or (
            actor.role == UserRole.SHOP_STAFF and actor.shop
            and actor.shop.name == "Blue and Silver Bookstore"
            and target.role == UserRole.PROFESSOR
        )
    ))
    if not permitted:
        raise PermissionError("Account erasure is not authorized.")
    previous = g.get("database_erasure_id")
    g.database_erasure_id = int(user_id)
    try:
        db.session.connection().execute(text(
            "SELECT set_config('pod.erase_user_id', :value, true)"
        ), {"value": str(user_id)})
        yield
    finally:
        g.database_erasure_id = previous
        if db.session().in_transaction() and db.session().is_active:
            db.session.connection().execute(text(
                "SELECT set_config('pod.erase_user_id', :value, true)"
            ), {"value": str(previous or "")})
