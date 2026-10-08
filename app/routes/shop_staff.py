"""Assigned-shop editing for staff accounts."""

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for
from decimal import Decimal, InvalidOperation
from io import BytesIO
from flask_login import current_user
from flask_wtf import FlaskForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.authorization import roles_required
from app.extensions import db
from app.models import ColorMode, FeeType, PaperSize, PrintPrice, ServiceType, ShopFee, ShopService, UserRole
from app.services.professors import PROFESSOR_DELIVERY_SHOP
from app.services.shop_photos import ShopPhotoError, normalize_shop_photo
from app.services.payment_qr import PaymentQRError, normalize_payment_qr
from app.shop_forms import FeeForm, PriceForm, ServiceForm, ShopPhotoForm, ShopStaffDetailsForm, ShopPaymentForm


shop_staff_bp = Blueprint("shop_staff", __name__, url_prefix="/shop/manage")


def assigned_shop():
    shop = current_user.shop
    if shop is None:
        abort(403)
    return shop


def editor(*, details_form=None, service_form=None, price_form=None, fee_form=None,
           photo_form=None, photo_error=None, payment_form=None, payment_error=None,
           price_values=None, price_errors=None, status=200):
    shop = assigned_shop()
    service_form = service_form or ServiceForm(formdata=None)
    if shop.name != PROFESSOR_DELIVERY_SHOP:
        service_form.service_type.choices = [
            choice for choice in service_form.service_type.choices
            if choice[0] != ServiceType.DIRECT_TO_PROFESSOR.value
        ]
    delivery_fee = next((fee for fee in shop.fees if fee.fee_type == FeeType.DELIVERY), None)
    delivery_fee_form = FeeForm(formdata=None, fee_type=FeeType.DELIVERY.value,
                               amount=delivery_fee.amount if delivery_fee else None)
    if fee_form is not None and fee_form.fee_type.data == FeeType.DELIVERY.value:
        delivery_fee_form, fee_form = fee_form, None
    fee_form = fee_form or FeeForm(formdata=None)
    fee_form.fee_type.choices = [choice for choice in fee_form.fee_type.choices
                               if choice[0] != FeeType.DELIVERY.value]
    price_map = {(price.paper_size, price.color_mode): price for price in shop.prices}
    service_map = {service.service_type: service for service in shop.services}
    service_types = [service_type for service_type in ServiceType
                     if service_type != ServiceType.DIRECT_TO_PROFESSOR
                     or shop.name == PROFESSOR_DELIVERY_SHOP]
    return render_template(
        "shops/manage.html", shop=shop,
        details_form=details_form or ShopStaffDetailsForm(formdata=None, obj=shop),
        service_form=service_form,
        price_form=price_form or PriceForm(formdata=None),
        bulk_price_form=FlaskForm(formdata=None),
        price_values=price_values or {}, price_errors=price_errors or {},
        fee_form=fee_form, delivery_fee_form=delivery_fee_form,
        delivery_enabled=any(service.service_type == ServiceType.DELIVERY and service.enabled
                             for service in shop.services),
        photo_form=photo_form or ShopPhotoForm(formdata=None),
        remove_photo_form=FlaskForm(), photo_error=photo_error,
        payment_form=payment_form or ShopPaymentForm(formdata=None, obj=shop),
        payment_error=payment_error,
        services=sorted(shop.services, key=lambda item: item.service_type.value),
        service_rows=[(service_type, service_map.get(service_type)) for service_type in service_types],
        prices=sorted(shop.prices, key=lambda item: (item.paper_size.value, item.color_mode.value)),
        price_rows=[(size, price_map.get((size, ColorMode.GRAYSCALE)),
                     price_map.get((size, ColorMode.COLOR))) for size in PaperSize],
        fees=sorted((fee for fee in shop.fees if fee.fee_type != FeeType.DELIVERY),
                    key=lambda item: item.fee_type.value),
    ), status


def commit_or_error(form, field_name):
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        getattr(form, field_name).errors.append("Unable to save this value.")
        return False
    return True


@shop_staff_bp.get("")
@roles_required(UserRole.SHOP_STAFF)
def index():
    return editor()


@shop_staff_bp.post("/details")
@roles_required(UserRole.SHOP_STAFF)
def save_details():
    shop = assigned_shop()
    form = ShopStaffDetailsForm()
    if form.validate_on_submit():
        shop.description = form.description.data or ""
        shop.address = form.address.data
        shop.opening_time = form.opening_time.data
        shop.closing_time = form.closing_time.data
        shop.is_demo = False
        if commit_or_error(form, "address"):
            flash("Shop details updated.", "success")
            return redirect(url_for("shop_staff.index"))
    return editor(details_form=form, status=400)


@shop_staff_bp.post("/services")
@roles_required(UserRole.SHOP_STAFF)
def save_service():
    shop = assigned_shop()
    form = ServiceForm()
    if shop.name != PROFESSOR_DELIVERY_SHOP:
        form.service_type.choices = [
            choice for choice in form.service_type.choices
            if choice[0] != ServiceType.DIRECT_TO_PROFESSOR.value
        ]
    if form.validate_on_submit():
        service_type = ServiceType(form.service_type.data)
        service = db.session.scalar(select(ShopService).where(
            ShopService.shop_id == shop.id, ShopService.service_type == service_type,
        ))
        if service is None:
            service = ShopService(shop=shop, service_type=service_type)
            db.session.add(service)
        service.enabled = bool(form.enabled.data)
        if commit_or_error(form, "service_type"):
            flash("Service updated.", "success")
            return redirect(url_for("shop_staff.index", _anchor="shop-services"))
    return editor(service_form=form, status=400)


@shop_staff_bp.post("/prices")
@roles_required(UserRole.SHOP_STAFF)
def save_price():
    shop = assigned_shop()
    form = PriceForm()
    if form.validate_on_submit():
        price = db.session.scalar(select(PrintPrice).where(
            PrintPrice.shop_id == shop.id,
            PrintPrice.paper_size == PaperSize(form.paper_size.data),
            PrintPrice.color_mode == ColorMode(form.color_mode.data),
        ))
        if price is None:
            price = PrintPrice(shop=shop, paper_size=PaperSize(form.paper_size.data),
                               color_mode=ColorMode(form.color_mode.data))
            db.session.add(price)
        price.price = form.price.data
        price.is_demo = False
        if commit_or_error(form, "price"):
            flash("Price updated.", "success")
            return redirect(url_for("shop_staff.index"))
    return editor(price_form=form, status=400)


@shop_staff_bp.post("/prices/bulk")
@roles_required(UserRole.SHOP_STAFF)
def save_prices_bulk():
    shop = assigned_shop()
    if not FlaskForm().validate_on_submit():
        abort(400)
    values = {}
    errors = {}
    for size in PaperSize:
        for mode in ColorMode:
            key = f"price_{size.value}_{mode.value}"
            raw = request.form.get(key)
            values[key] = raw if raw is not None else ""
            try:
                if raw is None or not raw.strip():
                    raise ValueError
                amount = Decimal(raw)
                if (not amount.is_finite() or amount < 0
                        or amount > Decimal("99999999.99")
                        or amount != amount.quantize(Decimal("0.01"))):
                    raise ValueError
                values[key] = amount
            except (InvalidOperation, ValueError):
                errors[key] = "Enter an amount from ₱0.00 to ₱99,999,999.99 with up to two decimals."
    if errors:
        return editor(price_values=values, price_errors=errors, status=400)
    existing = {(price.paper_size, price.color_mode): price for price in shop.prices}
    for size in PaperSize:
        for mode in ColorMode:
            price = existing.get((size, mode))
            if price is None:
                price = PrintPrice(shop=shop, paper_size=size, color_mode=mode)
                db.session.add(price)
            price.price = values[f"price_{size.value}_{mode.value}"]
            price.is_demo = False
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return editor(price_values=values,
                      price_errors={"all": "Unable to save prices. Please try again."}, status=400)
    flash("All print prices updated.", "success")
    return redirect(url_for("shop_staff.index", _anchor="shop-prices"))


@shop_staff_bp.post("/fees")
@roles_required(UserRole.SHOP_STAFF)
def save_fee():
    shop = assigned_shop()
    form = FeeForm()
    if form.validate_on_submit():
        fee = db.session.scalar(select(ShopFee).where(
            ShopFee.shop_id == shop.id, ShopFee.fee_type == FeeType(form.fee_type.data),
        ))
        if fee is None:
            fee = ShopFee(shop=shop, fee_type=FeeType(form.fee_type.data))
            db.session.add(fee)
        fee.amount = form.amount.data
        fee.is_demo = False
        if commit_or_error(form, "amount"):
            flash("Fee updated.", "success")
            return redirect(url_for("shop_staff.index", _anchor=(
                "delivery-settings" if fee.fee_type == FeeType.DELIVERY else "shop-fees"
            )))
    return editor(fee_form=form, status=400)


@shop_staff_bp.post("/photo")
@roles_required(UserRole.SHOP_STAFF)
def save_photo():
    shop = assigned_shop()
    form = ShopPhotoForm()
    if form.validate_on_submit():
        try:
            shop.photo_data, shop.photo_mime, shop.photo_digest = normalize_shop_photo(form.photo.data)
        except ShopPhotoError as error:
            return editor(photo_form=form, photo_error=str(error), status=400)
        db.session.commit()
        flash("Shop photo updated.", "success")
        return redirect(url_for("shop_staff.index"))
    return editor(photo_form=form, status=400)


@shop_staff_bp.post("/photo/remove")
@roles_required(UserRole.SHOP_STAFF)
def remove_photo():
    if not FlaskForm().validate_on_submit():
        abort(400)
    shop = assigned_shop()
    shop.photo_data = None
    shop.photo_mime = None
    shop.photo_digest = None
    db.session.commit()
    flash("Shop photo removed.", "success")
    return redirect(url_for("shop_staff.index"))


@shop_staff_bp.post("/payment")
@roles_required(UserRole.SHOP_STAFF)
def save_payment():
    shop = assigned_shop()
    form = ShopPaymentForm()
    if not form.validate_on_submit():
        return editor(payment_form=form, status=400)
    uploaded = form.payment_qr.data
    if uploaded and uploaded.filename:
        try:
            qr_data, qr_mime, qr_digest = normalize_payment_qr(uploaded)
        except PaymentQRError as error:
            return editor(payment_form=form, payment_error=str(error), status=400)
        shop.payment_qr_data = qr_data
        shop.payment_qr_mime = qr_mime
        shop.payment_qr_digest = qr_digest
    if form.online_enabled.data and not shop.payment_qr_digest:
        return editor(payment_form=form, payment_error="Upload a payment QR to enable online payment.", status=400)
    shop.cash_enabled = bool(form.cash_enabled.data)
    shop.online_enabled = bool(form.online_enabled.data)
    shop.online_account_name = form.online_account_name.data or ""
    if "online_account_reference" in request.form:
        shop.online_account_reference = form.online_account_reference.data or ""
    if "online_instructions" in request.form:
        shop.online_instructions = form.online_instructions.data or ""
    db.session.commit()
    flash("Payment settings updated.", "success")
    return redirect(url_for("shop_staff.index", _anchor="payment-settings"))


@shop_staff_bp.get("/payment/qr")
@roles_required(UserRole.SHOP_STAFF)
def payment_qr():
    shop = assigned_shop()
    if not shop.payment_qr_data:
        abort(404)
    response = send_file(BytesIO(shop.payment_qr_data), mimetype=shop.payment_qr_mime)
    response.headers["Cache-Control"] = "private, no-store"
    return response
