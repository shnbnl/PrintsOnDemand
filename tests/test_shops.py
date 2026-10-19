"""Shop directory, administration, prices, seed data, and access boundaries."""

import re
from datetime import time
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    ColorMode,
    FeeType,
    PaperSize,
    PrintPrice,
    PrintingShop,
    ServiceType,
    ShopFee,
    ShopService,
    User,
    UserRole,
)


PASSWORD = "A-strong-password-123"


def token(response):
    found = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', response.data)
    assert found, "CSRF token missing"
    return found.group(1).decode()


def add_user(app, role, email, shop_id=None):
    with app.app_context():
        user = User(name=email.split("@")[0], email=email, role=role, shop_id=shop_id)
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.commit()
        return user.id


def login(client, email):
    csrf = token(client.get("/auth/login"))
    response = client.post(
        "/auth/login", data={"email": email, "password": PASSWORD, "csrf_token": csrf}
    )
    assert response.status_code == 302


def add_shop(app, name="Campus Prints", active=True, demo=False):
    with app.app_context():
        shop = PrintingShop(
            name=name,
            description="Near campus",
            address="Campus Road",
            opening_time=time(9, 0),
            closing_time=time(17, 0),
            is_active=active,
            is_demo=demo,
        )
        db.session.add(shop)
        db.session.commit()
        return shop.id


def admin_post(client, shop_id, suffix, data):
    csrf = token(client.get(f"/admin/shops/{shop_id}/edit"))
    return client.post(
        f"/admin/shops/{shop_id}/{suffix}", data={**data, "csrf_token": csrf}
    )


def test_shop_model_creation_and_activation(test_app):
    shop_id = add_shop(test_app)
    with test_app.app_context():
        shop = db.session.get(PrintingShop, shop_id)
        assert shop.name == "Campus Prints"
        assert shop.address == "Campus Road"
        assert shop.opening_time == time(9, 0)
        assert shop.created_at is not None
        shop.is_active = False
        db.session.commit()
        assert db.session.get(PrintingShop, shop_id).is_active is False


def test_duplicate_service_and_price_rejected_by_database(test_app):
    shop_id = add_shop(test_app)
    with test_app.app_context():
        db.session.add(ShopService(shop_id=shop_id, service_type=ServiceType.PICKUP))
        db.session.add(
            PrintPrice(
                shop_id=shop_id, paper_size=PaperSize.A4,
                color_mode=ColorMode.GRAYSCALE, price=Decimal("3.00"),
            )
        )
        db.session.commit()

        db.session.add(ShopService(shop_id=shop_id, service_type=ServiceType.PICKUP))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        db.session.add(
            PrintPrice(
                shop_id=shop_id, paper_size=PaperSize.A4,
                color_mode=ColorMode.GRAYSCALE, price=Decimal("4.00"),
            )
        )
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_fee_uniqueness_and_negative_values_rejected_by_database(test_app):
    shop_id = add_shop(test_app)
    with test_app.app_context():
        db.session.add(ShopFee(shop_id=shop_id, fee_type=FeeType.DELIVERY, amount=Decimal("2.00")))
        db.session.commit()

        db.session.add(ShopFee(shop_id=shop_id, fee_type=FeeType.DELIVERY, amount=Decimal("3.00")))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        db.session.add(
            PrintPrice(
                shop_id=shop_id, paper_size=PaperSize.LETTER,
                color_mode=ColorMode.COLOR, price=Decimal("-1.00"),
            )
        )
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        db.session.add(ShopFee(shop_id=shop_id, fee_type=FeeType.RUSH_PRINTING, amount=Decimal("-0.01")))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_anonymous_shop_and_admin_pages_redirect_to_login(client):
    for path in ("/shops", "/shops/1", "/admin/shops", "/admin/shops/new"):
        response = client.get(path)
        assert response.status_code == 302
        assert "/auth/login" in response.headers["Location"]


def test_student_list_search_and_detail_only_show_active_shops(client, test_app):
    active_id = add_shop(test_app, "Blue Bookstore", demo=True)
    inactive_id = add_shop(test_app, "Closed Shop", active=False)
    with test_app.app_context():
        db.session.add(ShopService(shop_id=active_id, service_type=ServiceType.PICKUP))
        db.session.add(ShopService(shop_id=active_id, service_type=ServiceType.DELIVERY, enabled=False))
        db.session.add(
            PrintPrice(
                shop_id=active_id, paper_size=PaperSize.A4,
                color_mode=ColorMode.GRAYSCALE, price=Decimal("4.50"), is_demo=True,
            )
        )
        db.session.add(ShopFee(shop_id=active_id, fee_type=FeeType.DELIVERY, amount=Decimal("9.00")))
        db.session.commit()
    add_user(test_app, UserRole.STUDENT, "student@example.com")
    login(client, "student@example.com")

    listed = client.get("/shops")
    assert listed.status_code == 200
    assert b"Blue Bookstore" in listed.data
    assert b"Closed Shop" not in listed.data
    assert b"Pick-up" in listed.data
    assert b"Delivery" not in listed.data
    assert b"Sample shop information" in listed.data

    searched = client.get("/shops?q=bLuE")
    assert b"Blue Bookstore" in searched.data
    assert b"Closed Shop" not in searched.data
    assert b"Blue Bookstore" not in client.get("/shops?q=%25").data

    detail = client.get(f"/shops/{active_id}")
    assert detail.status_code == 200
    assert b"Campus Road" in detail.data
    assert b"4.50" in detail.data
    assert b"(sample)" in detail.data
    assert "—" in detail.get_data(as_text=True)
    assert b"Delivery" not in detail.data
    assert b"Ready to continue?" not in detail.data
    assert f"/checkout/upload?shop_id={active_id}".encode() not in detail.data
    assert client.get(f"/shops/{inactive_id}").status_code == 404


def test_shop_detail_places_fees_beside_services_above_prices(client, test_app):
    shop_id = add_shop(test_app)
    with test_app.app_context():
        db.session.add(ShopService(shop_id=shop_id, service_type=ServiceType.RUSH_PRINTING))
        db.session.add(ShopFee(shop_id=shop_id, fee_type=FeeType.RUSH_PRINTING,
                               amount=Decimal("20.00")))
        db.session.commit()
    add_user(test_app, UserRole.STUDENT, "student@example.com")
    login(client, "student@example.com")

    detail = client.get(f"/shops/{shop_id}")
    assert detail.status_code == 200
    html = detail.get_data(as_text=True)
    assert html.index("Services offered") < html.index("Additional fees") < html.index("Pricelist")
    assert 'class="shop-detail-grid"' in html


def test_student_cannot_modify_shops_or_prices(client, test_app):
    shop_id = add_shop(test_app)
    add_user(test_app, UserRole.STUDENT, "student@example.com")
    login(client, "student@example.com")
    csrf = token(client.get("/student"))

    assert client.get("/admin/shops").status_code == 403
    assert client.get(f"/admin/shops/{shop_id}/edit").status_code == 403
    assert client.post(
        f"/admin/shops/{shop_id}/prices",
        data={"paper_size": "A4", "color_mode": "COLOR", "price": "1.00", "csrf_token": csrf},
    ).status_code == 403
    with test_app.app_context():
        assert db.session.scalar(select(PrintPrice)) is None


def test_admin_creates_edits_and_deactivates_shop(client, test_app):
    add_user(test_app, UserRole.ADMIN, "admin@example.com")
    login(client, "admin@example.com")
    csrf = token(client.get("/admin/shops/new"))
    created = client.post(
        "/admin/shops/new",
        data={
            "name": "New Print Shop", "description": "A local shop", "address": "Main Street",
            "opening_time": "08:30", "closing_time": "18:00", "is_active": "y", "csrf_token": csrf,
        },
    )
    assert created.status_code == 302
    with test_app.app_context():
        shop = db.session.scalar(select(PrintingShop).where(PrintingShop.name == "New Print Shop"))
        shop_id = shop.id
        assert shop.is_active
        assert not shop.is_demo

    edited = admin_post(
        client, shop_id, "edit",
        {"name": "Renamed Print Shop", "description": "Updated", "address": "Other Road",
         "opening_time": "09:00", "closing_time": "17:00"},
    )
    assert edited.status_code == 302
    with test_app.app_context():
        shop = db.session.get(PrintingShop, shop_id)
        assert shop.name == "Renamed Print Shop"
        assert shop.address == "Other Road"
        assert shop.is_active is False
    assert b"Inactive" in client.get("/admin/shops").data


def test_admin_can_configure_and_update_service_price_and_fee(client, test_app):
    shop_id = add_shop(test_app)
    add_user(test_app, UserRole.ADMIN, "admin@example.com")
    login(client, "admin@example.com")

    assert admin_post(
        client, shop_id, "services", {"service_type": "RUSH_PRINTING", "enabled": "y"}
    ).status_code == 302
    assert admin_post(
        client, shop_id, "services", {"service_type": "RUSH_PRINTING"}
    ).status_code == 302
    assert admin_post(
        client, shop_id, "prices",
        {"paper_size": "A2", "color_mode": "COLOR", "price": "15.50"},
    ).status_code == 302
    assert admin_post(
        client, shop_id, "prices",
        {"paper_size": "A2", "color_mode": "COLOR", "price": "16.75"},
    ).status_code == 302
    rejected = admin_post(
        client, shop_id, "fees", {"fee_type": "RUSH_PRINTING", "amount": "5.25"}
    )
    assert rejected.status_code == 200
    assert b"Not a valid choice" in rejected.data
    assert admin_post(
        client, shop_id, "fees", {"fee_type": "DELIVERY", "amount": "12.00"}
    ).status_code == 302

    with test_app.app_context():
        services = db.session.scalars(select(ShopService)).all()
        prices = db.session.scalars(select(PrintPrice)).all()
        fees = db.session.scalars(select(ShopFee)).all()
        assert len(services) == len(prices) == 1
        assert len(fees) == 1
        assert services[0].enabled is False
        assert prices[0].price == Decimal("16.75")
        assert prices[0].is_demo is False
        assert {fee.fee_type: fee.amount for fee in fees} == {
            FeeType.DELIVERY: Decimal("12.00"),
        }


@pytest.mark.parametrize(
    "suffix,data",
    [
        ("prices", {"paper_size": "A4", "color_mode": "COLOR", "price": "-1.00"}),
        ("prices", {"paper_size": "A4", "color_mode": "COLOR", "price": "1.234"}),
        ("prices", {"paper_size": "A4", "color_mode": "COLOR", "price": "NaN"}),
        ("prices", {"paper_size": "A4", "color_mode": "COLOR", "price": "Infinity"}),
        ("prices", {"paper_size": "A4", "color_mode": "COLOR", "price": "100000000.00"}),
        ("prices", {"paper_size": "A0", "color_mode": "COLOR", "price": "1.00"}),
        ("prices", {"paper_size": "A4", "color_mode": "NEON", "price": "1.00"}),
        ("fees", {"fee_type": "DELIVERY", "amount": "-0.01"}),
    ],
)
def test_admin_rejects_invalid_pricing(client, test_app, suffix, data):
    shop_id = add_shop(test_app)
    add_user(test_app, UserRole.ADMIN, "admin@example.com")
    login(client, "admin@example.com")

    response = admin_post(client, shop_id, suffix, data)
    assert response.status_code == 200
    with test_app.app_context():
        assert db.session.scalar(select(PrintPrice)) is None
        assert db.session.scalar(select(ShopFee)) is None


def test_admin_assigns_staff_and_staff_sees_only_own_shop(client, test_app):
    own_id = add_shop(test_app, "Assigned Shop")
    other_id = add_shop(test_app, "Other Shop")
    staff_id = add_user(test_app, UserRole.SHOP_STAFF, "staff@example.com")
    add_user(test_app, UserRole.ADMIN, "admin@example.com")
    with test_app.app_context():
        db.session.add(
            PrintPrice(
                shop_id=own_id, paper_size=PaperSize.LETTER,
                color_mode=ColorMode.GRAYSCALE, price=Decimal("3.25"),
            )
        )
        db.session.commit()
    login(client, "admin@example.com")
    assigned = admin_post(client, own_id, "staff", {"staff_id": str(staff_id)})
    assert assigned.status_code == 302
    with test_app.app_context():
        assert db.session.get(User, staff_id).shop_id == own_id

    logout_csrf = token(client.get("/admin"))
    client.post("/auth/logout", data={"csrf_token": logout_csrf})
    login(client, "staff@example.com")
    own = client.get("/shop")
    assert own.status_code == 200
    assert b"Assigned Shop" in own.data
    assert b"3.25" in own.data
    assert b"Other Shop" not in own.data
    assert client.get(f"/shops/{other_id}").status_code == 403
    assert client.get(f"/admin/shops/{other_id}/edit").status_code == 403
    assert client.post(
        f"/admin/shops/{own_id}/prices",
        data={"paper_size": "A4", "color_mode": "COLOR", "price": "1.00", "csrf_token": token(own)},
    ).status_code == 403


def test_admin_cannot_assign_student_as_staff(client, test_app):
    shop_id = add_shop(test_app)
    student_id = add_user(test_app, UserRole.STUDENT, "student@example.com")
    add_user(test_app, UserRole.ADMIN, "admin@example.com")
    login(client, "admin@example.com")

    response = admin_post(client, shop_id, "staff", {"staff_id": str(student_id)})
    assert response.status_code == 200
    with test_app.app_context():
        assert db.session.get(User, student_id).shop_id is None


def test_invalid_service_and_missing_csrf_cannot_change_shop(client, test_app):
    shop_id = add_shop(test_app)
    add_user(test_app, UserRole.ADMIN, "admin@example.com")
    login(client, "admin@example.com")

    invalid = admin_post(client, shop_id, "services", {"service_type": "MADE_UP", "enabled": "y"})
    assert invalid.status_code == 200
    assert client.post(
        f"/admin/shops/{shop_id}/services", data={"service_type": "PICKUP", "enabled": "y"}
    ).status_code == 400
    with test_app.app_context():
        assert db.session.scalar(select(ShopService)) is None


def test_seed_is_explicit_idempotent_and_marked_demo(test_app):
    runner = test_app.test_cli_runner()
    first = runner.invoke(args=["seed-demo-shops"])
    second = runner.invoke(args=["seed-demo-shops"])

    assert first.exit_code == second.exit_code == 0
    assert "Added 4 sample shops" in first.output
    assert "Added 0 sample shops" in second.output
    assert "Added 0 sample shops" in runner.invoke(args=["seed-sample-shops"]).output
    with test_app.app_context():
        shops = db.session.scalars(select(PrintingShop)).all()
        prices = db.session.scalars(select(PrintPrice)).all()
        assert len(shops) == 4
        assert len(prices) == 40
        assert all(shop.is_demo for shop in shops)
        assert all(price.is_demo for price in prices)
        assert all(price.price >= 0 for price in prices)


def test_demo_seed_refused_in_production(monkeypatch):
    from app import create_app
    from app.config import ProductionConfig

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@localhost:5432/prints")
    monkeypatch.setenv("SECRET_KEY", "test-production-key-with-adequate-length")
    monkeypatch.setenv("TRUSTED_HOSTS", "prints.example")
    production_app = create_app(ProductionConfig)

    result = production_app.test_cli_runner().invoke(args=["seed-demo-shops"])
    assert result.exit_code != 0
    assert "disabled in production" in result.output
