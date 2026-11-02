"""Shop-local ordering limits, including stale checkout pages and direct posts."""

from datetime import datetime, time, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, update

from app.extensions import db
from app.models import Order, OrderItem, Payment, PrintingShop, UploadedFile
from app.services import shop_hours
from app.services.orders import create_order
from app.services.pricing import quote_order
from app.services.shop_hours import local_now as real_local_now
from test_checkout_flow import post, print_fields, setup, start
from test_orders import file, pickup_fields, place, review, shop, sign_in, student, token


def set_clock(monkeypatch, clock):
    value = datetime.now(ZoneInfo("Asia/Manila")).replace(
        hour=clock.hour, minute=clock.minute, second=clock.second, microsecond=clock.microsecond,
    )
    monkeypatch.setattr(shop_hours, "local_now", lambda: value)


@pytest.mark.parametrize("opening,closing,clock,expected", [
    (time(9), time(17), time(8, 59, 59), False),
    (time(9), time(17), time(9), True),
    (time(9), time(17), time(16, 59, 59), True),
    (time(9), time(17), time(17), False),
    (time(9), time(17), time(23), False),
    (time(9, 30), time(17, 15), time(9, 29, 59), False),
    (time(9, 30), time(17, 15), time(9, 30), True),
    (time(9, 30), time(17, 15), time(17, 15), False),
    (time(22), time(6), time(21, 59, 59), False),
    (time(22), time(6), time(22), True),
    (time(22), time(6), time(0), True),
    (time(22), time(6), time(5, 59, 59), True),
    (time(22), time(6), time(6), False),
    (time(9), time(9), time(12), False),
])
def test_opening_and_closing_boundaries(monkeypatch, opening, closing, clock, expected):
    set_clock(monkeypatch, clock)
    store = SimpleNamespace(is_active=True, opening_time=opening, closing_time=closing)
    assert shop_hours.is_open(store) is expected


def test_clock_uses_manila_even_when_server_clock_is_utc(test_app, monkeypatch):
    class UTCServerClock:
        @staticmethod
        def now(tz):
            return datetime(2026, 11, 2, 1, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(shop_hours, "datetime", UTCServerClock)
    value = real_local_now()
    assert value.hour == 9
    assert value.tzinfo == ZoneInfo("Asia/Manila")


@pytest.mark.parametrize("professor", [False, True])
@pytest.mark.parametrize("clock", [time(8, 59, 59), time(17)])
def test_stale_checkout_is_rejected_without_creating_any_records(
    client, test_app, monkeypatch, professor, clock,
):
    _, shop_id, file_id = setup(client, test_app, professor=professor)
    assert start(client, shop_id, file_id).status_code == 302
    assert post(client, "/checkout/payment", {"payment_method": "ONSITE"}).status_code == 302
    assert client.get("/checkout/review").status_code == 200
    set_clock(monkeypatch, clock)

    closed_review = client.get("/checkout/review")
    assert closed_review.status_code == 409
    assert b"Campus Prints is closed" in closed_review.data
    assert b"09:00 AM to 05:00 PM (Philippine time)" in closed_review.data
    assert b'type="submit" disabled>Place Order' in closed_review.data
    rejected = post(client, "/checkout/place")
    assert rejected.status_code == 409
    assert b"Campus Prints is closed" in rejected.data
    assert b'class="order-print-transition"' not in rejected.data
    for model in (Order, OrderItem, Payment):
        assert db.session.scalar(select(model)) is None
    assert db.session.get(UploadedFile, file_id).checkout_staged_at is not None
    with client.session_transaction() as state:
        assert state["checkout_draft"]["shop_id"] == shop_id

    # The same draft works when the shop opens, without another upload.
    set_clock(monkeypatch, time(9))
    assert post(client, "/checkout/place").status_code == 302
    assert db.session.scalar(select(Order)).shop_id == shop_id
    assert db.session.get(UploadedFile, file_id).checkout_staged_at is None


def test_closed_shop_blocks_progress_and_payment_but_can_still_be_browsed(
    client, test_app, monkeypatch,
):
    _, shop_id, file_id = setup(client, test_app, online=True)
    assert start(client, shop_id, file_id).status_code == 302
    set_clock(monkeypatch, time(17))

    workspace = client.get("/checkout/shop")
    assert workspace.status_code == 200
    assert b'data-ordering-open="false"' in workspace.data
    assert b'data-workspace-proceed disabled' in workspace.data
    fields = {"shop_id": str(shop_id), **print_fields(file_id)}
    quote = client.post("/checkout/shop", data={
        **fields, "intent": "quote", "csrf_token": token(client.get("/checkout/upload")),
    }, headers={"Accept": "application/json"})
    assert quote.status_code == 200
    assert quote.json["ordering_open"] is False
    assert "is closed" in quote.json["ordering_error"]
    assert post(client, "/checkout/shop", fields).status_code == 409
    for path in ("/checkout/fulfillment", "/checkout/payment"):
        assert client.get(path).status_code == 409
        assert post(client, path).status_code == 409
    assert client.get("/checkout/payment/qr").status_code == 409
    assert db.session.scalar(select(Order)) is None


def test_customer_can_switch_from_closed_shop_to_an_open_shop(client, test_app):
    _, closed_id, file_id = setup(client, test_app)
    open_id = shop(test_app, name="Open Campus Shop")
    db.session.get(PrintingShop, closed_id).closing_time = time(11)
    db.session.commit()
    assert post(client, "/checkout/upload", {"file_id": str(file_id)}).status_code == 302
    fields = print_fields(file_id)
    assert post(client, "/checkout/shop", {"shop_id": str(closed_id), **fields}).status_code == 409
    assert post(client, "/checkout/shop", {"shop_id": str(open_id), **fields}).status_code == 302
    assert post(client, "/checkout/fulfillment", pickup_fields()).status_code == 302
    assert post(client, "/checkout/payment", {"payment_method": "ONSITE"}).status_code == 302
    assert post(client, "/checkout/place").status_code == 302
    assert db.session.scalar(select(Order)).shop_id == open_id


@pytest.mark.parametrize("clock", [time(8, 59, 59), time(17)])
def test_legacy_create_cannot_bypass_hours(client, test_app, monkeypatch, clock):
    owner = student(test_app)
    shop_id = shop(test_app)
    file_id = file(test_app, owner)
    sign_in(client, owner)
    assert review(client, file_id, shop_id).status_code == 200
    set_clock(monkeypatch, clock)
    assert review(client, file_id, shop_id).status_code == 409
    rejected = place(client, file_id, shop_id)
    assert rejected.status_code == 409
    assert b"Campus Prints is closed" in rejected.data
    assert db.session.scalar(select(Order)) is None


def test_order_service_refreshes_hours_changed_after_quote(test_app):
    owner = student(test_app)
    shop_id = shop(test_app)
    file_id = file(test_app, owner)
    quote = quote_order(user_id=owner, file_id=file_id, shop_id=shop_id, max_quantity=999)
    assert quote.shop.closing_time == time(17)
    db.session.execute(update(PrintingShop).where(PrintingShop.id == shop_id).values(
        closing_time=time(11),
    ).execution_options(synchronize_session=False))
    db.session.commit()
    with pytest.raises(shop_hours.ShopClosedError, match="11:00 AM"):
        create_order(quote)
    assert db.session.scalar(select(Order)) is None
