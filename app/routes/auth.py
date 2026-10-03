"""Student registration and account sessions."""

from urllib.parse import urlsplit

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.forms import LoginForm, RegistrationForm
from app.models import User, UserRole


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
    if form.validate_on_submit():
        email = User.normalize_email(form.email.data)
        existing = db.session.scalar(select(User).where(User.email == email))
        if existing:
            form.email.errors.append("Unable to create account with these details.")
        else:
            user = User(name=form.name.data.strip(), email=email, role=UserRole.STUDENT)
            user.set_password(form.password.data)
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.email.errors.append("Unable to create account with these details.")
            else:
                flash("Account created. Please log in.", "success")
                return redirect(url_for("auth.login"))

    return render_template("auth/register.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(role_home(current_user.role))

    form = LoginForm()
    if form.validate_on_submit():
        email = User.normalize_email(form.email.data)
        user = db.session.scalar(select(User).where(User.email == email))
        if user and user.is_active and user.check_password(form.password.data):
            login_user(user, remember=bool(form.remember_me.data))
            return redirect(safe_next_url(request.args.get("next")) or role_home(user.role))
        form.password.errors.append("Invalid email or password.")

    return render_template("auth/login.html", form=form)


@auth_bp.post("/logout")
def logout():
    if current_user.is_authenticated:
        logout_user()
    flash("You have logged out.", "success")
    return redirect(url_for("main.index"))
