"""Role-protected placeholder pages for access checks."""

from flask import Blueprint, render_template, url_for
from flask_login import current_user

from app.authorization import roles_required
from app.models import UserRole
from app.routes.shops import detail_context


access_bp = Blueprint("access", __name__)


@access_bp.get("/student")
@roles_required(UserRole.STUDENT)
def student():
    return render_template(
        "main/protected.html", title="Student access", next_url=url_for("shops.index"),
        next_label="Browse printing shops",
        files_url=url_for("files.index"),
    )


@access_bp.get("/shop")
@roles_required(UserRole.SHOP_STAFF)
def shop():
    if current_user.shop is not None:
        return render_template("shops/detail.html", staff_view=True, **detail_context(current_user.shop))
    return render_template("main/protected.html", title="Shop Staff access")


@access_bp.get("/admin")
@roles_required(UserRole.ADMIN)
def admin():
    return render_template("admin/index.html")
