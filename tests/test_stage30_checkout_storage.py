"""Checkout-only staging, order attachment, shop access, map, and print controls."""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.extensions import db
from app.models import (
    ColorMode, FeeType, Order, PaperSize, PrintPrice, ServiceType, ShopFee,
    ShopService, UploadedFile, User, UserRole,
)
from app.models.user import utc_now
from app.services.staged_uploads import cleanup_staged_uploads
from test_checkout_flow import print_fields, post, setup, start, upload_checkout_file
from test_orders import PDF, file, pickup_fields, shop, sign_in, student
from test_shop_map import map_data


def test_expired_staged_cleanup_preserves_legacy_and_order_files(client, test_app):
    owner, shop_id, staged_id = setup(client, test_app)
    legacy_id = file(test_app, owner, name="legacy.pdf")
    completed_id = upload_checkout_file(client, test_app, owner, "completed.pdf")
    assert start(client, shop_id, completed_id, quantity="1").status_code == 302
    assert post(client, "/checkout/payment", {"payment_method": "ONSITE"}).status_code == 302
    assert post(client, "/checkout/place").status_code == 302
    with test_app.app_context():
        staged = db.session.get(UploadedFile, staged_id)
        old_key = staged.storage_key
        staged.checkout_staged_at = utc_now() - timedelta(hours=48)
        # Even a malformed legacy marker cannot make an order attachment eligible.
        db.session.get(UploadedFile, completed_id).checkout_staged_at = utc_now() - timedelta(hours=48)
        db.session.commit()
        assert cleanup_staged_uploads(retention_hours=24) == 1
        assert db.session.get(UploadedFile, staged_id) is None
        assert db.session.get(UploadedFile, legacy_id) is not None
        assert db.session.get(UploadedFile, completed_id) is not None
        assert not Path(test_app.config["UPLOAD_STORAGE_ROOT"], old_key).exists()
        assert cleanup_staged_uploads(retention_hours=24) == 0


def test_expired_upload_cannot_enter_checkout_and_removing_a_draft_file_keeps_other_files(client, test_app):
    owner, _, first_id = setup(client, test_app)
    second_id = upload_checkout_file(client, test_app, owner, "second.pdf")
    assert post(client, "/checkout/upload", {"remove_file_id": str(first_id)}).status_code == 302
    page = client.get("/checkout/upload")
    assert b"second.pdf" in page.data and b"notes.pdf" not in page.data
    assert post(client, "/checkout/upload", {"file_id": str(first_id)}).status_code == 400

    with test_app.app_context():
        db.session.get(UploadedFile, second_id).checkout_staged_at = utc_now() - timedelta(hours=48)
        db.session.commit()
    page = client.get("/checkout/upload")
    assert b"second.pdf" not in page.data
    assert post(client, "/checkout/upload", {"file_id": str(second_id)}).status_code == 400


def test_order_files_are_private_and_shop_scoped(client, test_app):
    owner, shop_id, staged_id = setup(client, test_app)
    assert start(client, shop_id, staged_id).status_code == 302
    assert post(client, "/checkout/payment", {"payment_method": "ONSITE"}).status_code == 302
    assert post(client, "/checkout/place").status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        reference, item_id = order.order_reference, order.items[0].id
        key = order.items[0].uploaded_file.storage_key
        assert order.items[0].uploaded_file.checkout_staged_at is None
    owner_url = f"/orders/{reference}/files/{item_id}/download"
    staff_url = f"/staff/orders/{reference}/files/{item_id}/download"
    assert client.get(owner_url).data == PDF
    assert client.get(f"/static/{key}").status_code == 404
    stranger = student(test_app, "other-student@example.edu")
    sign_in(client, stranger)
    assert client.get(owner_url).status_code == 404
    assert client.get(f"/files/{staged_id}/download").status_code == 404
    own_staff = student(test_app, "own-staff@example.edu", UserRole.SHOP_STAFF)
    other_staff = student(test_app, "other-staff@example.edu", UserRole.SHOP_STAFF)
    other_shop = shop(test_app, name="Other Shop")
    with test_app.app_context():
        db.session.get(User, own_staff).shop_id = shop_id
        db.session.get(User, other_staff).shop_id = other_shop
        db.session.commit()
    sign_in(client, own_staff)
    assert client.get(staff_url).data == PDF
    sign_in(client, other_staff)
    assert client.get(staff_url).status_code == 404
    assert client.get(owner_url).status_code == 403


def test_checkout_shop_reuses_four_database_map_markers(client, test_app):
    assert test_app.test_cli_runner().invoke(args=["seed-demo-shops"]).exit_code == 0
    owner = student(test_app)
    sign_in(client, owner)
    file_id = upload_checkout_file(client, test_app, owner)
    page = client.get("/checkout/shop")
    assert page.status_code == 200
    markers = map_data(page)
    assert {marker["name"] for marker in markers} == {
        "Blue and Silver Bookstore", "CHALECOSPOT", "Iced Design and Prints", "Pixels Print and Press",
    }
    assert b'/static/js/shop-map.js' in page.data
    for marker in markers:
        assert f'value="{marker["id"]}"'.encode() in page.data
    chosen = markers[2]
    assert post(client, "/checkout/shop", {"shop_id": str(chosen["id"]), **print_fields(file_id)}).status_code == 302
    assert f'value="{chosen["id"]}"'.encode() in client.get("/checkout/shop").data
    assert post(client, "/checkout/shop", {"shop_id": "99999"}).status_code == 400


def test_configure_each_supported_size_color_count_and_rush_rule(client, test_app):
    _, shop_id, file_id = setup(client, test_app)
    with test_app.app_context():
        for size in PaperSize:
            for mode in ColorMode:
                if size == PaperSize.A4 and mode == ColorMode.GRAYSCALE:
                    continue
                db.session.add(PrintPrice(shop_id=shop_id, paper_size=size, color_mode=mode, price=Decimal("3.00")))
        db.session.commit()
    assert post(client, "/checkout/upload", {"file_id": str(file_id)}).status_code == 302
    assert post(client, "/checkout/shop", {"shop_id": str(shop_id), **print_fields(file_id)}).status_code == 302

    def configure(*, size="A4", mode="GRAYSCALE", count="1", rush=False):
        fields = {"file_id": str(file_id), f"paper_size_{file_id}": size,
                  f"color_mode_{file_id}": mode, f"quantity_{file_id}": count,
                  **pickup_fields()}
        if rush:
            fields[f"is_rush_{file_id}"] = "1"
        return post(client, "/checkout/shop", {"shop_id": str(shop_id), **fields})

    page = client.get("/checkout/shop")
    assert b"Print settings" in page.data
    for size in PaperSize:
        assert f'value="{size.value}:GRAYSCALE"'.encode() in page.data
        assert configure(size=size.value).status_code == 302
    for mode in ColorMode:
        assert configure(mode=mode.value).status_code == 302
    for count in ("1", "999"):
        assert configure(count=count).status_code == 302
    for size, mode, count in (("TABLOID", "GRAYSCALE", "1"), ("A4", "NEON", "1"),
                              ("A4", "GRAYSCALE", "0"), ("A4", "GRAYSCALE", "1000")):
        assert configure(size=size, mode=mode, count=count).status_code == 400
    assert configure(rush=True).status_code == 400
    with test_app.app_context():
        db.session.add(ShopService(shop_id=shop_id, service_type=ServiceType.RUSH_PRINTING, enabled=True))
        db.session.add(ShopFee(shop_id=shop_id, fee_type=FeeType.RUSH_PRINTING, amount=Decimal("5.50")))
        db.session.commit()
    assert configure(rush=True).status_code == 302
    assert post(client, "/checkout/fulfillment", pickup_fields()).status_code == 302
    assert b"PHP 0.45" in client.get("/checkout/payment").data
