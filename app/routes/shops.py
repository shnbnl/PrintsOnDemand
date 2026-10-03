"""Ordering-account shop directory and read-only shop details."""

from flask import Blueprint, abort, current_app, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import Numeric, cast, select
from sqlalchemy.orm import selectinload

from app.authorization import roles_required
from app.extensions import db
from app.models import ColorMode, PaperSize, PrintConfiguration, PrintingShop, UploadedFile, UserRole
from app.services.fulfillment import availability
from app.services.professors import shop_supports_professor_delivery
from app.models import ServiceType


shops_bp = Blueprint("shops", __name__, url_prefix="/shops")
SCHOOL_AREA_CENTER = {"lat": 14.243375, "lng": 121.112716}


def detail_context(shop: PrintingShop) -> dict:
    prices = {(item.paper_size, item.color_mode): item for item in shop.prices}
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
        (item for item in shop.fees if item.fee_type.value in service_types),
        key=lambda item: item.fee_type.value,
    )
    return {"shop": shop, "price_rows": rows, "services": services, "fees": fees}


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
    return render_template("shops/index.html", shops=shops, query=query)


@shops_bp.get("/map")
@roles_required(UserRole.STUDENT, UserRole.PROFESSOR)
def map_view():
    """Discover only active shops with stored, valid coordinates."""
    query = request.args.get("q", "").strip()[:100]
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
            "description": shop.description,
            "address": shop.address,
            "hours": f"{shop.opening_time:%I:%M %p} - {shop.closing_time:%I:%M %p}",
            "services": [item.service_type.label for item in context["services"]],
            "fulfillment": [label for method, label in (
                ("PROFESSOR", "Direct-to-Professor"),
                ("PICKUP", "Scheduled Pickup"),
                ("DELIVERY", "Delivery"),
            ) if fulfillment[method]],
            "fees": [{
                "label": item.fee_type.label,
                "amount": f"₱{item.amount:.2f}",
                "is_demo": item.is_demo,
            } for item in context["fees"]],
            "prices": [{
                "size": row["size"].label,
                "grayscale": (
                    f"₱{row['grayscale'].price:.2f}"
                    f"{' (demo)' if row['grayscale'].is_demo else ''}"
                    if row["grayscale"] else "Not set"
                ),
                "color": (
                    f"₱{row['color'].price:.2f}"
                    f"{' (demo)' if row['color'].is_demo else ''}"
                    if row["color"] else "Not set"
                ),
            } for row in context["price_rows"]],
            "is_demo": shop.is_demo,
            "position": {"lat": float(shop.latitude), "lng": float(shop.longitude)},
            "detail_url": url_for("shops.detail", shop_id=shop.id),
        })
    return render_template(
        "shops/map.html", markers=markers, query=query,
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
    has_configured_file = db.session.scalar(
        select(UploadedFile.id)
        .join(PrintConfiguration, PrintConfiguration.file_id == UploadedFile.id)
        .where(UploadedFile.user_id == current_user.id)
        .limit(1)
    ) is not None
    return render_template("shops/detail.html", **detail_context(shop), can_order=has_configured_file)
