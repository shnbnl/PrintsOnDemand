"""Reusable role checks for protected endpoints."""

from functools import wraps

from flask import abort
from flask_login import current_user, login_required

from app.models import UserRole


def roles_required(*allowed_roles: UserRole):
    def decorate(view):
        @wraps(view)
        @login_required
        def guarded(*args, **kwargs):
            if current_user.role not in allowed_roles:
                abort(403)
            return view(*args, **kwargs)

        return guarded

    return decorate
