"""Role-protected placeholder pages for access checks."""

from flask import Blueprint, render_template

from app.authorization import roles_required
from app.models import UserRole


access_bp = Blueprint("access", __name__)


@access_bp.get("/student")
@roles_required(UserRole.STUDENT)
def student():
    return render_template("main/protected.html", title="Student access")


@access_bp.get("/shop")
@roles_required(UserRole.SHOP_STAFF)
def shop():
    return render_template("main/protected.html", title="Shop Staff access")


@access_bp.get("/admin")
@roles_required(UserRole.ADMIN)
def admin():
    return render_template("main/protected.html", title="Admin access")
