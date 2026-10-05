"""Dedicated shop sign-in stays separate and accepts only assigned staff."""

from app.extensions import db
from app.models import User, UserRole
from test_shops import PASSWORD, add_shop, add_user, login, token


def shop_login(client, shop_id, identifier, password=PASSWORD, *, next_url=""):
    path = "/auth/shop-login" + (f"?next={next_url}" if next_url else "")
    page = client.get(path)
    assert page.status_code == 200
    return client.post(path, data={
        "csrf_token": token(page), "shop_id": str(shop_id),
        "identifier": identifier, "password": password,
    })


def test_shop_login_is_hidden_from_student_and_professor_entry(client, test_app):
    shop_id = add_shop(test_app)
    add_shop(test_app, "New Shop")
    add_user(test_app, UserRole.SHOP_STAFF, "staff@campus.example", shop_id=shop_id)
    for path in ("/", "/auth/login", "/auth/register"):
        page = client.get(path)
        assert b"/auth/shop-login" not in page.data
        assert b"Blue and Silver staff?" not in page.data
    page = client.get("/auth/shop-login")
    assert page.headers["X-Robots-Tag"] == "noindex, nofollow"
    assert b"Campus Prints" in page.data and b"New Shop" in page.data
    assert b"Staff email or name" in page.data
    assert b"Back to landing page" in page.data

    for role in (UserRole.STUDENT, UserRole.PROFESSOR):
        email = f"{role.value.lower()}@campus.example"
        add_user(test_app, role, email)
        login(client, email)
        assert b"/auth/shop-login" not in client.get("/").data
        assert b"/auth/shop-login" not in client.get(
            "/student" if role == UserRole.STUDENT else "/professor"
        ).data
        assert client.get("/auth/shop-login").headers["Location"].endswith(
            "/student" if role == UserRole.STUDENT else "/professor"
        )
        client.post("/auth/logout", data={"csrf_token": token(client.get(
            "/student" if role == UserRole.STUDENT else "/professor"
        ))})


def test_assigned_staff_sign_in_by_email_or_name_and_shop_scope(client, test_app):
    blue = add_shop(test_app, "Blue and Silver Bookstore")
    other = add_shop(test_app, "CHALECOSPOT")
    provision = test_app.test_cli_runner().invoke(
        args=["create-blue-staff", "--name", "Blue Team"],
        input="Abcde\nAbcde\n",
    )
    assert provision.exit_code == 0, provision.output
    other_id = add_user(test_app, UserRole.SHOP_STAFF, "other@campus.example", shop_id=other)
    with test_app.app_context():
        db.session.get(User, other_id).name = "Other Team"
        db.session.commit()

    assert client.post("/auth/shop-login", data={
        "shop_id": str(other), "identifier": "Other Team", "password": PASSWORD,
    }).status_code == 400
    assert shop_login(client, blue, "Other Team").status_code == 200
    assert shop_login(client, other, "Other Team", "wrong").status_code == 200
    assert shop_login(client, other, "OTHER@CAMPUS.EXAMPLE", next_url="//evil.example").headers[
        "Location"
    ].endswith("/shop")
    assert b"CHALECOSPOT" in client.get("/shop").data
    logout = client.get("/shop")
    client.post("/auth/logout", data={"csrf_token": token(logout)})
    assert shop_login(client, blue, "blue team", "Abcde").headers["Location"].endswith("/shop")


def test_shop_login_rejects_nonstaff_and_unassigned_or_inactive_staff(client, test_app):
    shop_id = add_shop(test_app)
    student_email = "student@campus.example"
    add_user(test_app, UserRole.STUDENT, student_email)
    add_user(test_app, UserRole.PROFESSOR, "professor@campus.example")
    add_user(test_app, UserRole.ADMIN, "admin@campus.example")
    add_user(test_app, UserRole.SHOP_STAFF, "unassigned@campus.example")
    add_user(test_app, UserRole.SHOP_STAFF, "active@campus.example", shop_id=shop_id)
    inactive_id = add_user(test_app, UserRole.SHOP_STAFF, "inactive@campus.example", shop_id=shop_id)
    with test_app.app_context():
        db.session.get(User, inactive_id).is_active = False
        db.session.commit()
    for email in (student_email, "professor@campus.example", "admin@campus.example",
                  "unassigned@campus.example", "inactive@campus.example"):
        response = shop_login(client, shop_id, email)
        assert response.status_code == 200
        assert b"Invalid shop, staff email or name, or password" in response.data
    assert client.get("/shop").status_code in (302, 401)


def test_duplicate_staff_names_require_email(client, test_app):
    shop_id = add_shop(test_app)
    first_id = add_user(test_app, UserRole.SHOP_STAFF, "first@campus.example", shop_id=shop_id)
    second_id = add_user(test_app, UserRole.SHOP_STAFF, "second@campus.example", shop_id=shop_id)
    with test_app.app_context():
        db.session.get(User, first_id).name = "Print Team"
        db.session.get(User, second_id).name = "Print Team"
        db.session.commit()
    assert shop_login(client, shop_id, "Print Team").status_code == 200
    assert shop_login(client, shop_id, "second@campus.example").headers["Location"].endswith("/shop")
