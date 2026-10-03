"""Stage 8 confirmation and read-only tracking from authoritative records."""

from flask import g
from sqlalchemy import select

from app.extensions import db
from app.models import Order, Payment, Professor
from app.services.tracking import build_tracking
from test_orders import (
    approved_professor, file, offer_professor_service, place, professor_place,
    professor_review, review, shop, sign_in, student, token,
)
from test_payments import choose, configured_online, created_order, submit


def test_new_order_confirmation_and_timeline_without_payment(client, test_app):
    _, url = created_order(client, test_app)
    response = client.get(url)
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        reference = order.order_reference
        created = order.created_at.isoformat()
        total = str(order.total)
        tracking = build_tracking(order)
        assert tracking.payment_method == "Not selected"
        assert tracking.payment_status == "Not started"
        assert tracking.steps[0].timestamp == order.created_at
        assert tracking.steps[1].timestamp is None
        assert tracking.steps[2].timestamp is None
    assert response.status_code == 200
    assert b"Your order was created successfully." in response.data
    assert f"Order reference: {reference}".encode() in response.data
    assert f"Order total: PHP {total}".encode() in response.data
    assert b"Payment not selected" in response.data
    assert b"Payment not selected" in response.data
    assert b"Awaiting payment" in response.data
    assert b"Choose online or onsite payment for this order" in response.data
    assert b"Order tracking" in response.data
    assert b"Order created" in response.data
    assert b"No payment method has been selected" in response.data
    assert b"Current order status" in response.data
    assert response.data.count(b"<time ") == 1
    assert f'datetime="{created}"'.encode() in response.data
    assert b"Payment successful" not in response.data
    assert b"Ready for pickup" not in response.data
    assert b"Out for delivery" not in response.data


def test_online_tracking_changes_only_with_recorded_payment(client, test_app):
    configured_online(test_app)
    _, url = created_order(client, test_app)
    assert choose(client, url, "ONLINE").status_code == 302
    pending = client.get(url)
    with test_app.app_context():
        payment = db.session.scalar(select(Payment))
        selected_at = payment.updated_at.isoformat()
        assert build_tracking(payment.order).steps[1].timestamp == payment.updated_at
    assert b"Payment method: <strong>Online</strong>" in pending.data
    assert b"Payment pending" in pending.data
    assert b"no reference submitted" in pending.data
    assert b"submit your payment reference" in pending.data
    assert pending.data.count(b"<time ") == 2
    assert f'datetime="{selected_at}"'.encode() in pending.data

    assert submit(client, url, "DEMO-REF-1234").status_code == 302
    submitted = client.get(url)
    with test_app.app_context():
        payment = db.session.scalar(select(Payment))
        submitted_at = payment.updated_at.isoformat()
        assert build_tracking(payment.order).steps[1].timestamp == payment.updated_at
        assert payment.order.status.value == "PENDING_PAYMENT"
    assert b"Payment method: <strong>Online</strong>" in submitted.data
    assert b"Payment submitted" in submitted.data
    assert b"Payment submitted for verification" in submitted.data
    assert b"awaiting manual verification" in submitted.data
    assert b"Submitted reference: DEMO-REF-1234" in submitted.data
    assert b"Shop processing has not started" in submitted.data
    assert f'datetime="{submitted_at}"'.encode() in submitted.data
    assert b"Payment successful" not in submitted.data
    assert b"Payment verified" not in submitted.data
    assert b"Order printed" not in submitted.data
    assert client.get(url).status_code == 200
    with test_app.app_context():
        assert len(db.session.scalars(select(Order)).all()) == 1
        assert len(db.session.scalars(select(Payment)).all()) == 1


def test_onsite_confirmation_and_tracking_remain_pending(client, test_app):
    configured_online(test_app)
    _, url = created_order(client, test_app)
    assert choose(client, url, "ONSITE").status_code == 302
    response = client.get(url)
    with test_app.app_context():
        payment = db.session.scalar(select(Payment))
        selected_at = payment.updated_at.isoformat()
        assert build_tracking(payment.order).steps[1].timestamp == payment.updated_at
    assert b"Payment method: <strong>Onsite</strong>" in response.data
    assert b"Payment pending" in response.data
    assert b"Payment will be made onsite" in response.data
    assert b"Pay at the shop counter" in response.data
    assert b"Onsite payment selected; payment is pending" in response.data
    assert b"Payment is pending" in response.data
    assert f'datetime="{selected_at}"'.encode() in response.data
    assert b"Payment successful" not in response.data


def test_pending_method_change_tracks_current_recorded_method(client, test_app):
    configured_online(test_app)
    _, url = created_order(client, test_app)
    assert choose(client, url, "ONSITE").status_code == 302
    with test_app.app_context():
        first_updated_at = db.session.scalar(select(Payment)).updated_at
    assert choose(client, url, "ONLINE").status_code == 302
    with test_app.app_context():
        payment = db.session.scalar(select(Payment))
        tracking = build_tracking(payment.order)
        assert tracking.steps[1].timestamp == payment.updated_at
        assert payment.updated_at >= first_updated_at
        assert "Online payment method selected" in tracking.steps[1].detail
    response = client.get(url)
    assert b"Payment method: <strong>Online</strong>" in response.data
    assert b"Onsite payment selected" not in response.data


def test_professor_snapshot_and_print_details_remain_visible(client, test_app):
    user_id = student(test_app)
    shop_id = shop(test_app)
    file_id = file(test_app, user_id, name="private-lecture.pdf")
    offer_professor_service(test_app, shop_id)
    professor_id = approved_professor(test_app)
    sign_in(client, user_id)
    assert professor_review(client, file_id, shop_id, professor_id).status_code == 200
    url = professor_place(client, file_id, shop_id, professor_id).headers["Location"]
    with test_app.app_context():
        db.session.get(Professor, professor_id).name = "Changed Profile"
        db.session.commit()
    response = client.get(url)
    assert response.status_code == 200
    assert b"Intended recipient: <strong>Maria Santos</strong>" in response.data
    assert b"Computer Engineering" in response.data
    assert b"Engineering Building 204" in response.data
    assert b"maria.santos@example.edu" in response.data
    assert b"private-lecture.pdf" in response.data
    assert b"Grayscale" in response.data
    assert b"A4" in response.data
    assert b"Subtotal: PHP 6.75" in response.data
    assert b"Fees total: PHP 0.00" in response.data
    assert b"No file is sent electronically" in response.data


def test_tracking_inherits_order_ownership_and_avoids_internal_data(client, test_app):
    configured_online(test_app)
    owner, url = created_order(client, test_app)
    assert choose(client, url, "ONLINE").status_code == 302
    assert submit(client, url, "PRIVATE-REF-1234").status_code == 302
    with test_app.app_context():
        storage_key = db.session.scalar(select(Order)).items[0].uploaded_file.storage_key
    owner_page = client.get(url)
    assert b"PRIVATE-REF-1234" in owner_page.data
    assert storage_key.encode() not in owner_page.data
    assert b'name="order_id"' not in owner_page.data
    assert b"instance/uploads" not in owner_page.data

    other = student(test_app, "other@example.edu")
    sign_in(client, other)
    response = client.get(url)
    assert response.status_code == 404
    assert b"PRIVATE-REF-1234" not in response.data
    assert b"Order tracking" not in response.data
    sign_in(client, owner)
    assert client.get(url).status_code == 200
    g.pop("_login_user", None)
    response = test_app.test_client().get(url)
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_professor_validation_error_still_renders_tracking(client, test_app):
    user_id = student(test_app)
    shop_id = shop(test_app)
    file_id = file(test_app, user_id)
    offer_professor_service(test_app, shop_id)
    professor_id = approved_professor(test_app)
    sign_in(client, user_id)
    assert review(client, file_id, shop_id).status_code == 200
    url = place(client, file_id, shop_id).headers["Location"]
    response = client.post(url + "/professor", data={
        "csrf_token": token(client.get(url)), "professor_id": str(professor_id + 999),
    })
    assert response.status_code == 400
    assert b"Order tracking" in response.data
    assert b"Payment not selected" in response.data
