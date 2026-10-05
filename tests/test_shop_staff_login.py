"""Shop staff sign in without selecting a shop; the account assignment wins."""

from app.extensions import db
from app.models import User, UserRole
from test_shops import PASSWORD, add_shop, add_user, login, token


ERROR = b"Unable to sign in. Check your staff email or name and password"


def shop_login(client, identifier, password=PASSWORD, *, next_url="", extra=None):
    path = "/auth/shop-login" + (f"?next={next_url}" if next_url else "")
    page = client.get(path)
    assert page.status_code == 200
    data = {"csrf_token": token(page), "identifier": identifier, "password": password}
    if extra:
        data.update(extra)
    return client.post(path, data=data)


def logout(client):
    page = client.get("/shop")
    response = client.post("/auth/logout", data={"csrf_token": token(page)})
    assert response.status_code == 302


def test_shop_login_has_only_credentials_and_stays_out_of_public_entry(client, test_app):
    add_shop(test_app, "CHALECOSPOT")
    for path in ("/", "/auth/login", "/auth/register"):
        page = client.get(path)
        assert b"/auth/shop-login" not in page.data
        assert b"Blue and Silver staff?" not in page.data
    page = client.get("/auth/shop-login")
    assert page.headers["X-Robots-Tag"] == "noindex, nofollow"
    assert b'name="identifier"' in page.data
    assert b'name="password"' in page.data
    assert b'name="shop_id"' not in page.data
    assert b"Printing shop</label>" not in page.data
    assert b"Choose your assigned shop" not in page.data
    assert b"CHALECOSPOT" not in page.data
    assert b"Back to landing page" in page.data

    for role in (UserRole.STUDENT, UserRole.PROFESSOR):
        email = f"{role.value.lower()}@campus.example"
        add_user(test_app, role, email)
        login(client, email)
        home = "/student" if role == UserRole.STUDENT else "/professor"
        assert b"/auth/shop-login" not in client.get(home).data
        assert client.get("/auth/shop-login").headers["Location"].endswith(home)
        client.post("/auth/logout", data={"csrf_token": token(client.get(home))})


def test_four_staff_names_resolve_to_database_assigned_shops(client, test_app):
    names = (
        ("bns", "Blue and Silver Bookstore"),
        ("chaleco", "CHALECOSPOT"),
        ("iced", "Iced Design and Prints"),
        ("pixels", "Pixels Print and Press"),
    )
    shop_ids = {name: add_shop(test_app, name) for _, name in names}
    provision = test_app.test_cli_runner().invoke(
        args=["create-blue-staff", "--name", "bns"], input="Abcde\nAbcde\n",
    )
    assert provision.exit_code == 0, provision.output
    for alias, name in names[1:]:
        user_id = add_user(test_app, UserRole.SHOP_STAFF, f"{alias}@campus.example",
                           shop_id=shop_ids[name])
        with test_app.app_context():
            db.session.get(User, user_id).name = alias
            db.session.commit()

    for alias, name in names:
        other_name = next(other for _, other in names if other != name)
        response = shop_login(
            client, alias, "Abcde" if alias == "bns" else PASSWORD,
            extra={"shop_id": str(shop_ids[other_name])},
        )
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/shop")
        own_page = client.get("/shop")
        assert name.encode() in own_page.data
        assert client.get(f"/shop?shop_id={shop_ids[other_name]}").data == own_page.data
        assert name.encode() in client.get(
            f"/shop/manage?shop_id={shop_ids[other_name]}"
        ).data
        assert client.get(f"/shops/{shop_ids[other_name]}").status_code == 403
        assert client.get(f"/admin/shops/{shop_ids[other_name]}/edit").status_code == 403
        assert client.get("/admin/professors").status_code == (200 if alias == "bns" else 403)
        logout(client)


def test_staff_email_login_and_safe_next(client, test_app):
    shop_id = add_shop(test_app)
    add_user(test_app, UserRole.SHOP_STAFF, "staff@campus.example", shop_id=shop_id)
    assert client.post("/auth/shop-login", data={
        "identifier": "staff@campus.example", "password": PASSWORD,
    }).status_code == 400
    unsafe = shop_login(client, "STAFF@CAMPUS.EXAMPLE", next_url="//evil.example")
    assert unsafe.headers["Location"].endswith("/shop")
    logout(client)
    valid = shop_login(client, "staff@campus.example", next_url="/shop/manage")
    assert valid.headers["Location"].endswith("/shop/manage")


def test_invalid_inactive_unassigned_and_nonstaff_accounts_share_one_error(client, test_app):
    shop_id = add_shop(test_app)
    add_user(test_app, UserRole.STUDENT, "student@campus.example")
    add_user(test_app, UserRole.PROFESSOR, "professor@campus.example")
    add_user(test_app, UserRole.ADMIN, "admin@campus.example")
    add_user(test_app, UserRole.SHOP_STAFF, "unassigned@campus.example")
    active_id = add_user(test_app, UserRole.SHOP_STAFF, "active@campus.example", shop_id=shop_id)
    inactive_id = add_user(test_app, UserRole.SHOP_STAFF, "inactive@campus.example", shop_id=shop_id)
    with test_app.app_context():
        db.session.get(User, inactive_id).is_active = False
        db.session.commit()

    for identifier, password in (
        ("missing@campus.example", PASSWORD),
        ("active@campus.example", "wrong"),
        ("student@campus.example", PASSWORD),
        ("professor@campus.example", PASSWORD),
        ("admin@campus.example", PASSWORD),
        ("unassigned@campus.example", PASSWORD),
        ("inactive@campus.example", PASSWORD),
    ):
        response = shop_login(client, identifier, password)
        assert response.status_code == 200
        assert ERROR in response.data
    assert client.get("/shop").status_code in (302, 401)


def test_ambiguous_staff_names_require_email(client, test_app):
    first_shop = add_shop(test_app, "First Prints")
    second_shop = add_shop(test_app, "Second Prints")
    first = add_user(test_app, UserRole.SHOP_STAFF, "first@campus.example", shop_id=first_shop)
    second = add_user(test_app, UserRole.SHOP_STAFF, "second@campus.example", shop_id=second_shop)
    with test_app.app_context():
        db.session.get(User, first).name = "Print Team"
        db.session.get(User, second).name = "Print Team"
        db.session.commit()
    response = shop_login(client, "Print Team")
    assert response.status_code == 200 and ERROR in response.data
    assert shop_login(client, "second@campus.example").headers["Location"].endswith("/shop")
    assert b"Second Prints" in client.get("/shop").data
