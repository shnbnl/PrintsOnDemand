"""Student and professor registration and account sessions."""

from urllib.parse import urlsplit

from flask import Blueprint, flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.forms import BlueStaffLoginForm, LoginForm, RegistrationForm, ShopStaffLoginForm
from app.models import PrintingShop, User, UserRole
from app.services.professors import PROFESSOR_DELIVERY_SHOP


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def role_home(role: UserRole) -> str:
    return {
        UserRole.STUDENT: url_for("access.student"),
        UserRole.PROFESSOR: url_for("access.professor"),
        UserRole.SHOP_STAFF: url_for("access.shop"),
        UserRole.ADMIN: url_for("access.admin"),
    }[role]


def safe_next_url(value: str | None) -> str | None:
    if (
        value
        and value.startswith("/")
        and not value.startswith("//")
        and "\\" not in value
        and all(32 <= ord(char) < 127 for char in value)
    ):
        parsed = urlsplit(value)
        if not parsed.netloc and not parsed.scheme:
            return value
    return None


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(role_home(current_user.role))

    form = RegistrationForm()
    if request.method == "GET" and request.args.get("account_type") in {
        UserRole.STUDENT.value, UserRole.PROFESSOR.value,
    }:
        form.account_type.data = request.args["account_type"]
    if form.validate_on_submit():
        email = User.normalize_email(form.email.data)
        existing = db.session.scalar(select(User).where(User.email == email))
        if existing:
            form.email.errors.append("Unable to create account with these details.")
        else:
            user = User(
                name=form.name.data.strip(), email=email, role=UserRole(form.account_type.data),
                professor_department=(form.professor_department.data if form.account_type.data == "PROFESSOR" else None),
            )
            user.set_password(form.password.data)
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.email.errors.append("Unable to create account with these details.")
            else:
                if user.role == UserRole.PROFESSOR:
                    flash("Account created. Please log in. An active linked profile enables Deliver to Me; Blue and Silver approval is also needed before students can select you.", "success")
                else:
                    flash("Account created. Please log in.", "success")
                return redirect(url_for("auth.login"))

    return render_template("auth/register.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(role_home(current_user.role))

    blue_login = request.args.get("blue") == "1"
    form = BlueStaffLoginForm() if blue_login else LoginForm()
    if form.validate_on_submit():
        if blue_login:
            candidates = db.session.scalars(
                select(User).join(PrintingShop, User.shop_id == PrintingShop.id).where(
                    User.role == UserRole.SHOP_STAFF,
                    PrintingShop.name == PROFESSOR_DELIVERY_SHOP,
                    User.is_active.is_(True),
                )
            ).all()
            matches = [user for user in candidates if user.name.casefold() == form.name.data.casefold()]
            user = matches[0] if len(matches) == 1 else None
        else:
            email = User.normalize_email(form.email.data)
            user = db.session.scalar(select(User).where(User.email == email))
        if user and user.is_active and user.check_password(form.password.data):
            login_user(user, remember=bool(form.remember_me.data) if not blue_login else False)
            return redirect(safe_next_url(request.args.get("next")) or role_home(user.role))
        form.password.errors.append("Invalid name or password." if blue_login else "Invalid email or password.")

    return render_template("auth/login.html", form=form, blue_login=blue_login)


@auth_bp.route("/shop-login", methods=["GET", "POST"])
def shop_login():
    """Staff-only credential entry, separate from student/professor sign-in."""
    if current_user.is_authenticated:
        return redirect(role_home(current_user.role))

    form = ShopStaffLoginForm()
    shops = db.session.execute(
        select(PrintingShop.id, PrintingShop.name).order_by(PrintingShop.name)
    ).all()
    form.shop_id.choices = [(0, "Select your shop")] + [(id, name) for id, name in shops]
    if form.validate_on_submit():
        identifier = form.identifier.data.casefold()
        candidates = db.session.scalars(select(User).where(
            User.role == UserRole.SHOP_STAFF,
            User.shop_id == form.shop_id.data,
            User.is_active.is_(True),
        )).all()
        if "@" in identifier:
            matches = [user for user in candidates if user.email == identifier]
        else:
            matches = [user for user in candidates if user.name.casefold() == identifier]
        user = matches[0] if len(matches) == 1 else None
        if user and user.check_password(form.password.data):
            login_user(user, remember=False)
            return redirect(safe_next_url(request.args.get("next")) or role_home(user.role))
        form.password.errors.append("Invalid shop, staff email or name, or password.")
    response = make_response(render_template("auth/shop_login.html", form=form))
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@auth_bp.post("/logout")
def logout():
    if current_user.is_authenticated:
        logout_user()
    flash("You have logged out.", "success")
    return redirect(url_for("main.index"))
