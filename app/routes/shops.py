"""Ordering-account shop directory and read-only shop details."""

from io import BytesIO
from types import SimpleNamespace

from flask import Blueprint, abort, current_app, jsonify, render_template, request, send_file, url_for
from sqlalchemy import Numeric, cast, select
from sqlalchemy.orm import selectinload

from app.authorization import roles_required
from app.extensions import db
from app.models import ColorMode, PaperSize, PrintingShop, UserRole
from app.services.fulfillment import availability
from app.services.shop_hours import availability_status, ordering_error
from app.services.professors import shop_supports_professor_delivery
from app.models import ServiceType, FeeType


shops_bp = Blueprint("shops", __name__, url_prefix="/shops")
SCHOOL_AREA_CENTER = {"lat": 14.243375, "lng": 121.112716}
SHOP_DISPLAY_RATINGS = {
    "Blue and Silver Bookstore": 4.0,
    "Iced Design and Prints": 4.5,
    "CHALECOSPOT": 4.0,
    "Pixels Print and Press": 5.0,
}


def detail_context(shop: PrintingShop) -> dict:
    prices = {(item.paper_size, item.color_mode): item for item in shop.prices if item.price > 0}
    rows = [
        {
            "size": size,
            "grayscale": prices.get((size, ColorMode.GRAYSCALE)),
            "color": prices.get((size, ColorMode.COLOR)),
        }
        for size in PaperSize
    ]
    services = sorted(
        (item for item in shop.services if item.enabled and (
            item.service_type != ServiceType.DIRECT_TO_PROFESSOR
            or shop_supports_professor_delivery(shop))),
        key=lambda item: item.service_type.value,
    )
    service_types = {item.service_type.value for item in services}
    fees = sorted(
        (item for item in shop.fees if item.fee_type.value in service_types and item.fee_type != FeeType.RUSH_PRINTING),
        key=lambda item: item.fee_type.value,
    )
    if ServiceType.RUSH_PRINTING.value in service_types:
        fees.append(SimpleNamespace(fee_type=FeeType.RUSH_PRINTING, amount=20, is_demo=False))
    return {"shop": shop, "price_rows": rows, "price_map": prices, "services": services,
            "fees": fees, "shop_status": availability_status(shop)}


def active_shop_statement(query: str):
    statement = select(PrintingShop).where(PrintingShop.is_active.is_(True))
    if query:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(PrintingShop.name.ilike(f"%{escaped}%", escape="\\"))
    return statement


@shops_bp.get("")
@roles_required(UserRole.STUDENT, UserRole.PROFESSOR)
def index():
    query = request.args.get("q", "").strip()[:100]
    statement = active_shop_statement(query)
    shops = db.session.scalars(statement.order_by(PrintingShop.name)).all()
    return render_template("shops/index.html", shops=shops, query=query,
                           shop_statuses={shop.id: availability_status(shop) for shop in shops})


@shops_bp.get("/availability")
@roles_required(UserRole.STUDENT, UserRole.PROFESSOR, UserRole.SHOP_STAFF)
def live_availability():
    shops = db.session.scalars(select(PrintingShop).where(PrintingShop.is_active.is_(True))).all()
    response = jsonify(shops=[{
        "id": shop.id, **availability_status(shop), "ordering_error": ordering_error(shop),
    } for shop in shops])
    response.headers["Cache-Control"] = "private, no-store"
    return response


def map_markers(query: str = "") -> list[dict]:
    """Use one authoritative map payload for discovery and checkout."""
    statement = active_shop_statement(query).where(
        PrintingShop.latitude.is_not(None), PrintingShop.longitude.is_not(None),
        cast(PrintingShop.latitude, Numeric).between(-90, 90),
        cast(PrintingShop.longitude, Numeric).between(-180, 180),
    ).options(
        selectinload(PrintingShop.services), selectinload(PrintingShop.prices),
        selectinload(PrintingShop.fees),
    )
    shops = db.session.scalars(statement.order_by(PrintingShop.name)).all()
    markers = []
    for shop in shops:
        context = detail_context(shop)
        fulfillment = availability(shop)
        markers.append({
            "id": shop.id,
            "name": shop.name,
            "rating": SHOP_DISPLAY_RATINGS.get(shop.name),
            "description": shop.description,
            "address": shop.address,
            "hours": f"{shop.opening_time:%I:%M %p} - {shop.closing_time:%I:%M %p}",
            "availability": availability_status(shop),
            "services": [item.service_type.label for item in context["services"]],
            "fulfillment": [label for method, label in (
                ("PROFESSOR", "Direct-to-Professor"),
                ("PICKUP", "Scheduled Pickup"),
                ("DELIVERY", "Delivery"),
            ) if fulfillment[method]],
            "fees": [{
                "label": item.fee_type.label,
                "amount": "₱20.00 per order" if item.fee_type == FeeType.RUSH_PRINTING else f"₱{item.amount:.2f}",
                "is_sample": item.is_demo,
            } for item in context["fees"]],
            "prices": [{
                "size": row["size"].label,
                "grayscale": (
                    f"₱{row['grayscale'].price:.2f}"
                    if row["grayscale"] else "—"
                ),
                "color": (
                    f"₱{row['color'].price:.2f}"
                    if row["color"] else "—"
                ),
            } for row in context["price_rows"]],
            "is_sample": shop.is_demo,
            "position": {"lat": float(shop.latitude), "lng": float(shop.longitude)},
            "detail_url": url_for("shops.detail", shop_id=shop.id),
            "photo_url": (url_for("shops.photo", shop_id=shop.id, v=shop.photo_digest[:12])
                          if shop.photo_digest else None),
        })
    return markers


@shops_bp.get("/map")
@roles_required(UserRole.STUDENT, UserRole.PROFESSOR)
def map_view():
    """Discover only active shops with stored, valid coordinates."""
    query = request.args.get("q", "").strip()[:100]
    return render_template(
        "shops/map.html", markers=map_markers(query), query=query,
        center=SCHOOL_AREA_CENTER,
        maps_api_key=current_app.config["GOOGLE_MAPS_API_KEY"],
        maps_map_id=current_app.config["GOOGLE_MAPS_MAP_ID"],
        show_config_hint=current_app.config["ENV_NAME"] != "production",
    )


@shops_bp.get("/<int:shop_id>")
@roles_required(UserRole.STUDENT, UserRole.PROFESSOR)
def detail(shop_id: int):
    shop = db.session.get(PrintingShop, shop_id)
    if shop is None or not shop.is_active:
        abort(404)
    return render_template("shops/detail.html", **detail_context(shop))


@shops_bp.get("/<int:shop_id>/photo")
def photo(shop_id: int):
    shop = db.get_or_404(PrintingShop, shop_id)
    if not (shop.photo_digest and shop.photo_mime and shop.photo_data):
        abort(404)
    return send_file(
        BytesIO(shop.photo_data), mimetype=shop.photo_mime,
        as_attachment=False, etag=shop.photo_digest, max_age=3600,
    )
