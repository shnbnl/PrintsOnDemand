"""Shop-owned payment methods, QR isolation, and staff authorization."""

from io import BytesIO

import pytest
from PIL import Image

from app.extensions import db
from app.models import OrderDestination, PrintingShop, User, UserRole
from app.services.payments import PaymentError, validate_checkout_payment
from test_checkout_flow import post, start, upload_checkout_file
from test_orders import shop, sign_in, student, token


NAMES = (
    "Blue and Silver Bookstore", "CHALECOSPOT",
    "Iced Design and Prints", "Pixels Print and Press",
)


def image(color):
    output = BytesIO()
    Image.new("RGB", (32, 32), color).save(output, format="PNG")
    output.seek(0)
    return output


def setup_shops(app):
    ids = [shop(app, name=name) for name in NAMES]
    staff = [student(app, f"staff-{index}@example.edu", UserRole.SHOP_STAFF)
             for index in range(4)]
    with app.app_context():
        for user_id, shop_id in zip(staff, ids):
            db.session.get(User, user_id).shop_id = shop_id
        db.session.commit()
    return ids, staff


@pytest.mark.parametrize("index", range(4))
def test_each_staff_edits_only_assigned_shop_and_replaces_qr(client, test_app, index):
    ids, staff = setup_shops(test_app)
    sign_in(client, staff[index])
    page = client.get("/shop/manage")
    assert page.status_code == 200 and b"Payment settings" in page.data
    payload = {
        "csrf_token": token(page), "shop_id": str(ids[(index + 1) % 4]),
        "online_enabled": "y", "online_account_name": f"Account {index}",
        "online_account_reference": f"REFERENCE-{index}",
        "online_instructions": f"Instructions {index}",
        "payment_qr": (image((index * 50, 40, 100)), "qr.png"),
    }
    response = client.post("/shop/manage/payment", data=payload, content_type="multipart/form-data")
    assert response.status_code == 302
    qr = client.get("/shop/manage/payment/qr")
    assert qr.status_code == 200 and qr.mimetype == "image/png"
    with test_app.app_context():
        own = db.session.get(PrintingShop, ids[index])
        other = db.session.get(PrintingShop, ids[(index + 1) % 4])
        assert own.online_enabled and not own.cash_enabled
        assert own.online_account_name == f"Account {index}"
        assert own.online_account_reference == f"REFERENCE-{index}"
        assert own.payment_qr_data == qr.data
        assert not other.online_enabled and other.cash_enabled
        assert other.payment_qr_data != qr.data
    assert client.get(f"/shop/manage/{ids[(index + 1) % 4]}/payment").status_code == 404


@pytest.mark.parametrize("role", [UserRole.STUDENT, UserRole.PROFESSOR, UserRole.ADMIN])
def test_nonstaff_cannot_edit_shop_payment(client, test_app, role):
    user_id = student(test_app, f"{role.value.lower()}@example.edu", role)
    sign_in(client, user_id)
    assert client.get("/shop/manage").status_code == 403
    assert client.post("/shop/manage/payment", data={"csrf_token": token(client.get("/"))}).status_code == 403
    assert client.get("/shop/manage/payment/qr").status_code == 403


def test_customer_sees_selected_shop_details_and_private_qr(client, test_app):
    ids, _ = setup_shops(test_app)
    with test_app.app_context():
        for index, shop_id in enumerate(ids):
            record = db.session.get(PrintingShop, shop_id)
            record.online_enabled = True
            record.online_account_name = f"Merchant {index}"
            record.online_account_reference = f"SHOP-{index}"
        db.session.commit()
    owner = student(test_app)
    sign_in(client, owner)
    file_id = upload_checkout_file(client, test_app, owner)
    for index, shop_id in enumerate(ids):
        assert start(client, shop_id, file_id).status_code == 302
        page = client.get("/checkout/payment")
        assert f"Merchant {index}".encode() in page.data
        assert f"SHOP-{index}".encode() in page.data
        assert b"Placeholder QR" not in page.data
        qr = client.get("/checkout/payment/qr")
        assert qr.status_code == 200 and qr.mimetype == "image/png"
        with test_app.app_context():
            assert qr.data == db.session.get(PrintingShop, shop_id).payment_qr_data
        for other in range(4):
            if other != index:
                assert f"Merchant {other}".encode() not in page.data
    other_user = student(test_app, "other-payment@example.edu")
    sign_in(client, other_user)
    assert client.get("/checkout/payment/qr").status_code == 404


def test_disabled_methods_block_checkout_and_professor_delivery(client, test_app):
    owner = student(test_app)
    shop_id = shop(test_app, name="Blue and Silver Bookstore")
    with test_app.app_context():
        record = db.session.get(PrintingShop, shop_id)
        record.cash_enabled = False
        record.online_enabled = False
        db.session.commit()
        with pytest.raises(PaymentError):
            validate_checkout_payment(shop=record, destination=OrderDestination.PROFESSOR,
                                      method="ONLINE")
        with pytest.raises(PaymentError):
            validate_checkout_payment(shop=record, destination=OrderDestination.PROFESSOR,
                                      method="ONSITE")
    sign_in(client, owner)
    file_id = upload_checkout_file(client, test_app, owner)
    assert start(client, shop_id, file_id).status_code == 302
    page = client.get("/checkout/payment")
    assert b"No payment method is currently available" in page.data
    assert b"Back to shop selection" in page.data
    assert post(client, "/checkout/payment", {"payment_method": "ONSITE"}).status_code == 400
    assert post(client, "/checkout/payment", {"payment_method": "ONLINE"}).status_code == 400


def test_invalid_qr_upload_does_not_change_shop_settings(client, test_app):
    ids, staff = setup_shops(test_app)
    sign_in(client, staff[0])
    response = client.post("/shop/manage/payment", data={
        "csrf_token": token(client.get("/shop/manage")),
        "online_enabled": "y", "online_account_name": "Forged change",
        "payment_qr": (BytesIO(b"<script>not an image</script>"), "qr.png"),
    }, content_type="multipart/form-data")
    assert response.status_code == 400
    with test_app.app_context():
        record = db.session.get(PrintingShop, ids[0])
        assert record.cash_enabled and not record.online_enabled
        assert not record.online_account_name
