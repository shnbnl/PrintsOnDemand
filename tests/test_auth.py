"""Account, session, role, and CSRF behavior."""

import re

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import create_app
from app.config import TestingConfig
from app.extensions import db
from app.models import User, UserRole


PASSWORD = "A-strong-password-123"


def csrf_token(response):
    match = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', response.data)
    assert match, "CSRF token missing from page"
    return match.group(1).decode()


def register(client, **changes):
    data = {
        "name": "Student Name",
        "email": "student@example.com",
        "password": PASSWORD,
        "confirm_password": PASSWORD,
    }
    data.update(changes)
    data["csrf_token"] = csrf_token(client.get("/auth/register"))
    return client.post("/auth/register", data=data)


def login(client, email="student@example.com", password=PASSWORD, next_url=""):
    path = "/auth/login" + (f"?next={next_url}" if next_url else "")
    token = csrf_token(client.get(path))
    return client.post(path, data={"email": email, "password": password, "csrf_token": token})


def add_user(app, role=UserRole.STUDENT, email="student@example.com", active=True):
    with app.app_context():
        user = User(name="Test User", email=email, role=role, is_active=active)
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.commit()
        return user.id


def test_user_model_password_hash_and_email_normalization(test_app):
    with test_app.app_context():
        user = User(name="Student", email="  Student@Example.COM  ", role=UserRole.STUDENT)
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.commit()

        assert user.id is not None
        assert user.email == "student@example.com"
        assert user.password_hash != PASSWORD
        assert user.check_password(PASSWORD)
        assert not user.check_password("wrong-password")
        assert user.is_active
        assert user.created_at is not None
        assert user.updated_at is not None


def test_duplicate_email_rejected_by_database(test_app):
    add_user(test_app)
    with test_app.app_context():
        duplicate = User(name="Another", email="STUDENT@example.com", role=UserRole.STUDENT)
        duplicate.set_password(PASSWORD)
        db.session.add(duplicate)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_public_registration_is_student_only(client, test_app):
    response = register(client, email=" STUDENT@Example.COM ", role="ADMIN")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/login")
    with test_app.app_context():
        user = db.session.scalar(select(User).where(User.email == "student@example.com"))
        assert user.role == UserRole.STUDENT
        assert user.check_password(PASSWORD)
        assert db.session.scalar(select(User).where(User.role == UserRole.ADMIN)) is None
    assert PASSWORD.encode() not in response.data


@pytest.mark.parametrize(
    "changes",
    [
        {"name": ""},
        {"email": "not-an-email"},
        {"password": "short", "confirm_password": "short"},
    ],
)
def test_invalid_registration(client, test_app, changes):
    response = register(client, **changes)

    assert response.status_code == 200
    with test_app.app_context():
        assert db.session.scalar(select(User)) is None


def test_password_confirmation_required(client):
    response = register(client, confirm_password="different-password")

    assert response.status_code == 200
    assert b"Passwords must match" in response.data


def test_duplicate_registration_uses_generic_error(client, test_app):
    add_user(test_app)
    response = register(client, email="STUDENT@EXAMPLE.COM")

    assert response.status_code == 200
    assert b"Unable to create account with these details" in response.data
    with test_app.app_context():
        assert len(db.session.scalars(select(User)).all()) == 1


def test_login_and_logout(client, test_app):
    add_user(test_app)
    response = login(client, email="STUDENT@EXAMPLE.COM")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/student")
    assert client.get("/student").status_code == 200

    token = csrf_token(client.get("/student"))
    response = client.post("/auth/logout", data={"csrf_token": token})
    assert response.status_code == 302
    assert client.get("/student").status_code == 302


@pytest.mark.parametrize("email,password", [("missing@example.com", PASSWORD), ("student@example.com", "wrong-password")])
def test_login_failure_has_same_message(client, test_app, email, password):
    add_user(test_app)
    response = login(client, email=email, password=password)

    assert response.status_code == 200
    assert b"Invalid email or password" in response.data
    assert client.get("/student").status_code == 302


@pytest.mark.parametrize("path", ["/student", "/shop", "/admin"])
def test_anonymous_user_redirects_to_login(client, path):
    response = client.get(path)

    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


@pytest.mark.parametrize(
    "role,email,allowed",
    [
        (UserRole.STUDENT, "student@example.com", "/student"),
        (UserRole.SHOP_STAFF, "staff@example.com", "/shop"),
        (UserRole.ADMIN, "admin@example.com", "/admin"),
    ],
)
def test_role_boundaries(client, test_app, role, email, allowed):
    add_user(test_app, role=role, email=email)
    assert login(client, email=email).status_code == 302

    for path in ("/student", "/shop", "/admin"):
        response = client.get(path)
        assert response.status_code == (200 if path == allowed else 403)


def test_inactive_user_cannot_log_in_or_reuse_session(client, test_app):
    user_id = add_user(test_app, active=False)

    response = login(client)
    assert b"Invalid email or password" in response.data

    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True
    assert client.get("/student").status_code == 302


def test_deactivated_user_loses_existing_session(monkeypatch):
    # Use separate app contexts so each request reloads the user as in production.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    app = create_app(TestingConfig)
    with app.app_context():
        db.create_all()
        user = User(name="Test User", email="student@example.com", role=UserRole.STUDENT)
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    assert login(client).status_code == 302
    assert client.get("/student").status_code == 200

    with app.app_context():
        user = db.session.get(User, user_id)
        user.is_active = False
        db.session.commit()

    assert client.get("/student").status_code == 302


@pytest.mark.parametrize(
    "role,email,blocked_paths",
    [
        (UserRole.STUDENT, "student@example.com", (
            "/staff/orders", "/admin/shops", "/admin/staff", "/admin/professors", "/admin/payment",
        )),
        (UserRole.SHOP_STAFF, "staff@example.com", (
            "/admin/shops", "/admin/staff", "/admin/professors", "/admin/payment",
        )),
        (UserRole.ADMIN, "admin@example.com", ("/staff/orders", "/files")),
    ],
)
def test_management_routes_enforce_roles(client, test_app, role, email, blocked_paths):
    add_user(test_app, role=role, email=email)
    assert login(client, email=email).status_code == 302

    for path in blocked_paths:
        assert client.get(path).status_code == 403


@pytest.mark.parametrize("path", ["/auth/register", "/auth/login", "/auth/logout"])
def test_post_requires_csrf_token(client, path):
    response = client.post(path, data={})
    assert response.status_code == 400


def test_external_next_url_is_ignored(client, test_app):
    add_user(test_app)
    response = login(client, next_url="//evil.example/path")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/student")


def test_internal_next_url_is_honored(client, test_app):
    add_user(test_app)
    response = login(client, next_url="/files")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/files")


@pytest.mark.parametrize("next_url", ["https://evil.example/path", "/\\evil.example", "/%0D%0Aevil"])
def test_other_unsafe_next_urls_are_ignored(client, test_app, next_url):
    add_user(test_app)
    response = login(client, next_url=next_url)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/student")


def test_privileged_account_cli_is_not_public_registration(test_app):
    runner = test_app.test_cli_runner()
    result = runner.invoke(
        args=[
            "create-privileged-user",
            "--role", "SHOP_STAFF",
            "--name", "Staff Member",
            "--email", "staff@example.com",
        ],
        input=f"{PASSWORD}\n{PASSWORD}\n",
    )

    assert result.exit_code == 0, result.output
    with test_app.app_context():
        user = db.session.scalar(select(User).where(User.email == "staff@example.com"))
        assert user.role == UserRole.SHOP_STAFF
        assert user.check_password(PASSWORD)
