"""Student map discovery stays within the registered-shop access boundary."""

import json
import re
from datetime import time
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (ColorMode, FeeType, PaperSize, PrintPrice, PrintingShop,
                        ShopFee, ShopService, ServiceType, UserRole)
from tests.test_shops import add_shop, add_user, login, token


FINAL_DEMO_COORDINATES = {
    "Blue and Silver Bookstore": (Decimal("14.243257164979285"), Decimal("121.11300634061479")),
    "CHALECOSPOT": (Decimal("14.242503893301787"), Decimal("121.1137415531051")),
    "Iced Design and Prints": (Decimal("14.243062163277235"), Decimal("121.11345252527298")),
    "Pixels Print and Press": (Decimal("14.241960049308364"), Decimal("121.11268038748165")),
}
PREVIOUS_DEMO_COORDINATES = {
    "Blue and Silver Bookstore": (Decimal("14.243034885614946"), Decimal("121.1129526948974")),
    "CHALECOSPOT": (Decimal("14.24264686747224"), Decimal("121.11376032373335")),
    "Iced Design and Prints": (Decimal("14.243072562326358"), Decimal("121.11352762558575")),
    "Pixels Print and Press": (Decimal("14.242065977086666"), Decimal("121.11273536791352")),
}


def map_data(response):
    match = re.search(rb'<script id="map-shop-data" type="application/json">(.*?)</script>', response.data, re.S)
    assert match
    return json.loads(match.group(1))


def set_location(app, shop_id, latitude="14.243375", longitude="121.112716"):
    with app.app_context():
        shop = db.session.get(PrintingShop, shop_id)
        shop.latitude = Decimal(latitude) if latitude is not None else None
        shop.longitude = Decimal(longitude) if longitude is not None else None
        db.session.commit()


def test_student_map_search_and_existing_shop_flow(client, test_app):
    mapped = add_shop(test_app, "Mapped Campus Shop")
    unmapped = add_shop(test_app, "No Location Shop")
    inactive = add_shop(test_app, "Inactive Shop", active=False)
    set_location(test_app, mapped)
    set_location(test_app, inactive)
    with test_app.app_context():
        db.session.add(ShopService(shop_id=mapped, service_type=ServiceType.RUSH_PRINTING))
        db.session.add(PrintPrice(
            shop_id=mapped, paper_size=PaperSize.A4,
            color_mode=ColorMode.COLOR, price=Decimal("8.75"),
        ))
        db.session.commit()
    add_user(test_app, UserRole.STUDENT, "map.student@example.com")
    login(client, "map.student@example.com")
    test_app.config["GOOGLE_MAPS_API_KEY"] = ""

    listing = client.get("/shops")
    assert listing.status_code == 200
    assert b"Map view" in listing.data
    assert b"Mapped Campus Shop" in listing.data
    assert b"No Location Shop" in listing.data
    assert b"Inactive Shop" not in listing.data

    response = client.get("/shops/map")
    assert response.status_code == 200
    assert b"Map unavailable" in response.data  # No local API key is required to browse.
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert b"View shops as a list" in response.data
    assert b"Proceed" in response.data
    shops = map_data(response)
    assert len(shops) == 1
    assert shops[0]["id"] == mapped
    assert shops[0]["position"] == {"lat": 14.243375, "lng": 121.112716}
    assert shops[0]["services"] == ["Rush Printing"]
    assert shops[0]["prices"][2]["color"] == "₱8.75"
    assert set(shops[0]) == {
        "id", "name", "description", "address", "hours", "services",
        "fulfillment", "fees", "prices", "is_demo", "position", "detail_url",
    }
    assert shops[0]["fulfillment"] == [] and shops[0]["fees"] == []
    assert "admin" not in response.get_data(as_text=True).lower()
    detail_url = shops[0]["detail_url"]
    assert detail_url == f"/shops/{mapped}"
    detail = client.get(detail_url)
    assert detail.status_code == 200
    assert b"8.75" in detail.data
    assert b"Upload and configure a file" in detail.data

    searched = client.get("/shops/map?q=MaPpEd")
    assert [shop["id"] for shop in map_data(searched)] == [mapped]
    assert map_data(client.get("/shops/map?q=%25")) == []
    assert map_data(client.get("/shops/map?q=inactive")) == []
    assert map_data(client.get("/shops/map?q=No+Location")) == []
    assert client.get(f"/shops/{unmapped}").status_code == 200
    assert client.get(f"/shops/{inactive}").status_code == 404


def test_custom_panel_uses_registered_shop_services_fees_and_existing_proceed(client, test_app):
    mapped = add_shop(test_app, "Configured Print Shop")
    set_location(test_app, mapped)
    with test_app.app_context():
        db.session.add_all([
            ShopService(shop_id=mapped, service_type=ServiceType.PICKUP, enabled=True),
            ShopService(shop_id=mapped, service_type=ServiceType.DELIVERY, enabled=True),
            ShopService(shop_id=mapped, service_type=ServiceType.DIRECT_TO_PROFESSOR, enabled=True),
            ShopFee(shop_id=mapped, fee_type=FeeType.DELIVERY, amount=Decimal("30.00")),
        ])
        db.session.commit()
    add_user(test_app, UserRole.STUDENT, "configured.map@example.com")
    login(client, "configured.map@example.com")
    response = client.get("/shops/map")
    assert response.status_code == 200
    marker = map_data(response)[0]
    assert marker["id"] == mapped
    assert marker["fulfillment"] == ["Scheduled Pickup", "Delivery"]
    assert marker["fees"] == [{"label": "Delivery", "amount": "₱30.00", "is_demo": False}]
    assert b"Available" in response.data
    assert b"Applicable fees" in response.data
    assert b"Scheduled Pickup" in response.data
    assert client.get(marker["detail_url"]).status_code == 200

    with test_app.app_context():
        db.session.scalar(select(ShopFee).where(ShopFee.shop_id == mapped)).amount = Decimal("42.00")
        db.session.commit()
    assert map_data(client.get("/shops/map"))[0]["fees"][0]["amount"] == "₱42.00"


def test_map_authorization_matches_existing_shop_policy(client, test_app):
    anonymous = client.get("/shops/map")
    assert anonymous.status_code == 302
    assert "/auth/login" in anonymous.headers["Location"]
    add_user(test_app, UserRole.SHOP_STAFF, "map.staff@example.com")
    login(client, "map.staff@example.com")
    assert client.get("/shops/map").status_code == 403


def test_map_configuration_uses_browser_key_and_generic_production_fallback(client, test_app):
    add_user(test_app, UserRole.STUDENT, "map.student@example.com")
    login(client, "map.student@example.com")
    test_app.config["GOOGLE_MAPS_API_KEY"] = "test-browser-key"
    configured = client.get("/shops/map")
    assert b'data-api-key="test-browser-key"' in configured.data
    assert b"Loading the interactive map" in configured.data
    test_app.config["GOOGLE_MAPS_API_KEY"] = ""
    test_app.config["ENV_NAME"] = "production"
    fallback = client.get("/shops/map")
    assert b"Map unavailable" in fallback.data
    assert b"GOOGLE_MAPS_API_KEY" not in fallback.data


@pytest.mark.parametrize("latitude,longitude", [
    ("90.000001", "121"), ("-90.000001", "121"),
    ("14", "180.000001"), ("14", "-180.000001"),
    ("NaN", "121"), ("Infinity", "121"),
    ("14.1234567890123456", "121"), ("14", "121.1234567890123456"),
    ("14", ""), ("", "121"),
])
def test_admin_rejects_invalid_coordinates(client, test_app, latitude, longitude):
    add_user(test_app, UserRole.ADMIN, "map.admin@example.com")
    login(client, "map.admin@example.com")
    csrf = token(client.get("/admin/shops/new"))
    response = client.post("/admin/shops/new", data={
        "csrf_token": csrf, "name": "Bad Location", "description": "",
        "address": "Campus", "opening_time": "09:00", "closing_time": "17:00",
        "latitude": latitude, "longitude": longitude, "is_active": "y",
    })
    assert response.status_code == 200
    with test_app.app_context():
        assert db.session.scalar(select(PrintingShop).where(PrintingShop.name == "Bad Location")) is None


def test_admin_saves_and_clears_confirmed_coordinates(client, test_app):
    add_user(test_app, UserRole.ADMIN, "map.admin@example.com")
    login(client, "map.admin@example.com")
    csrf = token(client.get("/admin/shops/new"))
    response = client.post("/admin/shops/new", data={
        "csrf_token": csrf, "name": "Located Shop", "description": "",
        "address": "Campus", "opening_time": "09:00", "closing_time": "17:00",
        "latitude": "-90", "longitude": "180", "is_active": "y",
    })
    assert response.status_code == 302
    with test_app.app_context():
        shop = db.session.scalar(select(PrintingShop).where(PrintingShop.name == "Located Shop"))
        shop_id = shop.id
        assert (shop.latitude, shop.longitude) == (Decimal("-90.000000"), Decimal("180.000000"))
    csrf = token(client.get(f"/admin/shops/{shop_id}/edit"))
    response = client.post(f"/admin/shops/{shop_id}/edit", data={
        "csrf_token": csrf, "name": "Located Shop", "description": "",
        "address": "Campus", "opening_time": "09:00", "closing_time": "17:00",
        "latitude": "", "longitude": "", "is_active": "y",
    })
    assert response.status_code == 302
    with test_app.app_context():
        shop = db.session.get(PrintingShop, shop_id)
        assert shop.latitude is shop.longitude is None


def test_database_rejects_out_of_range_coordinate(test_app):
    shop_id = add_shop(test_app)
    with test_app.app_context():
        shop = db.session.get(PrintingShop, shop_id)
        shop.latitude = Decimal("91")
        shop.longitude = Decimal("121")
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_demo_seed_corrects_only_coordinates_for_existing_demo_shops(test_app):
    from app.seed import DEMO_SHOP_COORDINATES

    assert DEMO_SHOP_COORDINATES == FINAL_DEMO_COORDINATES
    runner = test_app.test_cli_runner()
    seeded = runner.invoke(args=["seed-demo-shops"])
    assert seeded.exit_code == 0
    assert "Added 4 demo shops; refreshed verified coordinates on 0 existing demo shops." in seeded.output
    with test_app.app_context():
        assigned_shop_id = db.session.scalar(
            select(PrintingShop.id).where(PrintingShop.name == "Blue and Silver Bookstore")
        )
    staff_id = add_user(test_app, UserRole.SHOP_STAFF, "seed.staff@example.com", assigned_shop_id)
    with test_app.app_context():
        shops = db.session.scalars(select(PrintingShop).order_by(PrintingShop.name)).all()
        assert len(shops) == 4
        original_ids = {shop.name: shop.id for shop in shops}
        original_data = {
            shop.name: (shop.description, shop.address, shop.opening_time,
                        shop.closing_time, shop.is_active, shop.is_demo,
                        tuple(sorted((service.service_type.value, service.enabled)
                                     for service in shop.services)),
                        tuple(sorted((price.paper_size.value, price.color_mode.value,
                                      price.price, price.is_demo) for price in shop.prices)),
                        tuple(sorted((fee.fee_type.value, fee.amount, fee.is_demo)
                                     for fee in shop.fees)),
                        tuple(sorted(staff.id for staff in shop.staff)))
            for shop in shops
        }
        for shop in shops:
            shop.latitude, shop.longitude = PREVIOUS_DEMO_COORDINATES[shop.name]
        db.session.commit()
    refreshed = runner.invoke(args=["seed-demo-shops"])
    assert refreshed.exit_code == 0
    assert "Added 0 demo shops; refreshed verified coordinates on 4 existing demo shops." in refreshed.output
    with test_app.app_context():
        shops = db.session.scalars(select(PrintingShop).order_by(PrintingShop.name)).all()
        assert len(shops) == 4
        for shop in shops:
            assert shop.id == original_ids[shop.name]
            assert (shop.latitude, shop.longitude) == FINAL_DEMO_COORDINATES[shop.name]
            assert (shop.description, shop.address, shop.opening_time,
                    shop.closing_time, shop.is_active, shop.is_demo,
                    tuple(sorted((service.service_type.value, service.enabled)
                                 for service in shop.services)),
                    tuple(sorted((price.paper_size.value, price.color_mode.value,
                                  price.price, price.is_demo) for price in shop.prices)),
                    tuple(sorted((fee.fee_type.value, fee.amount, fee.is_demo)
                                 for fee in shop.fees)),
                    tuple(sorted(staff.id for staff in shop.staff))) == original_data[shop.name]
        assert staff_id in tuple(staff.id for staff in shops[0].staff)
    unchanged = runner.invoke(args=["seed-demo-shops"])
    assert unchanged.exit_code == 0
    assert "Added 0 demo shops; refreshed verified coordinates on 0 existing demo shops." in unchanged.output


def test_exact_demo_coordinates_are_persisted_and_sent_to_map(client, test_app):
    from app.seed import DEMO_SHOP_COORDINATES

    assert DEMO_SHOP_COORDINATES == FINAL_DEMO_COORDINATES
    assert test_app.test_cli_runner().invoke(args=["seed-demo-shops"]).exit_code == 0
    add_user(test_app, UserRole.STUDENT, "exact-map@example.com")
    login(client, "exact-map@example.com")
    markers = map_data(client.get("/shops/map"))
    assert len(markers) == len(FINAL_DEMO_COORDINATES) == 4
    assert {marker["name"] for marker in markers} == set(FINAL_DEMO_COORDINATES)
    for marker in markers:
        latitude, longitude = FINAL_DEMO_COORDINATES[marker["name"]]
        assert marker["position"] == {"lat": float(latitude), "lng": float(longitude)}
        with test_app.app_context():
            shop = db.session.get(PrintingShop, marker["id"])
            assert (shop.latitude, shop.longitude) == (latitude, longitude)


def test_demo_seed_does_not_locate_existing_non_demo_shop(test_app):
    existing_id = add_shop(test_app, "Blue and Silver Bookstore")
    set_location(test_app, existing_id, "14.240001", "121.110001")
    assert test_app.test_cli_runner().invoke(args=["seed-demo-shops"]).exit_code == 0
    with test_app.app_context():
        existing = db.session.get(PrintingShop, existing_id)
        assert existing.is_demo is False
        assert (existing.latitude, existing.longitude) == (Decimal("14.240001"), Decimal("121.110001"))
