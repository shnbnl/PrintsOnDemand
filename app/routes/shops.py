"""Student shop directory and read-only shop details."""

from flask import Blueprint, abort, render_template, request
from flask_login import current_user
from sqlalchemy import select

from app.authorization import roles_required
from app.extensions import db
from app.models import ColorMode, PaperSize, PrintConfiguration, PrintingShop, UploadedFile, UserRole


shops_bp = Blueprint("shops", __name__, url_prefix="/shops")


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
        (item for item in shop.services if item.enabled),
        key=lambda item: item.service_type.value,
    )
    service_types = {item.service_type.value for item in services}
    fees = sorted(
        (item for item in shop.fees if item.fee_type.value in service_types),
        key=lambda item: item.fee_type.value,
    )
    return {"shop": shop, "price_rows": rows, "services": services, "fees": fees}


@shops_bp.get("")
@roles_required(UserRole.STUDENT)
def index():
    query = request.args.get("q", "").strip()[:100]
    statement = select(PrintingShop).where(PrintingShop.is_active.is_(True))
    if query:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(PrintingShop.name.ilike(f"%{escaped}%", escape="\\"))
    shops = db.session.scalars(statement.order_by(PrintingShop.name)).all()
    return render_template("shops/index.html", shops=shops, query=query)


@shops_bp.get("/<int:shop_id>")
@roles_required(UserRole.STUDENT)
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
