"""Blue and Silver's local name/password account stays scoped to that shop."""

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import User, UserRole
from app.services.admin_management import ManagementError, assign_staff_to_shop
from test_orders import shop, student, token


def provision(app, name="Blue and Silver Bookstore", password="Abcde"):
    return app.test_cli_runner().invoke(
        args=["create-blue-staff", "--name", name],
        input=f"{password}\n{password}\n",
    )


def blue_login(client, name, password):
    page = client.get("/auth/login?blue=1")
    assert page.status_code == 200
    return client.post("/auth/login?blue=1", data={
        "csrf_token": token(page), "name": name, "password": password,
    })


def test_blue_staff_can_be_provisioned_and_log_in_with_name_only(client, test_app):
    blue = shop(test_app, name="Blue and Silver Bookstore")
    result = provision(test_app)
    assert result.exit_code == 0, result.output
    with test_app.app_context():
        user = db.session.scalar(select(User).where(User.shop_id == blue))
        assert user.role == UserRole.SHOP_STAFF
        assert user.uses_name_login
        assert user.login_identifier == "Blue and Silver Bookstore"
        assert user.email.endswith("@blue-staff.invalid")
        assert user.check_password("Abcde")
    page = client.get("/auth/login?blue=1")
    assert b'name="name"' in page.data and b'name="email"' not in page.data
    assert b'name="remember_me"' not in page.data
    assert blue_login(client, "blue and silver bookstore", "Abcde").headers["Location"].endswith("/shop")
    assert client.get("/admin/professors").status_code == 200


def test_short_blue_password_is_narrowly_scoped_and_login_is_protected(client, test_app):
    blue = shop(test_app, name="Blue and Silver Bookstore")
    other = shop(test_app, name="CHALECOSPOT")
    assert provision(test_app, password="abcd").exit_code != 0
    assert provision(test_app, password="abcd1").exit_code != 0
    assert provision(test_app, password="abcdefghi").exit_code != 0
    assert provision(test_app, name="Blue Team").exit_code == 0
    assert provision(test_app, name="blue team").exit_code != 0
    other_staff_id = student(test_app, "other.staff@example.edu", UserRole.SHOP_STAFF)
    with test_app.app_context():
        other_staff = db.session.get(User, other_staff_id)
        other_staff.name = "Other Team"
        other_staff.shop_id = other
        db.session.commit()
    assert client.post("/auth/login?blue=1", data={"name": "Blue Team", "password": "Abcde"}).status_code == 400
    assert blue_login(client, "Other Team", "A-strong-password-123").status_code == 200
    assert blue_login(client, "Blue Team", "Wrong").status_code == 200
    assert blue_login(client, "Blue Team", "Abcde").status_code == 302
    with test_app.app_context():
        account = db.session.scalar(select(User).where(User.shop_id == blue))
        assert account.login_identifier == "Blue Team"
        with pytest.raises(ManagementError):
            assign_staff_to_shop(account.id, other)
        assert account.shop_id == blue
        other_staff = db.session.get(User, other_staff_id)
        other_staff.name = "blue team"
        db.session.commit()
        with pytest.raises(ManagementError):
            assign_staff_to_shop(other_staff.id, blue)
        assert other_staff.shop_id == other


def test_short_password_provisioning_is_disabled_in_production(test_app):
    shop(test_app, name="Blue and Silver Bookstore")
    test_app.config["ENV_NAME"] = "production"
    assert provision(test_app).exit_code != 0
    with test_app.app_context():
        assert db.session.scalar(select(User)) is None
