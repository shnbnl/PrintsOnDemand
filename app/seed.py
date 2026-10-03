"""Explicit, development-only sample shops and prices."""

from datetime import time
from decimal import Decimal

from sqlalchemy import select

from app.extensions import db
from app.models import (
    ColorMode,
    FeeType,
    PaperSize,
    PrintPrice,
    Professor,
    PrintingShop,
    ServiceType,
    ShopFee,
    ShopService,
)


# DEMO values only. Never use these as approved production rates.
DEMO_PRICES = {
    PaperSize.LETTER: ("3.00", "7.00"),
    PaperSize.LEGAL: ("5.00", "10.00"),
    PaperSize.A4: ("4.00", "8.00"),
    PaperSize.A3: ("12.00", "20.00"),
    PaperSize.A2: ("18.00", "30.00"),
}
DEMO_FEES = {FeeType.RUSH_PRINTING: "25.00", FeeType.DELIVERY: "30.00"}
DEMO_ADDRESS = "Demo location near Mapúa Malayan Colleges Laguna"
# User-provided coordinates for these seeded demo-shop records.
DEMO_SHOP_COORDINATES = {
    "Blue and Silver Bookstore": (Decimal("14.243034885614946"), Decimal("121.1129526948974")),
    "CHALECOSPOT": (Decimal("14.24264686747224"), Decimal("121.11376032373335")),
    "Iced Design and Prints": (Decimal("14.243072562326358"), Decimal("121.11352762558575")),
    "Pixels Print and Press": (Decimal("14.242065977086666"), Decimal("121.11273536791352")),
}

DEMO_SHOPS = (
    (
        "Blue and Silver Bookstore", time(6, 0), time(17, 0),
        (ServiceType.PICKUP, ServiceType.DIRECT_TO_PROFESSOR),
    ),
    (
        "Iced Design and Prints", time(9, 0), time(15, 0),
        (ServiceType.PICKUP, ServiceType.DIRECT_TO_PROFESSOR, ServiceType.RUSH_PRINTING, ServiceType.DELIVERY),
    ),
    (
        "CHALECOSPOT", time(8, 30), time(18, 50),
        (ServiceType.PICKUP, ServiceType.RUSH_PRINTING),
    ),
    (
        "Pixels Print and Press", time(9, 0), time(17, 0),
        (ServiceType.PICKUP, ServiceType.RUSH_PRINTING),
    ),
)


def seed_demo_shops() -> tuple[int, int]:
    """Insert demo shops and refresh verified coordinates on their seed records."""
    added = 0
    coordinates_updated = 0
    for name, opening_time, closing_time, services in DEMO_SHOPS:
        existing = db.session.scalar(select(PrintingShop).where(PrintingShop.name == name))
        if existing:
            # The name plus demo flag identify the seeded record; preserve all
            # other fields and leave real/admin-created shops untouched.
            if existing.is_demo:
                coordinates = DEMO_SHOP_COORDINATES[name]
                if (existing.latitude, existing.longitude) != coordinates:
                    existing.latitude, existing.longitude = coordinates
                    coordinates_updated += 1
            continue
        shop = PrintingShop(
            name=name,
            description="Sample shop based on the UI reference; confirm details before real use.",
            address=DEMO_ADDRESS,
            latitude=DEMO_SHOP_COORDINATES[name][0],
            longitude=DEMO_SHOP_COORDINATES[name][1],
            opening_time=opening_time,
            closing_time=closing_time,
            is_demo=True,
        )
        db.session.add(shop)
        for service_type in services:
            shop.services.append(ShopService(service_type=service_type, enabled=True))
        for paper_size, (grayscale, color) in DEMO_PRICES.items():
            shop.prices.extend(
                [
                    PrintPrice(paper_size=paper_size, color_mode=ColorMode.GRAYSCALE, price=Decimal(grayscale), is_demo=True),
                    PrintPrice(paper_size=paper_size, color_mode=ColorMode.COLOR, price=Decimal(color), is_demo=True),
                ]
            )
        for fee_type, amount in DEMO_FEES.items():
            if fee_type.value in {service.value for service in services}:
                shop.fees.append(ShopFee(fee_type=fee_type, amount=Decimal(amount), is_demo=True))
        added += 1
    db.session.commit()
    return added, coordinates_updated


DEMO_PROFESSORS = (
    ("Maria Santos", "maria.santos@example.edu", "Computer Engineering", "Engineering Building 204", True, True),
    ("Juan Dela Cruz", "juan.delacruz@example.edu", "Information Technology", "ICT Building 301", True, True),
    ("Ana Reyes", "ana.reyes@example.edu", "Electronics Engineering", "Engineering Building 105", True, False),
    ("Liza Navarro", "liza.navarro@example.edu", "Mathematics", "Science Building 102", False, True),
)


def seed_demo_professors() -> int:
    """Insert missing fictional professors; never change existing approvals."""
    added = 0
    for name, email, department, office, is_active, approved in DEMO_PROFESSORS:
        if db.session.scalar(select(Professor.id).where(Professor.email == email)):
            continue
        db.session.add(Professor(
            name=name, email=email, department=department, office=office,
            is_active=is_active, direct_send_approved=approved,
        ))
        added += 1
    db.session.commit()
    return added
