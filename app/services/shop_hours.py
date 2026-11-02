"""Accept new orders only during the selected shop's local business hours."""

from datetime import datetime
from zoneinfo import ZoneInfo

from flask import current_app

from app.models import PrintingShop
from app.services.fulfillment import FulfillmentError


class ShopClosedError(FulfillmentError):
    status_code = 409


def local_now() -> datetime:
    return datetime.now(ZoneInfo(current_app.config["FULFILLMENT_TIMEZONE"]))


def is_open(shop: PrintingShop) -> bool:
    """Opening is inclusive, closing exclusive; support hours crossing midnight."""
    if not shop.is_active or shop.opening_time == shop.closing_time:
        return False
    now = local_now().time()
    if shop.opening_time < shop.closing_time:
        return shop.opening_time <= now < shop.closing_time
    return now >= shop.opening_time or now < shop.closing_time


def ordering_error(shop: PrintingShop) -> str | None:
    if is_open(shop):
        return None
    zone = current_app.config["FULFILLMENT_TIMEZONE"]
    zone_label = "Philippine time" if zone == "Asia/Manila" else zone
    return (
        f"{shop.name} is closed. Orders are accepted only from "
        f"{shop.opening_time:%I:%M %p} to {shop.closing_time:%I:%M %p} ({zone_label}). "
        "Please order during these hours or choose another shop."
    )


def validate_ordering_hours(shop: PrintingShop) -> None:
    error = ordering_error(shop)
    if error:
        raise ShopClosedError(error)
