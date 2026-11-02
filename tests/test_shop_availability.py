"""Live business hours and staff-controlled breaks apply to every shop."""

from datetime import time

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import Order, PrintingShop, User, UserRole
from app.services.orders import create_order
from app.services.pricing import quote_order
from app.services.shop_hours import ShopClosedError, availability_status
from test_checkout_flow import post, setup, start
from test_ordering_hours import set_clock
from test_orders import file, shop, sign_in, student, token
from test_shop_map import map_data, set_location


def staff_for(app, shop_id, email):
    actor = student(app, email, UserRole.SHOP_STAFF)
    db.session.get(User, actor).shop_id = shop_id
    db.session.commit()
    return actor


@pytest.mark.parametrize("name", ["Blue and Silver Bookstore", "Iced Design and Prints", "CHALECOSPOT", "Pixels Print and Press"])
def test_each_shop_badge_uses_its_hours_and_break_setting(client, test_app, monkeypatch, name):
    shop_id = shop(test_app, name=name)
    set_location(test_app, shop_id)
    store = db.session.get(PrintingShop, shop_id)
    store.closing_time = time(18)
    db.session.commit()
    sign_in(client, student(test_app))
    for clock, on_break, expected in [
        (time(8, 59), False, "Closed"), (time(9), False, "Available"),
        (time(17, 59), True, "On a break"), (time(18), True, "Closed"),
        (time(18, 1), False, "Closed"),
    ]:
        set_clock(monkeypatch, clock)
        store.is_on_break = on_break
        db.session.commit()
        response = client.get("/shops/map")
        assert response.status_code == 200
        assert map_data(response)[0]["availability"]["label"] == expected
        assert f'data-shop-status="{shop_id}">{expected}</span>'.encode() in response.data
        live = client.get("/shops/availability")
        assert live.status_code == 200
        assert live.json["shops"][0]["label"] == expected
        assert live.headers["Cache-Control"] == "private, no-store"
    assert b"shop-availability.js" in response.data


def test_break_controls_are_csrf_protected_and_shop_scoped(client, test_app):
    one = shop(test_app, name="One")
    two = shop(test_app, name="Two")
    staff = staff_for(test_app, one, "staff@example.edu")
    sign_in(client, staff)
    dashboard = client.get("/shop")
    assert b">Take a break</button>" in dashboard.data
    assert b'role="switch" aria-checked="false"' in dashboard.data
    path = "/shop/manage/break"
    assert client.post(path, data={"on_break": "true"}).status_code == 400
    assert client.post(path, data={"on_break": "maybe", "csrf_token": token(dashboard)}).status_code == 400
    for _ in range(2):
        assert client.post(path, data={"on_break": "true", "shop_id": two,
                                      "csrf_token": token(client.get("/shop"))}).status_code == 302
    assert db.session.get(PrintingShop, one).is_on_break
    assert not db.session.get(PrintingShop, two).is_on_break
    assert b">Resume orders</button>" in client.get("/shop/manage").data
    assert client.post(path, data={"on_break": "false", "csrf_token": token(client.get("/shop"))}).status_code == 302
    assert not db.session.get(PrintingShop, one).is_on_break
    for role in (UserRole.STUDENT, UserRole.PROFESSOR, UserRole.ADMIN):
        actor = student(test_app, f"{role.value}@example.edu", role)
        sign_in(client, actor)
        assert client.post(path, data={"on_break": "true", "csrf_token": token(client.get(
            "/student" if role == UserRole.STUDENT else "/professor" if role == UserRole.PROFESSOR else "/admin"
        ))}).status_code == 403


def test_break_started_during_checkout_blocks_order_until_staff_resumes(client, test_app):
    _, shop_id, file_id = setup(client, test_app)
    assert start(client, shop_id, file_id).status_code == 302
    assert post(client, "/checkout/payment", {"payment_method": "ONSITE"}).status_code == 302
    staff = staff_for(test_app, shop_id, "break@example.edu")
    other_client = test_app.test_client()
    sign_in(other_client, staff)
    for value in ("true", "false"):
        assert other_client.post("/shop/manage/break", data={
            "on_break": value, "csrf_token": token(other_client.get("/shop")),
        }).status_code == 302
        result = post(client, "/checkout/place")
        if value == "true":
            assert result.status_code == 409
            assert b"is on a break" in result.data
            assert db.session.scalar(select(Order)) is None
        else:
            assert result.status_code == 302
            assert db.session.scalar(select(Order)).shop_id == shop_id


def test_service_refreshes_break_flag_after_quoting(test_app):
    owner = student(test_app)
    shop_id = shop(test_app)
    file_id = file(test_app, owner)
    quote = quote_order(user_id=owner, file_id=file_id, shop_id=shop_id, max_quantity=999)
    db.session.get(PrintingShop, shop_id).is_on_break = True
    db.session.commit()
    with pytest.raises(ShopClosedError, match="on a break"):
        create_order(quote)
    assert db.session.scalar(select(Order)) is None


def test_overnight_hours_keep_closed_and_break_states_distinct(test_app, monkeypatch):
    shop_id = shop(test_app)
    store = db.session.get(PrintingShop, shop_id)
    store.opening_time, store.closing_time = time(22), time(6)
    store.is_on_break = True
    for clock, expected in [(time(23), "BREAK"), (time(5, 59), "BREAK"), (time(6), "CLOSED")]:
        set_clock(monkeypatch, clock)
        assert availability_status(store)["code"] == expected
