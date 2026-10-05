"""Manual online and onsite payment intent, ownership, and state boundaries."""

from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Order, OrderStatus, Payment, PaymentMethod, PaymentStatus, PrintingShop, UserRole
from app.services.payments import PaymentError, select_payment_method, submit_online_reference
from test_orders import (
    approved_professor, file, offer_professor_service, place, professor_place,
    professor_review, review, shop, sign_in, student, token,
)


def configured_online(app):
    details = {
        "instructions": "Use the example transfer destination below.",
        "account_name": "Demo Campus Payments", "reference": "DEMO-ACCOUNT-123",
    }
    app.config["_TEST_SHOP_ONLINE_DEFAULTS"] = details
    with app.app_context():
        for record in db.session.scalars(select(PrintingShop)):
            record.online_enabled = True
            record.online_instructions = details["instructions"]
            record.online_account_name = details["account_name"]
            record.online_account_reference = details["reference"]
        db.session.commit()
        db.session.expire_all()


def created_order(client, app, *, professor=False):
    user_id = student(app)
    shop_id = shop(app)
    file_id = file(app, user_id)
    sign_in(client, user_id)
    if professor:
        offer_professor_service(app, shop_id)
        professor_id = approved_professor(app)
        assert professor_review(client, file_id, shop_id, professor_id).status_code == 200
        response = professor_place(client, file_id, shop_id, professor_id)
    else:
        assert review(client, file_id, shop_id).status_code == 200
        response = place(client, file_id, shop_id)
    assert response.status_code == 302
    return user_id, response.headers["Location"]


def choose(client, url, method, **extras):
    return client.post(url + "/payment", data={
        "csrf_token": token(client.get(url)), "payment_method": method, **extras,
    })


def submit(client, url, reference, **extras):
    return client.post(url + "/payment/submit", data={
        "csrf_token": token(client.get(url)), "payment_reference": reference, **extras,
    })


def test_online_payment_submission_is_unverified_and_idempotent(client, test_app):
    configured_online(test_app)
    _, url = created_order(client, test_app, professor=True)
    selected = choose(client, url, "ONLINE", amount="0.01", payment_status="PAID")
    assert selected.status_code == 302
    detail = client.get(url)
    assert b"Demo Campus Payments" in detail.data
    assert b"DEMO-ACCOUNT-123" in detail.data
    assert b"Use the example transfer destination below" in detail.data
    assert b"Maria Santos" in detail.data
    assert b"Payment pending" in detail.data
    assert b"Amount due: PHP 6.75" in detail.data
    assert b"Payment is pending" in detail.data
    with test_app.app_context():
        payment = db.session.scalar(select(Payment))
        order = db.session.scalar(select(Order))
        assert payment.order_id == order.id
        assert payment.payment_method == PaymentMethod.ONLINE
        assert payment.payment_status == PaymentStatus.PENDING
        assert payment.amount == order.total == Decimal("6.75")
        assert payment.currency == order.currency == "PHP"
        assert payment.payment_reference is None

    assert submit(
        client, url, "DEMO-REF-1234", amount="1", payment_status="PAID",
        order_total="1", payment_method="ONSITE",
    ).status_code == 302
    detail = client.get(url)
    assert b"Payment submitted for verification" in detail.data
    assert b"Payment submitted" in detail.data
    assert b"DEMO-REF-1234" in detail.data
    assert b"Payment submitted for verification" in detail.data
    assert b"Payment successful" not in detail.data
    assert submit(client, url, "DEMO-REF-1234").status_code == 302
    assert submit(client, url, "DIFFERENT-REF").status_code == 409
    assert choose(client, url, "ONSITE").status_code == 400
    with test_app.app_context():
        assert len(db.session.scalars(select(Payment)).all()) == 1
        payment = db.session.scalar(select(Payment))
        assert payment.payment_status == PaymentStatus.SUBMITTED
        assert payment.payment_reference == "DEMO-REF-1234"
        assert payment.amount == Decimal("6.75")
        assert payment.order.status == OrderStatus.PENDING_PAYMENT
        assert payment.order.professor_name == "Maria Santos"


def test_stale_online_submission_cannot_replace_recorded_reference(client, test_app):
    configured_online(test_app)
    _, url = created_order(client, test_app)
    assert choose(client, url, "ONLINE").status_code == 302
    # Keep the request-side ORM instance in PENDING while another session records
    # a reference, as can happen with concurrent browser submissions.
    payment = db.session.scalar(select(Payment))
    assert payment.payment_status == PaymentStatus.PENDING
    with test_app.app_context():
        current = db.session.get(Payment, payment.id)
        current.payment_reference = "FIRST-REF-123"
        current.payment_status = PaymentStatus.SUBMITTED
        db.session.commit()
    assert payment.payment_status == PaymentStatus.PENDING

    assert submit(client, url, "SECOND-REF-456").status_code == 409
    with test_app.app_context():
        current = db.session.get(Payment, payment.id)
        assert current.payment_status == PaymentStatus.SUBMITTED
        assert current.payment_reference == "FIRST-REF-123"


def test_stale_method_change_cannot_replace_submitted_payment(client, test_app):
    configured_online(test_app)
    _, url = created_order(client, test_app)
    assert choose(client, url, "ONLINE").status_code == 302
    payment = db.session.scalar(select(Payment))
    assert payment.payment_status == PaymentStatus.PENDING
    with test_app.app_context():
        current = db.session.get(Payment, payment.id)
        current.payment_reference = "FIRST-REF-123"
        current.payment_status = PaymentStatus.SUBMITTED
        db.session.commit()
    assert payment.payment_status == PaymentStatus.PENDING

    assert choose(client, url, "ONSITE").status_code == 409
    with test_app.app_context():
        current = db.session.get(Payment, payment.id)
        assert current.payment_method == PaymentMethod.ONLINE
        assert current.payment_status == PaymentStatus.SUBMITTED
        assert current.payment_reference == "FIRST-REF-123"


def test_onsite_selection_and_pending_method_change(client, test_app):
    configured_online(test_app)
    _, url = created_order(client, test_app)
    assert choose(client, url, "ONSITE", total="0.01", payment_status="PAID").status_code == 302
    detail = client.get(url)
    assert b"Order created. Payment will be made onsite." in detail.data
    assert b"Pay at the printing shop" in detail.data
    assert b"Payment pending" in detail.data
    assert b"Payment is pending" in detail.data
    assert choose(client, url, "ONSITE").status_code == 302
    assert submit(client, url, "DEMO-REF-1234").status_code == 409
    assert choose(client, url, "ONLINE").status_code == 302
    with test_app.app_context():
        payments = db.session.scalars(select(Payment)).all()
        assert len(payments) == 1
        assert payments[0].payment_method == PaymentMethod.ONLINE
        assert payments[0].payment_status == PaymentStatus.PENDING
        assert payments[0].amount == Decimal("6.75")


def test_online_requires_complete_configuration_and_valid_method(client, test_app):
    _, url = created_order(client, test_app)
    detail = client.get(url)
    assert b"Online payment" not in detail.data
    assert choose(client, url, "ONLINE").status_code == 400
    assert choose(client, url, "WIRE").status_code == 400
    assert choose(client, url, "ONSITE").status_code == 302
    with test_app.app_context():
        payment = db.session.scalar(select(Payment))
        assert payment.payment_method == PaymentMethod.ONSITE
        assert payment.payment_status == PaymentStatus.PENDING
    test_app.config["ONLINE_PAYMENT_ENABLED"] = True
    assert choose(client, url, "ONLINE").status_code == 400
    configured_online(test_app)
    with test_app.app_context():
        assert all(s.online_enabled and s.payment_qr_digest for s in db.session.scalars(select(PrintingShop)))
    selected = choose(client, url, "ONLINE")
    assert selected.status_code == 302, selected.get_data(as_text=True)


@pytest.mark.parametrize("reference", ["x", "bad<script>", "x" * 121, " " * 121 + "VALID-REF", " "])
def test_invalid_reference_is_rejected_without_state_change(client, test_app, reference):
    configured_online(test_app)
    _, url = created_order(client, test_app)
    assert choose(client, url, "ONLINE").status_code == 302
    assert submit(client, url, reference).status_code == 400
    with test_app.app_context():
        payment = db.session.scalar(select(Payment))
        assert payment.payment_status == PaymentStatus.PENDING
        assert payment.payment_reference is None


def test_online_qr_comes_from_owned_shop_not_global_url(client, test_app):
    configured_online(test_app)
    test_app.config["PAYMENT_QR_IMAGE_URL"] = "https://example.test/foreign.png"
    _, url = created_order(client, test_app)
    assert choose(client, url, "ONLINE").status_code == 302
    response = client.get(url)
    assert response.status_code == 200
    assert b'/payment/qr' in response.data
    assert b"foreign.png" not in response.data
    qr = client.get(url + "/payment/qr")
    assert qr.status_code == 200 and qr.mimetype == "image/png"
    assert qr.data.startswith(b"\x89PNG")
    assert b"Use the example transfer destination below" in response.data


def test_payment_summary_and_normalized_reference_keep_stored_amount(client, test_app):
    configured_online(test_app)
    _, url = created_order(client, test_app)
    assert choose(client, url, "ONLINE").status_code == 302
    pending = client.get(url)
    for expected in (b"Payment summary", b"Order items", b"Campus Prints",
                     b"Fulfillment:", b"Subtotal: PHP 6.75", b"Total: PHP 6.75"):
        assert expected in pending.data
    assert submit(client, url, "  DEMO   REF-123  ", amount="0.01", payment_status="PAID").status_code == 302
    submitted = client.get(url)
    assert b"Payment reference submitted" in submitted.data
    assert b"awaiting verification" in submitted.data
    assert b"Submitted reference: DEMO REF-123" in submitted.data
    assert b"Payment submitted" in submitted.data
    assert b"Payment successful" not in submitted.data
    history = client.get("/orders")
    assert b"Awaiting payment verification" in history.data
    with test_app.app_context():
        payment = db.session.scalar(select(Payment))
        assert payment.payment_reference == "DEMO REF-123"
        assert payment.amount == payment.order.total == Decimal("6.75")
        assert payment.payment_status == PaymentStatus.SUBMITTED
        assert payment.order.status == OrderStatus.PENDING_PAYMENT


def test_payment_ownership_authentication_csrf_and_no_verification_route(client, test_app):
    configured_online(test_app)
    owner, url = created_order(client, test_app)
    other = student(test_app, "other@example.edu")
    staff = student(test_app, "staff@example.edu", role=UserRole.SHOP_STAFF)
    sign_in(client, other)
    assert client.get(url).status_code == 404
    assert choose(client, url, "ONLINE").status_code == 404
    assert submit(client, url, "DEMO-REF-1234").status_code == 404
    sign_in(client, staff)
    assert choose(client, url, "ONSITE").status_code == 403
    sign_in(client, owner)
    assert client.post(url + "/payment", data={"payment_method": "ONLINE"}).status_code == 400
    assert client.post(url + "/payment/submit", data={"payment_reference": "DEMO-REF-1234"}).status_code == 400
    assert client.post(url + "/payment/verify", data={
        "csrf_token": token(client.get(url)), "payment_status": "PAID",
    }).status_code == 404
    with test_app.app_context():
        assert db.session.scalar(select(Payment)) is None


def test_payment_service_rechecks_ownership_and_state(client, test_app):
    configured_online(test_app)
    owner, url = created_order(client, test_app)
    other = student(test_app, "other@example.edu")
    reference = url.rsplit("/", 1)[1]
    with test_app.app_context():
        with pytest.raises(PaymentError) as error:
            select_payment_method(order_reference=reference, user_id=other, method="ONLINE")
        assert error.value.status_code == 404
        with pytest.raises(PaymentError):
            select_payment_method(order_reference=reference, user_id=owner, method="WIRE")
        payment = select_payment_method(order_reference=reference, user_id=owner, method="ONLINE")
        assert payment.payment_status == PaymentStatus.PENDING
        with pytest.raises(PaymentError) as error:
            submit_online_reference(order_reference=reference, user_id=other, reference="DEMO-REF-1234")
        assert error.value.status_code == 404
        payment = submit_online_reference(
            order_reference=reference, user_id=owner, reference="DEMO-REF-1234"
        )
        assert payment.payment_status == PaymentStatus.SUBMITTED
        with pytest.raises(PaymentError) as error:
            select_payment_method(order_reference=reference, user_id=owner, method="ONSITE")
        assert error.value.status_code == 409


def test_payment_database_constraints(client, test_app):
    _, url = created_order(client, test_app)
    assert choose(client, url, "ONSITE").status_code == 302
    with test_app.app_context():
        payment = db.session.scalar(select(Payment))
        assert payment.order.payment is payment
        file_id = payment.order.items[0].uploaded_file_id
        shop_id = payment.order.shop_id
        duplicate = Payment(
            order_id=payment.order_id, payment_method=PaymentMethod.ONSITE,
            payment_status=PaymentStatus.PENDING, amount=payment.amount,
            currency=payment.currency,
        )
        db.session.add(duplicate)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
    assert review(client, file_id, shop_id).status_code == 200
    second_url = place(client, file_id, shop_id).headers["Location"]
    second_reference = second_url.rsplit("/", 1)[1]
    with test_app.app_context():
        second_id = db.session.scalar(select(Order.id).where(Order.order_reference == second_reference))
        for method, status, amount, reference in (
            ("WIRE", "PENDING", 1, None),
            ("ONSITE", "VERIFIED", 1, None),
            ("ONSITE", "PENDING", -1, None),
            ("ONSITE", "SUBMITTED", 1, None),
        ):
            with pytest.raises(IntegrityError):
                db.session.execute(text("""
                    INSERT INTO payments
                        (order_id, payment_method, payment_status, amount, currency,
                         payment_reference, created_at, updated_at)
                    VALUES (:order_id, :method, :status, :amount, 'PHP',
                            :reference, '2026-10-03', '2026-10-03')
                """), {
                    "order_id": second_id, "method": method, "status": status,
                    "amount": amount, "reference": reference,
                })
            db.session.rollback()
