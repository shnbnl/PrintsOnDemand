"""Validate and snapshot one requested order fulfillment method."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from flask import current_app
from sqlalchemy import select

from app.extensions import db
from app.models import FeeType, OrderDestination, PrintingShop, ServiceType, ShopFee, ShopService, UserRole
from app.services.pricing import PricingError, money
from app.services.professors import ProfessorSelectionError, professor_snapshot, professor_service_available, validate_professor_selection
from app.professor_faculties import ALL_FACULTIES


class FulfillmentError(ValueError):
    pass


FIELDS = ("destination", "professor_id", "professor_faculty", "pickup_date", "pickup_slot",
          "delivery_recipient_name", "delivery_recipient_phone", "delivery_address",
          "delivery_date", "delivery_slot")


@dataclass(frozen=True)
class Fulfillment:
    destination: OrderDestination
    professor_id: int | None = None
    professor_details: dict | None = None
    professor_recipient_type: str | None = None
    pickup_date: date | None = None
    pickup_slot: str | None = None
    delivery_recipient_name: str | None = None
    delivery_recipient_phone: str | None = None
    delivery_address: str | None = None
    delivery_date: date | None = None
    delivery_slot: str | None = None
    delivery_fee: Decimal = Decimal("0.00")
    delivery_fee_is_demo: bool = False

    def snapshot(self) -> dict:
        return {
            "destination": self.destination.value,
            "professor": self.professor_details,
            "professor_recipient_type": self.professor_recipient_type,
            "pickup_date": self.pickup_date.isoformat() if self.pickup_date else None,
            "pickup_slot": self.pickup_slot,
            "delivery_recipient_name": self.delivery_recipient_name,
            "delivery_recipient_phone": self.delivery_recipient_phone,
            "delivery_address": self.delivery_address,
            "delivery_date": self.delivery_date.isoformat() if self.delivery_date else None,
            "delivery_slot": self.delivery_slot,
            "delivery_fee": str(self.delivery_fee),
        }

    def fields(self) -> dict[str, str]:
        return {
            "destination": self.destination.value,
            "professor_id": str(self.professor_id or "") if self.professor_recipient_type != "SELF" else "",
            "professor_faculty": "",
            "pickup_date": self.pickup_date.isoformat() if self.pickup_date else "",
            "pickup_slot": self.pickup_slot or "",
            "delivery_recipient_name": self.delivery_recipient_name or "",
            "delivery_recipient_phone": self.delivery_recipient_phone or "",
            "delivery_address": self.delivery_address or "",
            "delivery_date": self.delivery_date.isoformat() if self.delivery_date else "",
            "delivery_slot": self.delivery_slot or "",
        }


def today() -> date:
    return datetime.now(ZoneInfo(current_app.config["FULFILLMENT_TIMEZONE"])).date()


def slot_options(method: OrderDestination) -> tuple[tuple[str, str], ...]:
    key = "PICKUP_TIME_SLOTS" if method == OrderDestination.PICKUP else "DELIVERY_TIME_SLOTS"
    options = []
    for value in current_app.config[key]:
        match = re.fullmatch(r"(\d{2}):(\d{2})-(\d{2}):(\d{2})", value)
        if not match:
            raise RuntimeError(f"Invalid configured {key} slot: {value!r}")
        start_hour, start_minute, end_hour, end_minute = map(int, match.groups())
        try:
            start = time(start_hour, start_minute)
            end = time(end_hour, end_minute)
        except ValueError as error:
            raise RuntimeError(f"Invalid configured {key} slot: {value!r}") from error
        if start >= end:
            raise RuntimeError(f"Invalid configured {key} slot: {value!r}")
        options.append((value, f"{start.strftime('%I:%M %p').lstrip('0')}–{end.strftime('%I:%M %p').lstrip('0')}"))
    return tuple(options)


def service_available(shop_id: int, service: ServiceType) -> bool:
    return db.session.scalar(select(ShopService.id).where(
        ShopService.shop_id == shop_id, ShopService.service_type == service,
        ShopService.enabled.is_(True),
    )) is not None


def delivery_fee_for(shop_id: int) -> tuple[Decimal, bool]:
    fee = db.session.scalar(select(ShopFee).where(
        ShopFee.shop_id == shop_id, ShopFee.fee_type == FeeType.DELIVERY
    ).execution_options(populate_existing=True))
    if fee is None:
        raise FulfillmentError("Delivery fee is not configured for this shop.")
    try:
        return money(fee.amount, "Delivery fee"), fee.is_demo
    except PricingError as error:
        raise FulfillmentError(str(error)) from error


def slot_fits_shop(shop: PrintingShop, value: str) -> bool:
    start_text, end_text = value.split("-")
    start, end = time.fromisoformat(start_text), time.fromisoformat(end_text)
    return shop.opening_time <= start < end <= shop.closing_time


def availability(shop: PrintingShop) -> dict[str, bool]:
    pickup = service_available(shop.id, ServiceType.PICKUP) and any(
        slot_fits_shop(shop, value) for value, _ in slot_options(OrderDestination.PICKUP)
    )
    delivery = service_available(shop.id, ServiceType.DELIVERY) and any(
        slot_fits_shop(shop, value) for value, _ in slot_options(OrderDestination.DELIVERY)
    )
    if delivery:
        try:
            delivery_fee_for(shop.id)
        except FulfillmentError:
            delivery = False
    return {
        OrderDestination.PROFESSOR.value: professor_service_available(shop.id),
        OrderDestination.PICKUP.value: pickup,
        OrderDestination.DELIVERY.value: delivery,
    }


def _scheduled(values: dict[str, str], prefix: str, shop: PrintingShop) -> tuple[date, str]:
    raw_date = values[f"{prefix}_date"]
    raw_slot = values[f"{prefix}_slot"]
    if not raw_date:
        raise FulfillmentError(f"Select a {prefix} date.")
    try:
        requested = date.fromisoformat(raw_date)
        if requested.isoformat() != raw_date:
            raise ValueError
    except ValueError as error:
        raise FulfillmentError(f"Select a valid {prefix} date.") from error
    start = today()
    lead = current_app.config[f"{prefix.upper()}_LEAD_DAYS"]
    window = current_app.config[f"{prefix.upper()}_MAX_DAYS"]
    minimum_lead = max(0 if prefix == "pickup" else 1, lead)
    if requested < start + timedelta(days=minimum_lead) or requested > start + timedelta(days=window):
        raise FulfillmentError(f"Select a {prefix} date within the available scheduling window.")
    try:
        valid_slots = dict(slot_options(OrderDestination.PICKUP if prefix == "pickup" else OrderDestination.DELIVERY))
    except RuntimeError:
        raise
    if raw_slot not in valid_slots:
        raise FulfillmentError(f"Select a valid {prefix} time slot.")
    if not slot_fits_shop(shop, raw_slot):
        raise FulfillmentError(f"That {prefix} time slot is outside this shop's operating hours.")
    return requested, raw_slot


def validate_fulfillment(*, shop: PrintingShop, values, actor=None) -> Fulfillment:
    """Accept only fields belonging to the selected method; price never comes from values."""
    if "delivery_fee" in values:
        raise FulfillmentError("Delivery fee must be calculated by the shop.")
    if hasattr(values, "getlist"):
        if any(len(values.getlist(field)) > 1 for field in FIELDS):
            raise FulfillmentError("Select exactly one fulfillment method and one value per field.")
    data = {field: (values.get(field) or "").strip() for field in FIELDS}
    try:
        destination = OrderDestination(data["destination"])
    except ValueError as error:
        raise FulfillmentError("Select a valid fulfillment method.") from error
    allowed = {
        OrderDestination.PROFESSOR: {"destination", "professor_id", "professor_faculty"},
        OrderDestination.PICKUP: {"destination", "pickup_date", "pickup_slot"},
        OrderDestination.DELIVERY: {"destination", "delivery_recipient_name", "delivery_recipient_phone",
                                    "delivery_address", "delivery_date", "delivery_slot"},
    }[destination]
    if any(data[field] for field in FIELDS if field not in allowed):
        raise FulfillmentError("Fulfillment details do not match the selected method.")
    if destination == OrderDestination.PROFESSOR:
        try:
            professor = validate_professor_selection(
                shop_id=shop.id, destination=destination, professor_id=data["professor_id"], actor=actor
            )
        except ProfessorSelectionError as error:
            raise FulfillmentError(str(error)) from error
        self_order = actor is not None and actor.role == UserRole.PROFESSOR
        if data["professor_faculty"]:
            raise FulfillmentError("Faculty is assigned by Blue and Silver and cannot be changed here.")
        faculty = professor.faculty
        if faculty not in ALL_FACULTIES:
            raise FulfillmentError("The managed professor profile needs a valid Faculty.")
        return Fulfillment(destination, professor.id, professor_snapshot(professor, faculty=faculty),
                           "SELF" if self_order else "STUDENT_SELECTED")
    service = ServiceType.PICKUP if destination == OrderDestination.PICKUP else ServiceType.DELIVERY
    if not service_available(shop.id, service):
        raise FulfillmentError(f"This shop does not offer {destination.label}.")
    if destination == OrderDestination.PICKUP:
        requested, slot = _scheduled(data, "pickup", shop)
        return Fulfillment(destination, pickup_date=requested, pickup_slot=slot)
    name, phone, address = (data["delivery_recipient_name"], data["delivery_recipient_phone"],
                            data["delivery_address"])
    if not 2 <= len(name) <= 120:
        raise FulfillmentError("Enter a recipient name (2–120 characters).")
    if not re.fullmatch(r"\+?[0-9][0-9 ()-]{6,30}", phone) or not 7 <= len(re.sub(r"\D", "", phone)) <= 15:
        raise FulfillmentError("Enter a valid recipient phone number.")
    if not 10 <= len(address) <= 500:
        raise FulfillmentError("Enter a delivery address (10–500 characters).")
    requested, slot = _scheduled(data, "delivery", shop)
    fee, is_demo = delivery_fee_for(shop.id)
    return Fulfillment(destination, delivery_recipient_name=name,
                       delivery_recipient_phone=phone, delivery_address=address,
                       delivery_date=requested, delivery_slot=slot,
                       delivery_fee=fee, delivery_fee_is_demo=is_demo)
