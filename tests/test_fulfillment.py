"""Stage 16 fulfillment selection, scheduling, pricing, and snapshots."""

from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import (FeeType, Order, OrderDestination, PrintingShop,
                        ServiceType, ShopFee, ShopService, User, UserRole)
from test_orders import (approved_professor, file, offer_professor_service,
                         pickup_fields, shop, sign_in, student, token)
from app.services.tracking import build_tracking


def date_after(days):
    return (datetime.now(ZoneInfo("Asia/Manila")).date() + timedelta(days=days)).isoformat()


def delivery_fields():
    return {
        "destination": "DELIVERY", "delivery_recipient_name": "Rafael Cruz",
        "delivery_recipient_phone": "+639171234567",
        "delivery_address": "123 Campus Road, Laguna, Philippines",
        "delivery_date": date_after(3), "delivery_slot": "14:00-15:00",
    }


def offer_delivery(app, shop_id, *, enabled=True, fee="40.00"):
    with app.app_context():
        db.session.add(ShopService(shop_id=shop_id, service_type=ServiceType.DELIVERY, enabled=enabled))
        if fee is not None:
            db.session.add(ShopFee(shop_id=shop_id, fee_type=FeeType.DELIVERY, amount=Decimal(fee)))
        db.session.commit()


def setup(client, app, *, delivery=False):
    user_id = student(app)
    shop_id = shop(app)
    file_id = file(app, user_id)
    if delivery:
        offer_delivery(app, shop_id)
    sign_in(client, user_id)
    return user_id, shop_id, file_id


def review(client, shop_id, file_id, fields):
    return client.get("/orders/new", query_string={"shop_id": shop_id, "file_id": file_id, **fields})


def place(client, shop_id, file_id, fields):
    return client.post("/orders/create", data={
        "csrf_token": token(client.get("/student")), "shop_id": str(shop_id),
        "file_id": str(file_id), **fields,
    })


def test_pickup_review_placement_history_and_tracking(client, test_app):
    _, shop_id, file_id = setup(client, test_app)
    fields = pickup_fields()
    reviewed = review(client, shop_id, file_id, fields)
    assert reviewed.status_code == 200
    assert b"Scheduled Pickup" in reviewed.data
    assert fields["pickup_date"].encode() in reviewed.data
    placed = place(client, shop_id, file_id, fields)
    assert placed.status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert order.destination == OrderDestination.PICKUP
        assert order.pickup_date.isoformat() == fields["pickup_date"]
        assert order.pickup_slot == fields["pickup_slot"]
        assert order.delivery_fee == Decimal("0.00")
        assert order.payment is None
        assert "Scheduled Pickup requested" in build_tracking(order).steps[-1].detail
    detail = client.get(placed.headers["Location"])
    assert b"Requested pickup date" in detail.data
    assert b"Order tracking" in detail.data
    assert b"Scheduled Pickup" in client.get("/orders").data


def test_delivery_review_placement_fee_snapshot_and_staff(client, test_app):
    _, shop_id, file_id = setup(client, test_app, delivery=True)
    fields = delivery_fields()
    reviewed = review(client, shop_id, file_id, fields)
    assert reviewed.status_code == 200
    assert b"Delivery fee: PHP 40.00" in reviewed.data
    placed = place(client, shop_id, file_id, fields)
    assert placed.status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert order.destination == OrderDestination.DELIVERY
        assert order.delivery_address == fields["delivery_address"]
        assert order.delivery_date.isoformat() == fields["delivery_date"]
        assert order.delivery_fee == Decimal("40.00")
        assert order.total == order.subtotal + order.rush_fee + order.delivery_fee
        assert "No courier booking is recorded" in build_tracking(order).steps[-1].detail
        fee = db.session.scalar(select(ShopFee).where(ShopFee.shop_id == shop_id))
        fee.amount = Decimal("99.00")
        db.session.commit()
        assert order.delivery_fee == Decimal("40.00")
    detail = client.get(placed.headers["Location"])
    assert b"Delivery fee: PHP 40.00" in detail.data
    assert b"No courier has been booked" in detail.data
    assert b"Delivery:" in client.get("/orders").data
    staff_id = student(test_app, "staff16@example.edu", UserRole.SHOP_STAFF)
    other_staff_id = student(test_app, "other16@example.edu", UserRole.SHOP_STAFF)
    other_shop_id = shop(test_app, name="Other Campus Shop")
    with test_app.app_context():
        db.session.get(User, staff_id).shop_id = shop_id
        db.session.get(User, other_staff_id).shop_id = other_shop_id
        db.session.commit()
    staff_url = placed.headers["Location"].replace("/orders/", "/staff/orders/", 1)
    sign_in(client, staff_id)
    staff_detail = client.get(staff_url)
    assert staff_detail.status_code == 200
    assert b"Rafael Cruz" in staff_detail.data
    assert b"Delivery fee" in staff_detail.data
    sign_in(client, other_staff_id)
    assert client.get(staff_url).status_code == 404


@pytest.mark.parametrize("changes", [
    {"destination": ""}, {"destination": "INVALID"},
    {"pickup_date": ""}, {"pickup_date": "2020-01-01"},
    {"pickup_date": "not-a-date"}, {"pickup_date": date_after(31)},
    {"pickup_slot": "18:00-19:00"}, {"pickup_slot": ""},
    {"delivery_address": "forged"}, {"delivery_fee": "0.01"},
])
def test_pickup_invalid_requests_create_no_order(client, test_app, changes):
    _, shop_id, file_id = setup(client, test_app)
    fields = {**pickup_fields(), **changes}
    assert review(client, shop_id, file_id, fields).status_code == 400
    assert place(client, shop_id, file_id, fields).status_code == 400
    with test_app.app_context():
        assert db.session.scalar(select(Order)) is None


@pytest.mark.parametrize("changes", [
    {"delivery_recipient_name": ""}, {"delivery_recipient_phone": ""},
    {"delivery_recipient_phone": "not a number"}, {"delivery_address": ""},
    {"delivery_date": ""}, {"delivery_date": "yesterday"},
    {"delivery_date": "2020-01-01"}, {"delivery_date": date_after(31)},
    {"delivery_slot": ""}, {"delivery_slot": "18:00-19:00"},
    {"pickup_slot": "14:00-15:00"}, {"delivery_fee": "0.01"},
])
def test_delivery_invalid_requests_create_no_order(client, test_app, changes):
    _, shop_id, file_id = setup(client, test_app, delivery=True)
    fields = {**delivery_fields(), **changes}
    assert review(client, shop_id, file_id, fields).status_code == 400
    assert place(client, shop_id, file_id, fields).status_code == 400
    with test_app.app_context():
        assert db.session.scalar(select(Order)) is None


def test_delivery_requires_enabled_service_and_configured_fee(client, test_app):
    _, shop_id, file_id = setup(client, test_app)
    assert review(client, shop_id, file_id, delivery_fields()).status_code == 400
    assert place(client, shop_id, file_id, delivery_fields()).status_code == 400
    offer_delivery(test_app, shop_id, fee=None)
    assert review(client, shop_id, file_id, delivery_fields()).status_code == 400
    with test_app.app_context():
        assert db.session.scalar(select(Order)) is None


def test_shop_hours_and_configured_windows_are_authoritative(client, test_app):
    _, shop_id, file_id = setup(client, test_app, delivery=True)
    with test_app.app_context():
        db.session.get(PrintingShop, shop_id).closing_time = time(14)
        db.session.commit()
    assert review(client, shop_id, file_id, pickup_fields()).status_code == 400
    assert review(client, shop_id, file_id, delivery_fields()).status_code == 400
    test_app.config["PICKUP_TIME_SLOTS"] = ("10:00-11:00",)
    test_app.config["PICKUP_MAX_DAYS"] = 4
    good = {**pickup_fields(), "pickup_slot": "10:00-11:00"}
    assert review(client, shop_id, file_id, good).status_code == 200
    assert review(client, shop_id, file_id, {**good, "pickup_date": date_after(5)}).status_code == 400
    test_app.config["DELIVERY_TIME_SLOTS"] = ("10:00-11:00",)
    test_app.config["DELIVERY_LEAD_DAYS"] = 4
    assert review(client, shop_id, file_id, {
        **delivery_fields(), "delivery_slot": "10:00-11:00",
    }).status_code == 400
    assert review(client, shop_id, file_id, {
        **delivery_fields(), "delivery_date": date_after(4), "delivery_slot": "10:00-11:00",
    }).status_code == 200


def test_two_rush_items_and_delivery_charge_each_fee_once(client, test_app):
    user_id = student(test_app)
    shop_id = shop(test_app, rush=True)
    offer_delivery(test_app, shop_id)
    first, second = file(test_app, user_id, rush=True), file(test_app, user_id, name="second.pdf", rush=True)
    sign_in(client, user_id)
    fields = {"shop_id": str(shop_id), "file_id": [str(first), str(second)], **delivery_fields()}
    response = client.get("/orders/new", query_string=fields)
    assert response.status_code == 200
    assert b"Rush printing fee: PHP 5.50" in response.data
    assert b"Delivery fee: PHP 40.00" in response.data
    assert client.post("/orders/create", data={
        **fields, "csrf_token": token(response), "delivery_fee": "0.01",
    }).status_code == 400
    assert client.post("/orders/create", data={
        **fields, "csrf_token": token(response), "total": "0.01",
    }).status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert len(order.items) == 2
        assert order.rush_fee == Decimal("5.50")
        assert order.delivery_fee == Decimal("40.00")
        assert order.fees_total == Decimal("45.50")
        assert order.total == order.subtotal + Decimal("45.50")
        assert order.payment is None


def test_professor_has_no_delivery_fee_even_when_shop_offers_delivery(client, test_app):
    _, shop_id, file_id = setup(client, test_app, delivery=True)
    offer_professor_service(test_app, shop_id)
    professor = approved_professor(test_app)
    fields = {"destination": "PROFESSOR", "professor_id": str(professor)}
    assert review(client, shop_id, file_id, fields).status_code == 200
    placed = place(client, shop_id, file_id, fields)
    assert placed.status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert order.destination == OrderDestination.PROFESSOR
        assert order.professor_name == "Maria Santos"
        assert order.delivery_fee == Decimal("0.00")
        assert order.payment is None


def test_browser_review_posts_without_address_in_edit_url(client, test_app):
    _, shop_id, file_id = setup(client, test_app, delivery=True)
    page = client.get("/orders/new", query_string={"edit": "1", "file_id": file_id, "shop_id": shop_id})
    response = client.post("/orders/new", data={
        "csrf_token": token(page), "review": "1", "file_id": str(file_id),
        "shop_id": str(shop_id), **delivery_fields(),
    })
    assert response.status_code == 200
    assert b"123 Campus Road" in response.data
    import re
    edit_url = re.search(rb'href="([^"]+)"[^>]*>.*?Edit files and settings', response.data)
    assert edit_url and b"delivery_address" not in edit_url.group(1)
    edit = client.get(edit_url.group(1).decode())
    assert edit.status_code == 200
    assert b"123 Campus Road" in edit.data


def test_fee_change_requires_reconfirmation(client, test_app):
    _, shop_id, file_id = setup(client, test_app, delivery=True)
    fields = delivery_fields()
    assert review(client, shop_id, file_id, fields).status_code == 200
    with test_app.app_context():
        fee = db.session.scalar(select(ShopFee).where(ShopFee.shop_id == shop_id))
        fee.amount = Decimal("45.00")
        db.session.commit()
    response = place(client, shop_id, file_id, fields)
    assert response.status_code == 409
    assert b"Delivery fee: PHP 45.00" in response.data
    assert place(client, shop_id, file_id, fields).status_code == 302


def test_pickup_cannot_be_changed_to_professor_after_creation(client, test_app):
    _, shop_id, file_id = setup(client, test_app)
    offer_professor_service(test_app, shop_id)
    professor_id = approved_professor(test_app)
    fields = pickup_fields()
    assert review(client, shop_id, file_id, fields).status_code == 200
    url = place(client, shop_id, file_id, fields).headers["Location"]
    response = client.post(url + "/professor", data={
        "csrf_token": token(client.get(url)), "professor_id": str(professor_id),
    })
    assert response.status_code == 400
    with test_app.app_context():
        assert db.session.scalar(select(Order)).destination == OrderDestination.PICKUP


def test_method_duplicates_and_csrf_are_rejected(client, test_app):
    _, shop_id, file_id = setup(client, test_app)
    fields = pickup_fields()
    duplicate = {**fields, "destination": ["PICKUP", "DELIVERY"]}
    assert review(client, shop_id, file_id, duplicate).status_code == 400
    assert place(client, shop_id, file_id, duplicate).status_code == 400
    assert client.post("/orders/create", data={
        "shop_id": shop_id, "file_id": file_id, **fields,
    }).status_code == 400
