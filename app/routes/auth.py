"""Student and professor registration and account sessions."""

from urllib.parse import urlsplit

from flask import Blueprint, flash, make_response, redirect, render_template, request, session, url_for
from flask_login import current_user, logout_user
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.forms import BlueStaffLoginForm, LoginForm, RegistrationForm, ShopStaffLoginForm
from app.models import PrintingShop, User, UserRole
from app.services.professors import PROFESSOR_DELIVERY_SHOP
from app.professor_faculties import FACULTIES_BY_DEPARTMENT
from app.services.sessions import begin_login, clear_client_auth, revoke_session


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")
_DUMMY_PASSWORD_HASH = generate_password_hash("not-an-account-credential")


def valid_credentials(user, password):
    # Unknown/inactive identities still pay the password-hash cost.
    valid = check_password_hash(user.password_hash if user else _DUMMY_PASSWORD_HASH, password)
    return bool(user and user.is_active and valid)


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
    form.professor_faculty.choices = [("", "Select faculty")] + [
        (faculty, faculty) for faculty in FACULTIES_BY_DEPARTMENT.get(form.professor_department.data, ())
    ]
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
                professor_faculty=(form.professor_faculty.data or None) if form.account_type.data == "PROFESSOR" else None,
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
                    flash("Account created. Please log in. Blue and Silver will review your account before professor delivery becomes available.", "success")
                else:
                    flash("Account created. Please log in.", "success")
                return redirect(url_for("auth.login"))

    return render_template("auth/register.html", form=form, faculties_by_department=FACULTIES_BY_DEPARTMENT)


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
        if valid_credentials(user, form.password.data):
            begin_login(user, remember=bool(form.remember_me.data) if not blue_login else False)
            return redirect(safe_next_url(request.args.get("next")) or role_home(user.role))
        form.password.errors.append("Invalid name or password." if blue_login else "Invalid email or password.")

    return render_template("auth/login.html", form=form, blue_login=blue_login)


@auth_bp.route("/shop-login", methods=["GET", "POST"])
def shop_login():
    """Staff-only credential entry, separate from student/professor sign-in."""
    if current_user.is_authenticated:
        return redirect(role_home(current_user.role))

    form = ShopStaffLoginForm()
    if form.validate_on_submit():
        identifier = form.identifier.data.casefold()
        if "@" in identifier:
            user = db.session.scalar(select(User).where(
                User.role == UserRole.SHOP_STAFF,
                User.email == User.normalize_email(identifier),
            ))
        else:
            candidates = db.session.scalars(select(User).where(
                User.role == UserRole.SHOP_STAFF,
            )).all()
            matches = [user for user in candidates if user.name.casefold() == identifier]
            user = matches[0] if len(matches) == 1 else None
        if (
            valid_credentials(user, form.password.data)
            and user.shop_id is not None and user.shop is not None
        ):
            begin_login(user, remember=False)
            return redirect(safe_next_url(request.args.get("next")) or role_home(user.role))
        form.password.errors.append(
            "Unable to sign in. Check your staff email or name and password, "
            "or contact your administrator about account access."
        )
    response = make_response(render_template("auth/shop_login.html", form=form))
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@auth_bp.post("/logout")
def logout():
    revoke_session(session.get("_user_id"))
    if current_user.is_authenticated:
        logout_user()
    clear_client_auth()
    flash("You have logged out.", "success")
    response = redirect(url_for("main.index"))
    response.headers["Clear-Site-Data"] = '"cache", "cookies", "storage"'
    return response
