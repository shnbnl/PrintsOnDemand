"""Stage 5 checkout, pricing, snapshots, authorization, and persistence."""

import hashlib
import re
from io import BytesIO
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal
from pathlib import Path

import pytest
from flask import g
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from pypdf import PdfWriter

from app.extensions import db
from app.models import (
    ColorMode, FeeType, Order, OrderDestination, OrderItem, OrderStatus, PaperSize,
    PrintConfiguration, PrintPrice, PrintingShop, ServiceType, ShopFee,
    ShopService, UploadedFile, User, UserRole, Professor, ProfessorVerificationStatus,
)
from app.services.pricing import PricingError, quote_order
from app.services.orders import create_order
from app.services.professors import ProfessorSelectionError
from app.storage import LocalStorage


def pdf_bytes(page_count=1):
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=612, height=792)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


PDF = pdf_bytes()
PASSWORD = "A-strong-password-123"


def token(response):
    found = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', response.data)
    assert found
    return found.group(1).decode()


def student(app, email="student@example.com", role=UserRole.STUDENT):
    with app.app_context():
        user = User(name=email, email=email, role=role)
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.commit()
        return user.id


def sign_in(client, user_id):
    with client.session_transaction() as state:
        state["_user_id"] = str(user_id)
        state["_fresh"] = True
    g.pop("_login_user", None)


def shop(app, *, name="Campus Prints", active=True, price="2.25", rush=False, rush_fee="5.50"):
    with app.app_context():
        online = app.config.get("_TEST_SHOP_ONLINE_DEFAULTS")
        record = PrintingShop(
            name=name, address="Campus Road", opening_time=time(9),
            closing_time=time(17), is_active=active,
            online_enabled=bool(online),
            online_account_name=online["account_name"] if online else "",
            online_account_reference=online["reference"] if online else "",
            online_instructions=online["instructions"] if online else "",
        )
        db.session.add(record)
        db.session.flush()
        db.session.add(ShopService(
            shop_id=record.id, service_type=ServiceType.PICKUP, enabled=True,
        ))
        if price is not None:
            db.session.add(PrintPrice(
                shop_id=record.id, paper_size=PaperSize.A4,
                color_mode=ColorMode.GRAYSCALE, price=Decimal(price),
            ))
        if rush:
            db.session.add(ShopService(
                shop_id=record.id, service_type=ServiceType.RUSH_PRINTING, enabled=True,
            ))
            if rush_fee is not None:
                db.session.add(ShopFee(
                    shop_id=record.id, fee_type=FeeType.RUSH_PRINTING,
                    amount=Decimal(rush_fee),
                ))
        db.session.commit()
        return record.id


def file(app, user_id, *, name="notes.pdf", configured=True, quantity=3, rush=False):
    with app.app_context():
        key = LocalStorage(app.config["UPLOAD_STORAGE_ROOT"], app.static_folder).save(PDF, "pdf")
        record = UploadedFile(
            user_id=user_id, original_filename=name, stored_filename=key,
            storage_key=key, mime_type="application/pdf", file_extension="pdf",
            file_size=len(PDF), sha256=hashlib.sha256(PDF).hexdigest(),
            pdf_page_count=1,
        )
        db.session.add(record)
        db.session.flush()
        if configured:
            db.session.add(PrintConfiguration(
                file_id=record.id, paper_size=PaperSize.A4,
                color_mode=ColorMode.GRAYSCALE, quantity=quantity, is_rush=rush,
            ))
        db.session.commit()
        return record.id


def review(client, file_id, shop_id):
    return client.get("/orders/new", query_string={
        "file_id": file_id, "shop_id": shop_id, **pickup_fields(),
    })


def pickup_fields():
    return {
        "destination": "PICKUP",
        "pickup_date": (datetime.now(ZoneInfo("Asia/Manila")).date() + timedelta(days=3)).isoformat(),
        "pickup_slot": "14:00-15:00",
    }


def place(client, file_id, shop_id, **extras):
    return client.post("/orders/create", data={
        "csrf_token": token(client.get("/student")),
        "file_id": str(file_id), "shop_id": str(shop_id),
        **(pickup_fields() if "destination" not in extras else {}), **extras,
    })


def approved_professor(app, *, active=True, approved=True, accepts=True, faculty="MITL", name="Maria Santos", linked=True):
    with app.app_context():
        professor = Professor(
            name=name, email=f"{name.lower().replace(' ', '.')}@example.edu",
            department="Computer Engineering", office="Engineering Building 204",
            is_active=active, direct_send_approved=approved,
            accepts_student_deliveries=accepts,
            faculty=faculty,
        )
        db.session.add(professor)
        if linked:
            account = User(
                name=name, email=professor.email, role=UserRole.PROFESSOR,
                professor=professor, professor_department=faculty,
                professor_verification_status=ProfessorVerificationStatus.VERIFIED,
            )
            account.set_password(PASSWORD)
            db.session.add(account)
        db.session.commit()
        return professor.id


def offer_professor_service(app, shop_id, *, enabled=True):
    with app.app_context():
        record = db.session.get(PrintingShop, shop_id)
        if record.name == "Campus Prints":
            record.name = "Blue and Silver Bookstore"
        service = db.session.scalar(select(ShopService).where(
            ShopService.shop_id == shop_id,
            ShopService.service_type == ServiceType.DIRECT_TO_PROFESSOR,
        ))
        if service is None:
            db.session.add(ShopService(
                shop_id=shop_id, service_type=ServiceType.DIRECT_TO_PROFESSOR,
                enabled=enabled,
            ))
        else:
            service.enabled = enabled
        db.session.commit()


def professor_review(client, file_id, shop_id, professor_id):
    return client.get("/orders/new", query_string={
        "file_id": file_id, "shop_id": shop_id,
        "destination": "PROFESSOR", "professor_id": professor_id,
    })


def professor_place(client, file_id, shop_id, professor_id, **extras):
    return place(client, file_id, shop_id, destination="PROFESSOR",
                 professor_id=str(professor_id), **extras)


def test_professor_checkout_review_confirmation_and_snapshot(client, test_app):
    user_id = student(test_app)
    shop_id = shop(test_app)
    file_id = file(test_app, user_id)
    offer_professor_service(test_app, shop_id)
    professor_id = approved_professor(test_app)
    approved_professor(test_app, approved=False, name="Ana Reyes")
    approved_professor(test_app, active=False, name="Liza Navarro")
    sign_in(client, user_id)
    selection = client.get("/orders/new")
    assert b"Deliver to Professor" in selection.data
    assert b"Maria Santos" in selection.data
    assert b"Ana Reyes" not in selection.data
    assert b"Liza Navarro" not in selection.data
    reviewed = professor_review(client, file_id, shop_id, professor_id)
    assert reviewed.status_code == 200
    assert b"Computer Engineering" in reviewed.data
    assert b"Engineering Building 204" in reviewed.data
    assert b"maria.santos@example.edu" in reviewed.data
    response = professor_place(
        client, file_id, shop_id, professor_id,
        professor_email="attacker@example.edu", total="0.01", status="PAID",
    )
    assert response.status_code == 302
    confirmation = client.get(response.headers["Location"])
    assert confirmation.status_code == 200
    assert b"Intended recipient" in confirmation.data
    assert b"Maria Santos" in confirmation.data
    assert b"maria.santos@example.edu" in confirmation.data
    assert b"PENDING_PAYMENT" in confirmation.data
    assert b"No file is sent electronically" in confirmation.data
    assert b"Payment is pending" in confirmation.data
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert order.destination == OrderDestination.PROFESSOR
        assert order.professor_id == professor_id
        assert order.professor_name == "Maria Santos"
        assert order.professor_email == "maria.santos@example.edu"
        assert order.professor_department == "Computer Engineering"
        assert order.professor_office == "Engineering Building 204"
        assert order.status == OrderStatus.PENDING_PAYMENT
        assert order.total == Decimal("6.75")
        assert order.items[0].unit_price == Decimal("2.25")
        db.session.get(Professor, professor_id).name = "Changed Later"
        db.session.commit()
    assert b"Maria Santos" in client.get(response.headers["Location"]).data


@pytest.mark.parametrize("invalid", ["999999", "0", "not-an-id", "-1", str(2**63)])
def test_invalid_professor_id_never_creates_order(client, test_app, invalid):
    user_id = student(test_app)
    shop_id = shop(test_app)
    file_id = file(test_app, user_id)
    offer_professor_service(test_app, shop_id)
    sign_in(client, user_id)
    assert professor_review(client, file_id, shop_id, invalid).status_code == 400
    assert professor_place(client, file_id, shop_id, invalid).status_code == 400
    with test_app.app_context():
        assert db.session.scalar(select(Order)) is None


@pytest.mark.parametrize("active,approved", [(True, False), (False, True), (False, False)])
def test_ineligible_professor_rejected_at_review_and_placement(client, test_app, active, approved):
    user_id = student(test_app)
    shop_id = shop(test_app)
    file_id = file(test_app, user_id)
    offer_professor_service(test_app, shop_id)
    professor_id = approved_professor(test_app, active=active, approved=approved)
    sign_in(client, user_id)
    assert professor_review(client, file_id, shop_id, professor_id).status_code == 400
    assert professor_place(client, file_id, shop_id, professor_id).status_code == 400
    with test_app.app_context():
        assert db.session.scalar(select(Order)) is None


def test_professor_rechecked_after_review_and_in_order_service(client, test_app):
    user_id = student(test_app)
    shop_id = shop(test_app)
    file_id = file(test_app, user_id)
    offer_professor_service(test_app, shop_id)
    professor_id = approved_professor(test_app)
    sign_in(client, user_id)
    assert professor_review(client, file_id, shop_id, professor_id).status_code == 200
    with test_app.app_context():
        db.session.get(Professor, professor_id).direct_send_approved = False
        db.session.commit()
    assert professor_place(client, file_id, shop_id, professor_id).status_code == 400
    with test_app.app_context():
        assert db.session.scalar(select(Order)) is None
        db.session.get(Professor, professor_id).direct_send_approved = True
        db.session.commit()
    assert professor_review(client, file_id, shop_id, professor_id).status_code == 200
    with test_app.app_context():
        db.session.get(Professor, professor_id).office = "New Room"
        db.session.commit()
    changed = professor_place(client, file_id, shop_id, professor_id)
    assert changed.status_code == 409
    assert b"New Room" in changed.data
    assert professor_place(client, file_id, shop_id, professor_id).status_code == 302


def test_order_service_independently_rejects_revoked_professor(test_app):
    user_id = student(test_app)
    shop_id = shop(test_app)
    file_id = file(test_app, user_id)
    offer_professor_service(test_app, shop_id)
    professor_id = approved_professor(test_app)
    with test_app.app_context():
        quote = quote_order(user_id=user_id, file_id=file_id, shop_id=shop_id, max_quantity=999)
        db.session.get(Professor, professor_id).direct_send_approved = False
        db.session.commit()
        with pytest.raises(ProfessorSelectionError):
            create_order(quote, destination="PROFESSOR", professor_id=professor_id)
        assert db.session.scalar(select(Order)) is None


def test_changing_professor_after_review_requires_new_confirmation(client, test_app):
    user_id = student(test_app)
    shop_id = shop(test_app)
    file_id = file(test_app, user_id)
    offer_professor_service(test_app, shop_id)
    maria_id = approved_professor(test_app)
    juan_id = approved_professor(test_app, name="Juan Dela Cruz")
    sign_in(client, user_id)
    assert professor_review(client, file_id, shop_id, maria_id).status_code == 200
    response = professor_place(client, file_id, shop_id, juan_id)
    assert response.status_code == 409
    assert b"Juan Dela Cruz" in response.data
    with test_app.app_context():
        assert db.session.scalar(select(Order)) is None
    assert professor_place(client, file_id, shop_id, juan_id).status_code == 302


def test_professor_requires_shop_service_and_no_future_destination(client, test_app):
    user_id = student(test_app)
    shop_id = shop(test_app)
    file_id = file(test_app, user_id)
    professor_id = approved_professor(test_app)
    sign_in(client, user_id)
    assert professor_review(client, file_id, shop_id, professor_id).status_code == 400
    offer_professor_service(test_app, shop_id, enabled=False)
    assert professor_review(client, file_id, shop_id, professor_id).status_code == 400
    offer_professor_service(test_app, shop_id, enabled=True)
    assert client.get("/orders/new", query_string={
        "file_id": file_id, "shop_id": shop_id,
        "destination": "PICKUP",
    }).status_code == 400
    with test_app.app_context():
        assert db.session.scalar(select(Order)) is None


def test_owner_can_select_professor_on_existing_order_but_other_user_cannot(client, test_app):
    owner = student(test_app)
    other = student(test_app, "other@example.edu")
    shop_id = shop(test_app)
    file_id = file(test_app, owner)
    offer_professor_service(test_app, shop_id)
    professor_id = approved_professor(test_app)
    sign_in(client, owner)
    assert review(client, file_id, shop_id).status_code == 200
    with test_app.app_context():
        legacy = create_order(quote_order(
            user_id=owner, file_id=file_id, shop_id=shop_id, max_quantity=999,
        ))
        total_before = legacy.total
        url = f"/orders/{legacy.order_reference}"
    sign_in(client, other)
    assert client.get(url).status_code == 404
    assert client.post(
        url + "/professor",
        data={"csrf_token": token(client.get("/student")), "professor_id": str(professor_id)},
    ).status_code == 404
    sign_in(client, owner)
    assert client.post(url + "/professor", data={"professor_id": str(professor_id)}).status_code == 400
    assert client.post(
        url + "/professor",
        data={"csrf_token": token(client.get(url)), "professor_id": "99999"},
    ).status_code == 400
    with test_app.app_context():
        assert db.session.scalar(select(Order)).professor_id is None
    response = client.post(
        url + "/professor",
        data={"csrf_token": token(client.get(url)), "professor_id": str(professor_id)},
    )
    assert response.status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert order.professor_id == professor_id
        assert order.destination == OrderDestination.PROFESSOR
        assert order.total == total_before
        assert order.status == OrderStatus.PENDING_PAYMENT
        db.session.get(PrintingShop, shop_id).is_active = False
        db.session.commit()
    assert client.post(
        url + "/professor",
        data={"csrf_token": token(client.get(url)), "professor_id": str(professor_id)},
    ).status_code == 400


def test_order_quote_creation_and_model_snapshots(client, test_app):
    user_id = student(test_app)
    shop_id = shop(test_app)
    file_id = file(test_app, user_id)
    sign_in(client, user_id)
    page = review(client, file_id, shop_id)
    assert page.status_code == 200
    assert b"Campus Prints" in page.data and b"notes.pdf" in page.data
    assert b"PHP 2.25" in page.data
    assert b"PHP 6.75" in page.data
    assert b"awaiting payment" in page.data
    assert b"Payment has not been completed" not in page.data
    response = place(client, file_id, shop_id, subtotal="0.01", total="0.01", unit_price="0.01", fees_total="999")
    assert response.status_code == 302
    assert re.search(r"/orders/POD-\d{4}-[0-9A-F]{12}$", response.headers["Location"])
    detail = client.get(response.headers["Location"])
    assert detail.status_code == 200
    assert b"Your order was created successfully." in detail.data
    assert b"Payment is pending" in detail.data
    assert b"PENDING_PAYMENT" in detail.data
    assert b"PHP 6.75" in detail.data
    assert b"Paid" not in detail.data
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        item = db.session.scalar(select(OrderItem))
        assert order.user_id == user_id and order.shop_id == shop_id
        assert order.shop.name == "Campus Prints" and order.user.id == user_id
        assert order.status == OrderStatus.PENDING_PAYMENT
        assert order.currency == "PHP"
        assert type(order.total) is Decimal
        assert (order.subtotal, order.fees_total, order.total) == (
            Decimal("6.75"), Decimal("0.00"), Decimal("6.75")
        )
        assert order.created_at and order.updated_at
        assert order.items == [item]
        assert item.order_id == order.id and item.uploaded_file_id == file_id
        assert item.uploaded_file.user_id == user_id
        assert item.paper_size == PaperSize.A4 and item.color_mode == ColorMode.GRAYSCALE
        assert item.quantity == 3 and item.is_rush is False
        assert item.unit_price == Decimal("2.25") and item.line_total == Decimal("6.75")
        assert type(item.unit_price) is Decimal


def test_rush_fee_is_flat_twenty_pesos(client, test_app):
    user_id = student(test_app)
    shop_id = shop(test_app, rush=True)
    file_id = file(test_app, user_id, quantity=4, rush=True)
    sign_in(client, user_id)
    page = review(client, file_id, shop_id)
    assert b"Rush printing fee: PHP 20.00" in page.data
    assert b"Subtotal: PHP 9.00" in page.data
    assert b"Total: PHP 29.00" in page.data
    assert place(client, file_id, shop_id).status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert order.rush_fee == order.fees_total == Decimal("20.00")
        assert order.subtotal == Decimal("9.00")
        assert order.total == Decimal("29.00")
        assert order.items[0].is_rush


@pytest.mark.parametrize("rush_enabled,fee,expected", [
    (False, "5.50", b"Rush printing is not offered"),
])
def test_rush_requires_service(client, test_app, rush_enabled, fee, expected):
    user_id = student(test_app)
    shop_id = shop(test_app, rush=rush_enabled, rush_fee=fee)
    file_id = file(test_app, user_id, rush=True)
    sign_in(client, user_id)
    response = review(client, file_id, shop_id)
    assert response.status_code == 400 and expected in response.data
    assert place(client, file_id, shop_id).status_code == 400
    with test_app.app_context():
        assert db.session.scalar(select(Order)) is None


def test_regular_order_does_not_add_other_fees(client, test_app):
    user_id = student(test_app)
    shop_id = shop(test_app, rush=True)
    file_id = file(test_app, user_id)
    with test_app.app_context():
        db.session.add(ShopFee(
            shop_id=shop_id, fee_type=FeeType.DELIVERY, amount=Decimal("99.00")
        ))
        db.session.commit()
    sign_in(client, user_id)
    assert review(client, file_id, shop_id).status_code == 200
    assert place(client, file_id, shop_id).status_code == 302
    with test_app.app_context():
        assert db.session.scalar(select(Order)).fees_total == Decimal("0.00")


@pytest.mark.parametrize("variant,expected_status", [
    ("missing_shop", 404), ("inactive_shop", 404),
    ("missing_file", 404), ("unconfigured", 400),
    ("oversized_file_id", 400), ("oversized_shop_id", 400),
    ("missing_price", 400), ("zero_quantity", 400),
    ("too_many", 400), ("bad_paper", 400), ("bad_color", 400),
    ("missing_bytes", 409),
])
def test_invalid_order_inputs_do_not_create_records(client, test_app, variant, expected_status):
    user_id = student(test_app)
    shop_id = shop(test_app, active=variant != "inactive_shop", price=None if variant == "missing_price" else "2.25")
    file_id = file(test_app, user_id, configured=variant != "unconfigured")
    with test_app.app_context():
        corrupt_values = {
            "zero_quantity": ("quantity", 0),
            "too_many": ("quantity", 1000),
            "bad_paper": ("paper_size", "OTHER"),
            "bad_color": ("color_mode", "OTHER"),
        }
        if variant in corrupt_values:
            column, value = corrupt_values[variant]
            # Simulate an old/corrupt row to test application validation even
            # though the current database constraints normally prevent it.
            with db.engine.begin() as connection:
                connection.exec_driver_sql("PRAGMA ignore_check_constraints = ON")
                connection.execute(
                    text(f"UPDATE print_configurations SET {column} = :value WHERE file_id = :id"),
                    {"value": value, "id": file_id},
                )
                connection.exec_driver_sql("PRAGMA ignore_check_constraints = OFF")
            db.session.expire_all()
        if variant == "missing_bytes":
            key = db.session.get(UploadedFile, file_id).storage_key
            Path(test_app.config["UPLOAD_STORAGE_ROOT"], key).unlink()
    if variant == "missing_shop":
        shop_id = 9999
    if variant == "missing_file":
        file_id = 9999
    if variant == "oversized_file_id":
        file_id = 2**63
    if variant == "oversized_shop_id":
        shop_id = 2**63
    sign_in(client, user_id)
    assert review(client, file_id, shop_id).status_code == expected_status
    assert place(client, file_id, shop_id).status_code == expected_status
    with test_app.app_context():
        assert db.session.scalar(select(Order)) is None
        assert db.session.scalar(select(OrderItem)) is None


def test_cross_user_and_role_access(client, test_app):
    first = student(test_app)
    second = student(test_app, "second@example.com")
    staff = student(test_app, "staff@example.com", UserRole.SHOP_STAFF)
    shop_id = shop(test_app)
    file_id = file(test_app, first)
    assert client.get("/orders/new").status_code == 302
    assert client.get("/orders/POD-2026-ABCDEF123456").status_code == 302
    sign_in(client, first)
    review(client, file_id, shop_id)
    reference = place(client, file_id, shop_id).headers["Location"].rsplit("/", 1)[1]
    sign_in(client, second)
    assert review(client, file_id, shop_id).status_code == 404
    assert place(client, file_id, shop_id).status_code == 404
    assert client.get(f"/orders/{reference}").status_code == 404
    sign_in(client, staff)
    assert client.get("/orders/new").status_code == 403
    assert client.get(f"/orders/{reference}").status_code == 403
    assert place(client, file_id, shop_id).status_code == 403


def test_review_required_and_price_change_requires_new_confirmation(client, test_app):
    user_id = student(test_app)
    shop_id = shop(test_app)
    file_id = file(test_app, user_id)
    sign_in(client, user_id)
    first = place(client, file_id, shop_id)
    assert first.status_code == 409
    with test_app.app_context():
        assert db.session.scalar(select(Order)) is None
    assert review(client, file_id, shop_id).status_code == 200
    with test_app.app_context():
        rate = db.session.scalar(select(PrintPrice))
        rate.price = Decimal("3.00")
        db.session.commit()
    changed = place(client, file_id, shop_id)
    assert changed.status_code == 409
    assert b"The order or price changed" in changed.data
    assert b"PHP 9.00" in changed.data
    with test_app.app_context():
        assert db.session.scalar(select(Order)) is None
    assert place(client, file_id, shop_id).status_code == 302
    with test_app.app_context():
        assert db.session.scalar(select(Order)).total == Decimal("9.00")
    assert place(client, file_id, shop_id).status_code == 409


def test_historical_snapshot_and_intentional_reprint(client, test_app):
    user_id = student(test_app)
    shop_id = shop(test_app)
    file_id = file(test_app, user_id)
    sign_in(client, user_id)
    review(client, file_id, shop_id)
    first_url = place(client, file_id, shop_id).headers["Location"]
    with test_app.app_context():
        db.session.scalar(select(PrintPrice)).price = Decimal("3.00")
        db.session.get(PrintingShop, shop_id).name = "Renamed Shop"
        config = db.session.scalar(select(PrintConfiguration))
        config.quantity = 2
        db.session.commit()
    old = client.get(first_url)
    assert b"Campus Prints" in old.data
    assert b"PHP 2.25" in old.data and b"PHP 6.75" in old.data
    assert b"Renamed Shop" not in old.data
    assert review(client, file_id, shop_id).status_code == 200
    second_url = place(client, file_id, shop_id).headers["Location"]
    assert first_url != second_url
    with test_app.app_context():
        orders = db.session.scalars(select(Order).order_by(Order.id)).all()
        assert len(orders) == 2
        assert orders[0].items[0].unit_price == Decimal("2.25")
        assert orders[0].items[0].quantity == 3
        assert orders[1].items[0].unit_price == Decimal("3.00")
        assert orders[1].items[0].quantity == 2
        assert orders[0].items[0].uploaded_file_id == orders[1].items[0].uploaded_file_id
    response = client.post(
        f"/files/{file_id}/delete",
        data={"csrf_token": token(client.get(f"/files/{file_id}"))},
    )
    assert response.status_code == 409
    with test_app.app_context():
        assert db.session.get(UploadedFile, file_id) is not None


def test_unique_reference_collision_retries_without_partial_order(client, test_app, monkeypatch):
    user_id = student(test_app)
    shop_id = shop(test_app)
    file_id = file(test_app, user_id)
    sign_in(client, user_id)
    with test_app.app_context():
        existing = Order(
            user_id=user_id, shop_id=shop_id,
            order_reference="POD-2026-AAAAAAAAAAAA", shop_name="Campus Prints",
            subtotal=Decimal("0.00"), fees_total=Decimal("0.00"),
            total=Decimal("0.00"), currency="PHP",
        )
        db.session.add(existing)
        db.session.commit()
    from app.services import orders as order_service
    values = iter(["aaaaaaaaaaaa", "bbbbbbbbbbbb"])
    monkeypatch.setattr(order_service.secrets, "token_hex", lambda length: next(values))
    monkeypatch.setattr(order_service, "utc_now", lambda: type("Now", (), {"year": 2026})())
    review(client, file_id, shop_id)
    result = place(client, file_id, shop_id)
    assert result.status_code == 302
    assert result.headers["Location"].endswith("POD-2026-BBBBBBBBBBBB")
    with test_app.app_context():
        assert len(db.session.scalars(select(Order)).all()) == 2
        assert len(db.session.scalars(select(OrderItem)).all()) == 1


def test_reference_unique_constraint_and_csrf(client, test_app):
    user_id = student(test_app)
    shop_id = shop(test_app)
    file_id = file(test_app, user_id)
    sign_in(client, user_id)
    review(client, file_id, shop_id)
    assert client.post("/orders/create", data={"file_id": file_id, "shop_id": shop_id}).status_code == 400
    assert place(client, "bad", shop_id).status_code == 400
    assert place(client, file_id, "bad").status_code == 400
    assert place(client, file_id, shop_id).status_code == 302
    with test_app.app_context():
        original = db.session.scalar(select(Order))
        duplicate = Order(
            user_id=user_id, shop_id=shop_id,
            order_reference=original.order_reference, shop_name="Campus Prints",
            subtotal=Decimal("0.00"), fees_total=Decimal("0.00"),
            total=Decimal("0.00"), currency="PHP",
        )
        db.session.add(duplicate)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_order_foreign_keys_reject_orphans_in_sqlite(test_app):
    with test_app.app_context():
        assert db.session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        db.session.add(Order(
            user_id=9999, shop_id=9999,
            order_reference="POD-2026-ORPHAN000001", shop_name="Missing",
            subtotal=Decimal("0.00"), fees_total=Decimal("0.00"),
            total=Decimal("0.00"), currency="PHP",
        ))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_quote_is_decimal_not_float_and_owned(test_app):
    owner = student(test_app)
    other = student(test_app, "other@example.com")
    shop_id = shop(test_app, price="0.10")
    file_id = file(test_app, owner, quantity=3)
    with test_app.app_context():
        quote = quote_order(user_id=owner, file_id=file_id, shop_id=shop_id, max_quantity=999)
        assert quote.unit_price == Decimal("0.10")
        assert quote.total == Decimal("0.30")
        assert type(quote.total) is Decimal
        with pytest.raises(PricingError) as error:
            quote_order(user_id=other, file_id=file_id, shop_id=shop_id, max_quantity=999)
        assert error.value.status_code == 404
