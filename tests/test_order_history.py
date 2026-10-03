"""Stage 11 student-only history from existing order snapshots."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.extensions import db
from app.models import (
    Order, OrderStatus, Payment, PaymentMethod, PaymentStatus, PrintPrice, PrintingShop,
    Professor, UploadedFile, UserRole,
)
from test_orders import (
    approved_professor, file, offer_professor_service, place, professor_place,
    professor_review, review, shop, sign_in, student,
)
from test_payments import choose, configured_online, submit


def test_empty_history_and_role_boundaries(client, test_app):
    assert client.get("/orders").status_code == 302
    assert client.get("/orders/POD-NO-ORDER").status_code == 302
    owner = student(test_app)
    staff = student(test_app, "staff@example.edu", UserRole.SHOP_STAFF)
    admin = student(test_app, "admin@example.edu", UserRole.ADMIN)
    sign_in(client, owner)
    page = client.get("/orders")
    assert page.status_code == 200
    assert b"No orders yet" in page.data
    assert b"Browse printing shops" in page.data
    assert b"Order History" in client.get("/student").data
    assert b'href="/orders"' in client.get("/student").data
    for actor, home in ((staff, "/shop"), (admin, "/admin")):
        sign_in(client, actor)
        assert client.get("/orders").status_code == 403
        assert client.get("/orders/POD-NO-ORDER").status_code == 403
        assert b'href="/orders"' not in client.get(home).data


def test_history_is_owner_scoped_newest_first_and_payment_truthful(client, test_app):
    configured_online(test_app)
    owner = student(test_app)
    stranger = student(test_app, "stranger@example.edu")
    shop_id = shop(test_app)
    first_file = file(test_app, owner, name="first.pdf")
    second_file = file(test_app, owner, name="second.pdf")
    foreign_file = file(test_app, stranger, name="secret.pdf")
    sign_in(client, owner)
    assert review(client, first_file, shop_id).status_code == 200
    first_url = place(client, first_file, shop_id).headers["Location"]
    assert review(client, second_file, shop_id).status_code == 200
    second_url = place(client, second_file, shop_id).headers["Location"]
    assert choose(client, second_url, "ONLINE").status_code == 302
    assert submit(client, second_url, "REF-SECOND-123").status_code == 302
    sign_in(client, stranger)
    assert review(client, foreign_file, shop_id).status_code == 200
    foreign_url = place(client, foreign_file, shop_id).headers["Location"]
    with test_app.app_context():
        first = db.session.scalar(select(Order).where(Order.order_reference == first_url.rsplit("/", 1)[1]))
        second = db.session.scalar(select(Order).where(Order.order_reference == second_url.rsplit("/", 1)[1]))
        first.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        second.created_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
        db.session.commit()
        second_ref = second.order_reference
        first_ref = first.order_reference
        foreign_ref = foreign_url.rsplit("/", 1)[1]
    sign_in(client, owner)
    listing = client.get("/orders")
    assert listing.status_code == 200
    assert listing.data.index(second_ref.encode()) < listing.data.index(first_ref.encode())
    assert foreign_ref.encode() not in listing.data
    assert b"Campus Prints" in listing.data
    assert b"PHP 6.75" in listing.data
    assert b"PENDING_PAYMENT" in listing.data
    assert b"SUBMITTED (awaiting verification)" in listing.data
    assert b"Not selected" in listing.data
    assert b"REF-SECOND-123" not in listing.data
    assert client.get(first_url).status_code == 200
    assert b"Order tracking" in client.get(second_url).data
    assert client.get(foreign_url).status_code == 404
    assert client.get(f"/orders/{foreign_ref}/payment").status_code in {404, 405}
    assert b"Order History" in client.get(first_url).data

    submitted = client.get("/orders?payment_status=SUBMITTED")
    assert second_ref.encode() in submitted.data and first_ref.encode() not in submitted.data
    missing = client.get("/orders?payment_status=NONE")
    assert first_ref.encode() in missing.data and second_ref.encode() not in missing.data
    assert b"No orders match" in client.get("/orders?status=COMPLETED").data
    assert client.get("/orders?status=UNKNOWN").status_code == 400
    assert client.get("/orders?payment_status=PAID%27").status_code == 400
    assert client.get("/orders?page=0").status_code == 400
    assert client.get("/orders?page=abc").status_code == 400
    with test_app.app_context():
        payment = db.session.scalar(select(Payment))
        assert payment.payment_status == PaymentStatus.SUBMITTED
        assert payment.order.status == OrderStatus.PENDING_PAYMENT


def test_old_shop_price_and_professor_snapshots_remain_visible(client, test_app):
    owner = student(test_app)
    shop_id = shop(test_app)
    file_id = file(test_app, owner, name="lecture.pdf")
    offer_professor_service(test_app, shop_id)
    professor_id = approved_professor(test_app)
    sign_in(client, owner)
    assert professor_review(client, file_id, shop_id, professor_id).status_code == 200
    detail_url = professor_place(client, file_id, shop_id, professor_id).headers["Location"]
    with test_app.app_context():
        storage_key = db.session.get(UploadedFile, file_id).storage_key
        db.session.get(PrintingShop, shop_id).is_active = False
        db.session.get(PrintingShop, shop_id).name = "Renamed Inactive Shop"
        rate = db.session.scalar(select(PrintPrice))
        rate.price = Decimal("99.00")
        professor = db.session.get(Professor, professor_id)
        professor.name = "Changed Name"
        professor.email = "changed@example.edu"
        professor.is_active = False
        professor.direct_send_approved = False
        db.session.commit()
    assert client.get(f"/shops/{shop_id}").status_code == 404
    listing = client.get("/orders")
    assert listing.status_code == 200
    assert b"Campus Prints" in listing.data and b"Renamed Inactive Shop" not in listing.data
    assert b"PHP 6.75" in listing.data and b"PHP 297.00" not in listing.data
    assert b"Direct-to-Professor: Maria Santos" in listing.data
    assert b"Changed Name" not in listing.data
    assert storage_key.encode() not in listing.data
    detail = client.get(detail_url)
    assert detail.status_code == 200
    assert b"maria.santos@example.edu" in detail.data
    assert b"Changed Name" not in detail.data
    assert b"lecture.pdf" in detail.data
    assert b"Grayscale" in detail.data
    assert b"Order tracking" in detail.data
    assert storage_key.encode() not in detail.data


def test_history_paginates_only_the_owner_orders(client, test_app):
    owner = student(test_app)
    stranger = student(test_app, "stranger@example.edu")
    shop_id = shop(test_app)
    with test_app.app_context():
        for index in range(23):
            db.session.add(Order(
                user_id=owner, shop_id=shop_id, shop_name="Campus Prints",
                order_reference=f"POD-2026-HISTORY{index:04d}",
                subtotal=Decimal("1.00"), fees_total=Decimal("0.00"),
                total=Decimal("1.00"), currency="PHP",
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index),
            ))
        db.session.add(Order(
            user_id=stranger, shop_id=shop_id, shop_name="Secret Shop",
            order_reference="POD-2026-STRANGER", subtotal=Decimal("999.00"),
            fees_total=Decimal("0.00"), total=Decimal("999.00"), currency="PHP",
        ))
        db.session.commit()
    sign_in(client, owner)
    first = client.get("/orders")
    second = client.get("/orders?page=2")
    assert first.status_code == second.status_code == 200
    assert first.data.count(b'<th scope="row">') == 20
    assert second.data.count(b'<th scope="row">') == 3
    assert b"POD-2026-HISTORY0022" in first.data
    assert b"POD-2026-HISTORY0000" in second.data
    assert b"POD-2026-STRANGER" not in first.data + second.data
    assert b"Previous" in second.data and b"Next" in first.data
    assert b"Page 1 of 2" in first.data and b"Page 2 of 2" in second.data


def test_recorded_completed_and_paid_state_appears_without_new_events(client, test_app):
    owner = student(test_app)
    shop_id = shop(test_app)
    with test_app.app_context():
        at = datetime(2026, 1, 3, tzinfo=timezone.utc)
        order = Order(
            user_id=owner, shop_id=shop_id, shop_name="Campus Prints",
            order_reference="POD-2026-PAIDCOMPLETE", status=OrderStatus.COMPLETED,
            subtotal=Decimal("6.75"), fees_total=Decimal("0.00"),
            total=Decimal("6.75"), currency="PHP", created_at=at,
            processing_started_at=at + timedelta(hours=1),
            ready_at=at + timedelta(hours=2), completed_at=at + timedelta(hours=3),
        )
        db.session.add(order)
        db.session.flush()
        db.session.add(Payment(
            order_id=order.id, payment_method=PaymentMethod.ONSITE,
            payment_status=PaymentStatus.PAID, amount=order.total, currency="PHP",
        ))
        db.session.commit()
    sign_in(client, owner)
    listing = client.get("/orders?status=COMPLETED&payment_status=PAID")
    assert listing.status_code == 200
    assert b"POD-2026-PAIDCOMPLETE" in listing.data
    assert b"COMPLETED" in listing.data and b"PAID" in listing.data
    detail = client.get("/orders/POD-2026-PAIDCOMPLETE")
    assert b"Processing started" in detail.data
    assert b"Order ready" in detail.data
    assert b"Order completed" in detail.data
    assert b"Shop processing is reflected" in detail.data
