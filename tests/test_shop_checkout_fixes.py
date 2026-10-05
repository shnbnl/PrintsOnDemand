"""Shop fees, atomic payment verification, and direct checkout shop selection."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import FeeType, Order, OrderDestination, OrderStatus, PaymentStatus, PrintingShop, ShopFee, ShopService, ServiceType, User, UserRole
from app.services.tracking import build_tracking
from test_checkout_delivery_shops import SHOPS, seeded_shop
from test_checkout_flow import post, upload_checkout_file
from test_fulfillment import delivery_fields
from test_orders import sign_in, student, token
from test_payment_verification import post_action, review_url
from test_shop_staff_management import staff_post
from test_stage31_fulfillment import configure, select_shop
from test_staff_orders import setup_orders


def staff_for(app, shop_id):
    staff = student(app, "fee-staff@example.edu", role=UserRole.SHOP_STAFF)
    with app.app_context():
        db.session.get(User, staff).shop_id = shop_id
        db.session.commit()
    return staff


@pytest.mark.parametrize("name", SHOPS)
@pytest.mark.parametrize("role", (UserRole.STUDENT, UserRole.PROFESSOR))
def test_shop_fee_checkout_and_verification_start_printing(client, test_app, name, role):
    shop_id = seeded_shop(test_app, name)
    staff = staff_for(test_app, shop_id)
    sign_in(client, staff)
    page = client.get("/shop/manage")
    assert b'for="delivery_fee_amount">Delivery Fee' in page.data
    assert b'id="delivery_fee_amount"' in page.data and b'value="30.00"' in page.data
    with test_app.app_context():
        other = db.session.scalar(select(PrintingShop).where(PrintingShop.id != shop_id))
        other_id = other.id
        shop = db.session.get(PrintingShop, shop_id)
        shop.online_enabled = True
        shop.online_account_name = shop.name
        shop.online_account_reference = "QA account"
        shop.online_instructions = "Send payment to the shop."
        db.session.commit()
    assert staff_post(client, "fees", {
        "fee_type": "DELIVERY", "amount": "45.50", "shop_id": str(other_id),
    }).status_code == 302
    with test_app.app_context():
        assert db.session.scalar(select(ShopFee).where(
            ShopFee.shop_id == other_id, ShopFee.fee_type == FeeType.DELIVERY,
        )).amount == Decimal("30.00")
        assert db.session.scalar(select(ShopService).where(
            ShopService.shop_id == shop_id, ShopService.service_type == ServiceType.DELIVERY,
        )).enabled
    owner = student(test_app, role=role)
    sign_in(client, owner)
    file_id = upload_checkout_file(client, test_app, owner)
    select_shop(client, file_id, shop_id)
    assert post(client, "/checkout/configure", configure(
        file_id, **delivery_fields(), delivery_fee="0.01",
    )).status_code == 400
    assert post(client, "/checkout/configure", configure(file_id, **delivery_fields())).status_code == 302
    assert b"Delivery fee: PHP 45.50" in client.get("/checkout/payment").data
    assert post(client, "/checkout/payment", {"payment_method": "ONLINE", "payment_reference": "FEE-1234"}).status_code == 302
    assert post(client, "/checkout/place").status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        payment_id = order.payment.id
        assert order.destination == OrderDestination.DELIVERY
        assert order.delivery_fee == Decimal("45.50") and order.total == order.subtotal + Decimal("45.50")
        assert order.status == OrderStatus.PENDING_PAYMENT
    sign_in(client, staff)
    url = f"/payments/verification/{payment_id}"
    assert post_action(client, url, "verify").status_code == 302
    assert b"Printing" in client.get(url).data
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert order.status == OrderStatus.PROCESSING
        assert order.payment.payment_status == PaymentStatus.PAID
        started = order.processing_started_at
        assert started == order.payment.reviewed_at
        assert len([step for step in build_tracking(order).steps if step.title == "Processing started"]) == 1
        assert order.ready_at is None and order.delivered_at is None and order.completed_at is None
    assert post_action(client, url, "verify").status_code == 409
    with test_app.app_context():
        assert db.session.scalar(select(Order)).processing_started_at == started


@pytest.mark.parametrize("amount", ("", "-0.01", "not-money", "NaN", "Infinity", "1.001", "100000000.00"))
def test_delivery_fee_rejects_invalid_values(client, test_app, amount):
    shop_id = seeded_shop(test_app, SHOPS[0])
    sign_in(client, staff_for(test_app, shop_id))
    response = staff_post(client, "fees", {"fee_type": "DELIVERY", "amount": amount})
    assert response.status_code == 400
    assert b'id="delivery-settings"' in response.data and b'role="alert"' in response.data
    with test_app.app_context():
        assert db.session.scalar(select(ShopFee).where(
            ShopFee.shop_id == shop_id, ShopFee.fee_type == FeeType.DELIVERY,
        )).amount == Decimal("30.00")


@pytest.mark.parametrize("enabled", (False, True))
def test_staff_can_create_zero_delivery_fee_without_changing_service(client, test_app, enabled):
    shop_id = seeded_shop(test_app, SHOPS[0])
    with test_app.app_context():
        fee = db.session.scalar(select(ShopFee).where(ShopFee.shop_id == shop_id, ShopFee.fee_type == FeeType.DELIVERY))
        db.session.delete(fee)
        service = db.session.scalar(select(ShopService).where(ShopService.shop_id == shop_id, ShopService.service_type == ServiceType.DELIVERY))
        service.enabled = enabled
        db.session.commit()
    sign_in(client, staff_for(test_app, shop_id))
    assert client.post("/shop/manage/fees", data={"fee_type": "DELIVERY", "amount": "12"}).status_code == 400
    assert staff_post(client, "fees", {"fee_type": "DELIVERY", "amount": "0.00"}).status_code == 302
    with test_app.app_context():
        assert db.session.scalar(select(ShopFee).where(ShopFee.shop_id == shop_id, ShopFee.fee_type == FeeType.DELIVERY)).amount == 0
        assert db.session.scalar(select(ShopService).where(ShopService.shop_id == shop_id, ShopService.service_type == ServiceType.DELIVERY)).enabled is enabled


@pytest.mark.parametrize("role", (UserRole.STUDENT, UserRole.PROFESSOR))
def test_customer_cannot_change_delivery_fee(client, test_app, role):
    seeded_shop(test_app, SHOPS[0])
    sign_in(client, student(test_app, role=role))
    response = client.post("/shop/manage/fees", data={
        "csrf_token": token(client.get("/checkout/upload")), "fee_type": "DELIVERY", "amount": "0",
    })
    assert response.status_code == 403


def test_payment_verification_rolls_back_if_order_transition_fails(client, test_app, monkeypatch):
    _, staff, _, url_a, url_b, *_ = setup_orders(client, test_app)
    url = review_url(test_app, url_a)
    sign_in(client, staff)
    execute = db.session.execute

    def conflict(statement, *args, **kwargs):
        if getattr(statement, "is_update", False) and statement.table.name == "orders":
            return SimpleNamespace(rowcount=0)
        return execute(statement, *args, **kwargs)

    monkeypatch.setattr(db.session, "execute", conflict)
    assert post_action(client, url, "verify").status_code == 409
    with test_app.app_context():
        for order in db.session.scalars(select(Order)).all():
            assert order.status == OrderStatus.PENDING_PAYMENT
            assert order.processing_started_at is None
        payment = db.session.scalar(select(Order).where(Order.order_reference == url_a.rsplit("/", 1)[1])).payment
        assert payment.payment_status == PaymentStatus.SUBMITTED
        assert payment.reviewed_at is None and payment.reviewed_by_id is None


@pytest.mark.parametrize("role", (UserRole.STUDENT, UserRole.PROFESSOR))
def test_checkout_map_panel_selection_posts_directly_and_validates_shop(client, test_app, role):
    shop_id = seeded_shop(test_app, SHOPS[0])
    owner = student(test_app, role=role)
    sign_in(client, owner)
    file_id = upload_checkout_file(client, test_app, owner)
    assert post(client, "/checkout/upload", {"file_id": str(file_id)}).status_code == 302
    page = client.get("/checkout/shop")
    assert page.data.count(b'class="checkout-map-info"') == 4
    assert b'data-checkout-select' in page.data
    assert b'Next: Configure Printing' not in page.data
    assert b'checkout-shop-grid' not in page.data
    assert b'data-shop-fallback open' in page.data
    assert post(client, "/checkout/shop", {}).status_code == 400
    assert post(client, "/checkout/shop", {"shop_id": "999999"}).status_code == 400
    with test_app.app_context():
        shop = db.session.get(PrintingShop, shop_id)
        shop.is_active = False
        db.session.commit()
    db.session.expire_all()
    assert post(client, "/checkout/shop", {"shop_id": str(shop_id)}).status_code == 400
    with test_app.app_context():
        shop = db.session.get(PrintingShop, shop_id)
        shop.is_active = True
        db.session.commit()
    db.session.expire_all()
    response = post(client, "/checkout/shop", {"shop_id": str(shop_id)})
    assert response.status_code == 302 and response.headers["Location"].endswith("/checkout/configure")
    with client.session_transaction() as state:
        assert state["checkout_draft"]["shop_id"] == shop_id
