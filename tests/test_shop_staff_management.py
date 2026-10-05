"""Assigned staff can edit only their shop and publish bounded images."""

from datetime import time
from decimal import Decimal
from io import BytesIO

from PIL import Image
from sqlalchemy import select

from app.extensions import db
from app.models import ColorMode, FeeType, PaperSize, PrintPrice, PrintingShop, ServiceType, ShopFee, ShopService, UserRole
from test_shop_map import map_data, set_location
from test_shops import add_shop, add_user, token
from test_orders import sign_in


def image_bytes():
    image = Image.new("RGB", (1500, 900), "#31527b")
    output = BytesIO()
    image.save(output, format="JPEG", exif=Image.Exif())
    return output.getvalue()


def staff_post(client, endpoint, data):
    page = client.get("/shop/manage")
    return client.post(f"/shop/manage/{endpoint}", data={"csrf_token": token(page), **data})


def test_staff_edit_is_scoped_and_updates_student_view(client, test_app):
    owned = add_shop(test_app, "Owned Prints")
    other = add_shop(test_app, "Other Prints")
    actor = add_user(test_app, UserRole.SHOP_STAFF, "owned@example.edu", shop_id=owned)
    student = add_user(test_app, UserRole.STUDENT, "student@example.edu")
    sign_in(client, actor)
    assert client.get("/shop/manage").status_code == 200
    assert client.post("/shop/manage/details", data={"address": "Forged"}).status_code == 400
    changed = staff_post(client, "details", {
        "description": "Fast campus printing", "address": "New campus location",
        "opening_time": "08:00", "closing_time": "18:00", "shop_id": str(other),
        "name": "Blue and Silver Bookstore", "latitude": "14.1", "is_active": "",
    })
    assert changed.status_code == 302
    assert staff_post(client, "services", {
        "service_type": "DELIVERY", "enabled": "y", "shop_id": str(other),
    }).status_code == 302
    assert staff_post(client, "prices", {
        "paper_size": "A4", "color_mode": "COLOR", "price": "8.75", "shop_id": str(other),
    }).status_code == 302
    assert staff_post(client, "fees", {
        "fee_type": "DELIVERY", "amount": "20.00", "shop_id": str(other),
    }).status_code == 302
    assert staff_post(client, "services", {
        "service_type": "DIRECT_TO_PROFESSOR", "enabled": "y",
    }).status_code == 400
    assert staff_post(client, "prices", {
        "paper_size": "A4", "color_mode": "COLOR", "price": "-1",
    }).status_code == 400
    with test_app.app_context():
        shop = db.session.get(PrintingShop, owned)
        untouched = db.session.get(PrintingShop, other)
        assert (shop.name, shop.description, shop.address, shop.opening_time, shop.closing_time) == (
            "Owned Prints", "Fast campus printing", "New campus location", time(8), time(18),
        )
        assert shop.latitude is None and shop.is_active
        assert untouched.description == "Near campus" and untouched.address == "Campus Road"
        assert db.session.scalar(select(ShopService).where(
            ShopService.shop_id == owned, ShopService.service_type == ServiceType.DELIVERY,
        )).enabled
        assert db.session.scalar(select(PrintPrice).where(
            PrintPrice.shop_id == owned, PrintPrice.paper_size == PaperSize.A4,
            PrintPrice.color_mode == ColorMode.COLOR,
        )).price == Decimal("8.75")
        assert db.session.scalar(select(ShopFee).where(
            ShopFee.shop_id == owned, ShopFee.fee_type == FeeType.DELIVERY,
        )).amount == Decimal("20.00")
        assert db.session.scalar(select(PrintPrice).where(PrintPrice.shop_id == other)) is None
    sign_in(client, student)
    page = client.get(f"/shops/{owned}")
    assert b"Fast campus printing" in page.data and b"8.75" in page.data
    assert client.get("/shop/manage").status_code == 403
    assert client.post("/shop/manage/prices", data={
        "csrf_token": token(client.get("/student")),
    }).status_code == 403


def test_shop_photo_is_processed_and_used_by_map_and_pages(client, test_app):
    shop_id = add_shop(test_app, "Photo Prints")
    set_location(test_app, shop_id)
    actor = add_user(test_app, UserRole.SHOP_STAFF, "photo@example.edu", shop_id=shop_id)
    student = add_user(test_app, UserRole.STUDENT, "student@example.edu")
    sign_in(client, actor)
    assert staff_post(client, "photo", {
        "photo": (BytesIO(b"not an image"), "fake.jpg"),
    }).status_code == 400
    response = staff_post(client, "photo", {
        "photo": (BytesIO(image_bytes()), "shop.jpg"),
    })
    assert response.status_code == 302
    with test_app.app_context():
        shop = db.session.get(PrintingShop, shop_id)
        assert shop.photo_mime == "image/jpeg" and len(shop.photo_digest) == 64
        with Image.open(BytesIO(shop.photo_data)) as processed:
            assert processed.size == (1024, 614)
            assert not processed.getexif()
    photo = client.get(f"/shops/{shop_id}/photo")
    assert photo.status_code == 200 and photo.mimetype == "image/jpeg"
    assert photo.headers["X-Content-Type-Options"] == "nosniff"
    sign_in(client, student)
    assert b"/photo?v=" in client.get("/shops").data
    assert b"/photo?v=" in client.get(f"/shops/{shop_id}").data
    marker = map_data(client.get("/shops/map"))[0]
    assert marker["photo_url"].startswith(f"/shops/{shop_id}/photo?v=")
    sign_in(client, actor)
    assert staff_post(client, "photo/remove", {}).status_code == 302
    assert client.get(f"/shops/{shop_id}/photo").status_code == 404


def test_unassigned_and_other_roles_cannot_manage_shop(client, test_app):
    add_shop(test_app, "One Shop")
    for role in (UserRole.STUDENT, UserRole.PROFESSOR, UserRole.ADMIN, UserRole.SHOP_STAFF):
        actor = add_user(test_app, role, f"{role.value.lower()}@example.edu")
        sign_in(client, actor)
        assert client.get("/shop/manage").status_code == 403
        own_page = {
            UserRole.STUDENT: "/student", UserRole.PROFESSOR: "/professor",
            UserRole.ADMIN: "/admin", UserRole.SHOP_STAFF: "/shop",
        }[role]
        assert client.post("/shop/manage/photo/remove", data={
            "csrf_token": token(client.get(own_page)),
        }).status_code == 403
