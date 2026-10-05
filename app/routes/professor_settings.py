"""Redirect the retired professor settings URL to the existing account page."""

from flask import Blueprint, redirect, url_for

from app.authorization import roles_required
from app.models import UserRole


professor_settings_bp = Blueprint("professor_settings", __name__, url_prefix="/professor")


@professor_settings_bp.get("/settings")
@roles_required(UserRole.PROFESSOR)
def settings():
    return redirect(url_for("account.settings"))
