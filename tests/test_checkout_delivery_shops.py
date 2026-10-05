"""Normal delivery follows each shop's saved service and fee for both customer roles."""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import FeeType, Order, OrderDestination, PrintingShop, ServiceType, ShopFee, ShopService, UserRole
from test_checkout_flow import print_fields, post, upload_checkout_file
from test_fulfillment import delivery_fields
from test_orders import pickup_fields, sign_in, student
from test_stage31_fulfillment import configure, select_shop


SHOPS = (
    "Blue and Silver Bookstore", "CHALECOSPOT", "Iced Design and Prints", "Pixels Print and Press",
)


def seeded_shop(app, name):
    assert app.test_cli_runner().invoke(args=["seed-sample-shops"]).exit_code == 0
    with app.app_context():
        return db.session.scalar(select(PrintingShop.id).where(PrintingShop.name == name))


@pytest.mark.parametrize("name", SHOPS)
@pytest.mark.parametrize("role", (UserRole.STUDENT, UserRole.PROFESSOR))
def test_delivery_checkout_for_each_shop_and_customer_role(client, test_app, name, role):
    shop_id = seeded_shop(test_app, name)
    owner = student(test_app, role=role)
    sign_in(client, owner)
    file_id = upload_checkout_file(client, test_app, owner)
    page = select_shop(client, file_id, shop_id)
    assert page.status_code == 200
    assert b'data-method-choice="DELIVERY"' in page.data
    assert b'Have your printed papers delivered to you.' in page.data
    assert b'data-method-fields="DELIVERY"' in page.data
    assert b'Scheduled Pickup' in page.data
    professor_label = b'Deliver to Professor' if role == UserRole.STUDENT else b'Deliver to Faculty'
    assert professor_label not in page.data

    configured = post(client, "/checkout/fulfillment", configure(file_id, **delivery_fields()))
    assert configured.status_code == 302
    assert configured.headers["Location"].endswith("/checkout/payment")
    payment = client.get("/checkout/payment")
    assert payment.status_code == 200 and b"PHP 30.00" in payment.data
    assert post(client, "/checkout/payment", {"payment_method": "ONSITE"}).status_code == 302
    review = client.get("/checkout/review")
    assert review.status_code == 200
    assert b"Delivery" in review.data and delivery_fields()["delivery_address"].encode() in review.data
    placed = post(client, "/checkout/place")
    assert placed.status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert order.user_id == owner and order.shop_id == shop_id
        assert order.destination == OrderDestination.DELIVERY
        assert order.delivery_address == delivery_fields()["delivery_address"]
        assert order.delivery_fee == Decimal("30.00")
        assert order.professor_id is None


@pytest.mark.parametrize("role", (UserRole.STUDENT, UserRole.PROFESSOR))
def test_disabled_delivery_hidden_and_forged_post_rejected(client, test_app, role):
    shop_id = seeded_shop(test_app, "CHALECOSPOT")
    with test_app.app_context():
        service = db.session.scalar(select(ShopService).where(
            ShopService.shop_id == shop_id, ShopService.service_type == ServiceType.DELIVERY,
        ))
        service.enabled = False
        db.session.commit()
    owner = student(test_app, role=role)
    sign_in(client, owner)
    file_id = upload_checkout_file(client, test_app, owner)
    page = select_shop(client, file_id, shop_id)
    assert b'data-method-choice="DELIVERY"' not in page.data
    assert b'data-method-fields="DELIVERY"' not in page.data
    assert post(client, "/checkout/fulfillment", configure(file_id, **delivery_fields())).status_code == 400
    assert client.get("/checkout/payment").headers["Location"].endswith("/checkout/fulfillment")
    assert post(client, "/checkout/fulfillment", configure(file_id, **pickup_fields())).status_code == 302


def test_switching_shops_clears_delivery_and_recomputes_options(client, test_app):
    enabled = seeded_shop(test_app, "Blue and Silver Bookstore")
    with test_app.app_context():
        disabled = db.session.scalar(select(PrintingShop.id).where(PrintingShop.name == "CHALECOSPOT"))
        service = db.session.scalar(select(ShopService).where(
            ShopService.shop_id == disabled, ShopService.service_type == ServiceType.DELIVERY,
        ))
        service.enabled = False
        db.session.commit()
    owner = student(test_app)
    sign_in(client, owner)
    file_id = upload_checkout_file(client, test_app, owner)
    select_shop(client, file_id, enabled)
    assert post(client, "/checkout/fulfillment", configure(file_id, **delivery_fields())).status_code == 302
    assert post(client, "/checkout/payment", {"payment_method": "ONSITE"}).status_code == 302
    assert post(client, "/checkout/shop", {"shop_id": str(disabled), **print_fields(file_id)}).status_code == 302
    page = client.get("/checkout/fulfillment")
    assert b'data-method-choice="DELIVERY"' not in page.data
    assert b'name="destination"' in page.data and b'name="destination" value="PICKUP" checked' not in page.data
    assert client.get("/checkout/payment").headers["Location"].endswith("/checkout/fulfillment")
    assert post(client, "/checkout/fulfillment", configure(file_id, **delivery_fields())).status_code == 400
    assert post(client, "/checkout/shop", {"shop_id": str(enabled), **print_fields(file_id)}).status_code == 302
    assert b'data-method-choice="DELIVERY"' in client.get("/checkout/fulfillment").data


def test_upload_shop_link_also_clears_previous_fulfillment(client, test_app):
    enabled = seeded_shop(test_app, "Blue and Silver Bookstore")
    with test_app.app_context():
        other = db.session.scalar(select(PrintingShop.id).where(PrintingShop.name == "Pixels Print and Press"))
    owner = student(test_app)
    sign_in(client, owner)
    file_id = upload_checkout_file(client, test_app, owner)
    select_shop(client, file_id, enabled)
    assert post(client, "/checkout/fulfillment", configure(file_id, **delivery_fields())).status_code == 302
    assert client.get("/checkout/upload", query_string={"shop_id": other}).status_code == 200
    with client.session_transaction() as state:
        assert state["checkout_draft"]["shop_id"] == other
        assert "fulfillment" not in state["checkout_draft"]
    assert client.get("/checkout/payment").headers["Location"].endswith("/checkout/fulfillment")


def test_seed_updates_missing_delivery_without_overwriting_saved_choice(test_app):
    seeded_shop(test_app, "Blue and Silver Bookstore")
    with test_app.app_context():
        shops = {shop.name: shop for shop in db.session.scalars(select(PrintingShop)).all()}
        original_ids = {name: shop.id for name, shop in shops.items()}
        blue = shops["Blue and Silver Bookstore"]
        chaleco = shops["CHALECOSPOT"]
        blue.services.remove(next(item for item in blue.services if item.service_type == ServiceType.DELIVERY))
        blue.fees.remove(next(item for item in blue.fees if item.fee_type == FeeType.DELIVERY))
        next(item for item in chaleco.services if item.service_type == ServiceType.DELIVERY).enabled = False
        db.session.commit()
    for _ in range(2):
        assert test_app.test_cli_runner().invoke(args=["seed-sample-shops"]).exit_code == 0
    with test_app.app_context():
        shops = {shop.name: shop for shop in db.session.scalars(select(PrintingShop)).all()}
        assert {name: shop.id for name, shop in shops.items()} == original_ids
        for name, shop in shops.items():
            services = [item for item in shop.services if item.service_type == ServiceType.DELIVERY]
            fees = [item for item in shop.fees if item.fee_type == FeeType.DELIVERY]
            assert len(services) == len(fees) == 1
            assert services[0].enabled is (name != "CHALECOSPOT")
            assert fees[0].amount == Decimal("30.00")
