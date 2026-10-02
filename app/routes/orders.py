"""Student-only order selection, quote review, creation, and detail."""

from flask import Blueprint, abort, current_app, redirect, render_template, request, session, url_for
from flask_login import current_user
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.authorization import roles_required
from app.extensions import db
from app.models import Order, PrintConfiguration, PrintingShop, UploadedFile, UserRole
from app.order_forms import PlaceOrderForm
from app.services.orders import create_order
from app.services.pricing import PricingError, quote_order


orders_bp = Blueprint("orders", __name__, url_prefix="/orders")


def positive_id(value: str | None) -> int | None:
    try:
        number = int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and number > 0 else None


def choices():
    files = db.session.scalars(
        select(UploadedFile)
        .join(PrintConfiguration, PrintConfiguration.file_id == UploadedFile.id)
        .where(UploadedFile.user_id == current_user.id)
        .order_by(UploadedFile.created_at.desc(), UploadedFile.id.desc())
    ).all()
    shops = db.session.scalars(
        select(PrintingShop).where(PrintingShop.is_active.is_(True))
        .order_by(PrintingShop.name)
    ).all()
    return files, shops


def quote_for(file_id: int, shop_id: int):
    return quote_order(
        user_id=current_user.id,
        file_id=file_id,
        shop_id=shop_id,
        max_quantity=current_app.config["UPLOAD_MAX_QUANTITY"],
        currency=current_app.config["ORDER_CURRENCY"],
    )


def render_selection(*, file_id=None, shop_id=None, error=None, status=200):
    files, shops = choices()
    return render_template(
        "orders/new.html", files=files, shops=shops,
        selected_file_id=file_id, selected_shop_id=shop_id, error=error,
    ), status


def render_review(quote, *, warning=None, status=200):
    form = PlaceOrderForm(formdata=None)
    form.file_id.data = str(quote.uploaded_file.id)
    form.shop_id.data = str(quote.shop.id)
    return render_template("orders/review.html", quote=quote, form=form, warning=warning), status


@orders_bp.get("/new")
@roles_required(UserRole.STUDENT)
def new():
    raw_file = request.args.get("file_id")
    raw_shop = request.args.get("shop_id")
    file_id, shop_id = positive_id(raw_file), positive_id(raw_shop)
    if (raw_file and file_id is None) or (raw_shop and shop_id is None):
        return render_selection(error="Select a valid file and printing shop.", status=400)
    if file_id is None or shop_id is None:
        return render_selection(file_id=file_id, shop_id=shop_id)
    try:
        quote = quote_for(file_id, shop_id)
    except PricingError as error:
        return render_selection(
            file_id=file_id, shop_id=shop_id, error=str(error), status=error.status_code
        )
    session["order_quote"] = {
        "file_id": file_id, "shop_id": shop_id, "fingerprint": quote.fingerprint,
    }
    return render_review(quote)


@orders_bp.post("/create")
@roles_required(UserRole.STUDENT)
def create():
    form = PlaceOrderForm()
    if not form.validate_on_submit():
        return render_selection(error="Review a valid order before submitting.", status=400)
    file_id, shop_id = positive_id(form.file_id.data), positive_id(form.shop_id.data)
    if file_id is None or shop_id is None:
        return render_selection(error="Select a valid file and printing shop.", status=400)
    try:
        quote = quote_for(file_id, shop_id)
    except PricingError as error:
        return render_selection(
            file_id=file_id, shop_id=shop_id, error=str(error), status=error.status_code
        )
    reviewed = session.get("order_quote")
    if reviewed != {
        "file_id": file_id, "shop_id": shop_id, "fingerprint": quote.fingerprint,
    }:
        session["order_quote"] = {
            "file_id": file_id, "shop_id": shop_id, "fingerprint": quote.fingerprint,
        }
        return render_review(
            quote, warning="The order or price changed. Review the current total and place the order again.",
            status=409,
        )
    try:
        order = create_order(quote)
    except (SQLAlchemyError, RuntimeError):
        db.session.rollback()
        current_app.logger.exception("Could not create order")
        abort(500)
    session.pop("order_quote", None)
    return redirect(url_for("orders.detail", order_reference=order.order_reference))


@orders_bp.get("/<order_reference>")
@roles_required(UserRole.STUDENT)
def detail(order_reference: str):
    order = db.session.scalar(
        select(Order).where(
            Order.order_reference == order_reference, Order.user_id == current_user.id
        )
    )
    if order is None:
        abort(404)
    return render_template("orders/detail.html", order=order)
