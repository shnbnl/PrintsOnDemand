"""Guided customer checkout built on the existing private-file and order services."""

from datetime import timedelta
from io import BytesIO

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, session, url_for
from flask_login import current_user
from flask_wtf import FlaskForm
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import RequestEntityTooLarge

from app.authorization import roles_required
from app.extensions import db
from app.models import (
    ColorMode, Order, OrderDestination, PaperSize, PrintConfiguration,
    PrintingShop, ServiceType, UploadedFile, UserRole,
)
from app.models.user import utc_now
from app.routes.orders import parse_files, positive_id, quote_for, review_state
from app.services.fulfillment import (
    FulfillmentError, availability, service_available, slot_options, today, validate_fulfillment,
)
from app.services.orders import create_order
from app.services.payments import (
    PaymentError, online_payment_details, validate_checkout_payment,
)
from app.services.pricing import PricingError, PrintOptions
from app.services.professors import professor_can_self_deliver, selectable_professors
from app.storage import StorageError, get_storage
from app.storage.validation import ALLOWED_EXTENSIONS, UploadValidationError, validate_upload


checkout_bp = Blueprint("checkout", __name__, url_prefix="/checkout")
ROLES = (UserRole.STUDENT, UserRole.PROFESSOR)


def draft() -> dict:
    saved = session.get("checkout_draft")
    if not isinstance(saved, dict) or saved.get("user_id") != current_user.id:
        saved = {"user_id": current_user.id, "file_ids": []}
        session["checkout_draft"] = saved
        session.pop("checkout_last_order", None)
    return saved


def save(saved: dict) -> None:
    session["checkout_draft"] = saved


def owned_files(file_ids: list[int]) -> list[UploadedFile] | None:
    if not file_ids or len(file_ids) > current_app.config["ORDER_MAX_FILES"] or len(set(file_ids)) != len(file_ids):
        return None
    cutoff = utc_now() - timedelta(hours=current_app.config["CHECKOUT_STAGED_RETENTION_HOURS"])
    records = db.session.scalars(select(UploadedFile).where(
        UploadedFile.user_id == current_user.id, UploadedFile.id.in_(file_ids),
        UploadedFile.checkout_staged_at > cutoff, ~UploadedFile.order_items.any(),
    )).all()
    by_id = {record.id: record for record in records}
    return [by_id[file_id] for file_id in file_ids] if len(by_id) == len(file_ids) else None


def selected_files(saved: dict):
    records = owned_files(saved.get("file_ids", []))
    return records if records is not None else None


def selected_shop(saved: dict):
    shop = db.session.get(PrintingShop, saved.get("shop_id")) if saved.get("shop_id") else None
    return shop if shop is not None and shop.is_active else None


def render_upload(*, error=None, status=200):
    saved = draft().copy()
    records = owned_files(saved.get("file_ids", [])) or []
    if len(records) != len(saved.get("file_ids", [])):
        saved["file_ids"] = [record.id for record in records]
        for key in ("options", "fulfillment", "payment_method", "payment_reference", "review"):
            saved.pop(key, None)
        save(saved)
    return render_template(
        "checkout/upload.html", records=records,
        error=error, max_files=current_app.config["ORDER_MAX_FILES"],
        extensions=ALLOWED_EXTENSIONS,
        accept_types=",".join(f".{ext}" for ext in sorted(ALLOWED_EXTENSIONS)),
        step=1,
    ), status


@checkout_bp.route("/upload", methods=["GET", "POST"])
@roles_required(*ROLES)
def upload():
    if request.method == "GET":
        from app.services.staged_uploads import cleanup_staged_uploads

        try:
            cleanup_staged_uploads(retention_hours=current_app.config["CHECKOUT_STAGED_RETENTION_HOURS"])
        except (OSError, StorageError, SQLAlchemyError):
            db.session.rollback()
            current_app.logger.exception("Could not clean up expired checkout uploads")
    saved = draft().copy()
    if request.method == "GET":
        shop_id = positive_id(request.args.get("shop_id"))
        shop = db.session.get(PrintingShop, shop_id) if shop_id else None
        if shop is not None and shop.is_active:
            saved["shop_id"] = shop.id
        save(saved)
        return render_upload()
    if not FlaskForm().validate_on_submit():
        abort(400)
    if "remove_file_id" in request.form:
        remove_id = positive_id(request.form.get("remove_file_id"))
        if remove_id not in saved.get("file_ids", []):
            abort(400)
        saved["file_ids"] = [value for value in saved["file_ids"] if value != remove_id]
        for key in ("options", "fulfillment", "payment_method", "payment_reference", "review"):
            saved.pop(key, None)
        save(saved)
        return redirect(url_for("checkout.upload"))
    raw_ids = request.form.getlist("file_id")
    file_ids = [positive_id(raw) for raw in raw_ids]
    if (any(file_id is None for file_id in file_ids)
            or not set(file_ids).issubset(set(saved.get("file_ids", [])))
            or (file_ids and owned_files(file_ids) is None)):
        return render_upload(error="Select one or more of your own files to continue.", status=400)
    if file_ids != saved.get("file_ids"):
        saved["file_ids"] = file_ids
        saved.pop("fulfillment", None)
        saved.pop("options", None)
        saved.pop("payment_method", None)
        saved.pop("payment_reference", None)
        saved.pop("review", None)
    save(saved)
    if not file_ids:
        return render_upload(error="Upload at least one file to continue.", status=400)
    return redirect(url_for("checkout.shop"))


@checkout_bp.post("/upload/files")
@roles_required(*ROLES)
def upload_files():
    if not FlaskForm().validate_on_submit():
        abort(400)
    uploads = [file for file in request.files.getlist("files") if file.filename]
    saved = draft().copy()
    if not uploads or len(uploads) + len(saved["file_ids"]) > current_app.config["ORDER_MAX_FILES"]:
        return render_upload(error="Choose files within the order's file limit.", status=400)
    try:
        validated = [validate_upload(file, current_app.config["UPLOAD_MAX_SIZE"]) for file in uploads]
    except UploadValidationError as error:
        return render_upload(error=str(error), status=error.status_code)
    try:
        storage = get_storage()
    except StorageError:
        abort(503, description="Private file storage is unavailable.")
    keys = []
    records = []
    try:
        for item in validated:
            key = storage.save(item.data, item.extension)
            keys.append(key)
            record = UploadedFile(
                user_id=current_user.id, original_filename=item.original_filename,
                stored_filename=key, storage_key=key, mime_type=item.mime_type,
                file_extension=item.extension, file_size=item.size, sha256=item.sha256,
                checkout_staged_at=utc_now(),
            )
            db.session.add(record)
            records.append(record)
        db.session.commit()
    except (OSError, StorageError, SQLAlchemyError):
        db.session.rollback()
        for key in keys:
            try:
                storage.delete(key)
            except (OSError, StorageError):
                current_app.logger.error("Could not remove failed checkout upload")
        current_app.logger.exception("Could not save checkout files")
        abort(503, description="Private file storage is unavailable.")
    saved["file_ids"] = [*saved["file_ids"], *(record.id for record in records)]
    saved.pop("fulfillment", None)
    saved.pop("options", None)
    saved.pop("payment_method", None)
    saved.pop("payment_reference", None)
    saved.pop("review", None)
    save(saved)
    flash(f"{len(records)} {'file' if len(records) == 1 else 'files'} uploaded privately.", "success")
    return redirect(url_for("checkout.upload"))


@checkout_bp.errorhandler(RequestEntityTooLarge)
def upload_too_large(error):
    return render_upload(error="The combined upload is too large. Add fewer files at a time.", status=413)


def render_shop(*, error=None, status=200):
    from app.routes.shops import SCHOOL_AREA_CENTER, map_markers

    shops = db.session.scalars(select(PrintingShop).where(
        PrintingShop.is_active.is_(True),
    ).order_by(PrintingShop.name)).all()
    return render_template("checkout/shop.html", shops=shops, selected_shop_id=draft().get("shop_id"),
                           markers=map_markers(), center=SCHOOL_AREA_CENTER,
                           maps_api_key=current_app.config["GOOGLE_MAPS_API_KEY"],
                           maps_map_id=current_app.config["GOOGLE_MAPS_MAP_ID"],
                           error=error, step=2), status


@checkout_bp.route("/shop", methods=["GET", "POST"])
@roles_required(*ROLES)
def shop():
    saved = draft().copy()
    if selected_files(saved) is None:
        return redirect(url_for("checkout.upload"))
    if request.method == "GET":
        return render_shop()
    if not FlaskForm().validate_on_submit():
        abort(400)
    shop_id = positive_id(request.form.get("shop_id"))
    selected = db.session.get(PrintingShop, shop_id) if shop_id else None
    if selected is None or not selected.is_active:
        return render_shop(error="Select an available printing shop.", status=400)
    if saved.get("shop_id") != selected.id:
        saved["shop_id"] = selected.id
        for key in ("fulfillment", "payment_method", "payment_reference", "review"):
            saved.pop(key, None)
    save(saved)
    return redirect(url_for("checkout.configure"))


def render_config(files, shop, *, options=None, fields=None, error=None, status=200):
    offered = availability(shop)
    professors = (selectable_professors() if current_user.role == UserRole.STUDENT
                  and offered[OrderDestination.PROFESSOR.value] else [])
    own_professor = current_user.professor if professor_can_self_deliver(current_user) else None
    if current_user.role == UserRole.PROFESSOR:
        offered[OrderDestination.DELIVERY.value] = False
    if (current_user.role == UserRole.STUDENT and not professors) or (
        current_user.role == UserRole.PROFESSOR and own_professor is None
    ):
        offered[OrderDestination.PROFESSOR.value] = False
    fields = fields or {}
    if options is None:
        try:
            options = checkout_options(draft())
        except PricingError:
            options = {}
    preview_quote = None
    if draft().get("fulfillment"):
        try:
            preview_quote, _ = current_quote(draft())
        except (PricingError, FulfillmentError):
            pass
    return render_template(
        "checkout/configure.html", files=files, shop=shop, options=options,
        fields=fields, error=error, offered=offered, preview_quote=preview_quote,
        rush_available=service_available(shop.id, ServiceType.RUSH_PRINTING),
        professors=professors, own_professor=own_professor,
        paper_sizes=list(PaperSize), color_modes=list(ColorMode),
        pickup_slots=slot_options(OrderDestination.PICKUP),
        delivery_slots=slot_options(OrderDestination.DELIVERY),
        pickup_min=(today() + timedelta(days=max(1, current_app.config["PICKUP_LEAD_DAYS"]))).isoformat(),
        pickup_max=(today() + timedelta(days=current_app.config["PICKUP_MAX_DAYS"])).isoformat(),
        delivery_min=(today() + timedelta(days=max(1, current_app.config["DELIVERY_LEAD_DAYS"]))).isoformat(),
        delivery_max=(today() + timedelta(days=current_app.config["DELIVERY_MAX_DAYS"])).isoformat(),
        max_quantity=current_app.config["UPLOAD_MAX_QUANTITY"], step=3,
    ), status


def checkout_options(saved):
    raw = saved.get("options")
    if not isinstance(raw, dict) or set(raw) != {str(value) for value in saved.get("file_ids", [])}:
        raise PricingError("Complete the print settings for each selected file.")
    try:
        return {int(key): PrintOptions(
            paper_size=value["paper_size"], color_mode=value["color_mode"],
            quantity=value["quantity"], is_rush=value["is_rush"],
        ) for key, value in raw.items()}
    except (TypeError, KeyError, ValueError) as error:
        raise PricingError("Print configuration is invalid.") from error


def current_quote(saved):
    files = selected_files(saved)
    shop = selected_shop(saved)
    if files is None or shop is None or not saved.get("fulfillment"):
        raise FulfillmentError("Complete the print configuration first.")
    options = checkout_options(saved)
    preliminary = quote_for(saved["file_ids"], shop.id, options)
    fulfillment = validate_fulfillment(shop=shop, values=saved["fulfillment"], actor=current_user)
    quote = (quote_for(saved["file_ids"], shop.id, options, delivery_fee=fulfillment.delivery_fee,
                       delivery_fee_is_demo=fulfillment.delivery_fee_is_demo)
             if fulfillment.destination == OrderDestination.DELIVERY else preliminary)
    return quote, fulfillment


@checkout_bp.route("/configure", methods=["GET", "POST"])
@roles_required(*ROLES)
def configure():
    saved = draft().copy()
    files = selected_files(saved)
    if files is None:
        return redirect(url_for("checkout.upload"))
    shop = selected_shop(saved)
    if shop is None:
        return redirect(url_for("checkout.shop"))
    if request.method == "GET":
        return render_config(files, shop, fields=saved.get("fulfillment"))
    if not FlaskForm().validate_on_submit():
        abort(400)
    try:
        posted_ids, options = parse_files(request.form)
        if posted_ids != saved["file_ids"] or len(options) != len(files):
            raise PricingError("Complete the print settings for each selected file.")
        for file in files:
            choice = options[file.id]
            if not 1 <= choice.quantity <= current_app.config["UPLOAD_MAX_QUANTITY"]:
                raise PricingError("Print count is invalid.")
            if file.configuration is None:
                db.session.add(PrintConfiguration(
                    uploaded_file=file, paper_size=PaperSize(choice.paper_size),
                    color_mode=ColorMode(choice.color_mode), quantity=choice.quantity,
                    is_rush=choice.is_rush,
                ))
        db.session.flush()
        preliminary = quote_for(saved["file_ids"], shop.id, options)
        fulfillment = validate_fulfillment(shop=shop, values=request.form, actor=current_user)
        if fulfillment.destination == OrderDestination.DELIVERY:
            quote_for(saved["file_ids"], shop.id, options, delivery_fee=fulfillment.delivery_fee,
                      delivery_fee_is_demo=fulfillment.delivery_fee_is_demo)
        db.session.commit()
    except (PricingError, FulfillmentError, ValueError) as error:
        db.session.rollback()
        return render_config(files, shop, options=locals().get("options"), fields=request.form,
                             error=str(error), status=getattr(error, "status_code", 400))
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not save checkout configuration")
        abort(500)
    saved["fulfillment"] = fulfillment.fields()
    saved["options"] = {str(file_id): {
        "paper_size": choice.paper_size, "color_mode": choice.color_mode,
        "quantity": choice.quantity, "is_rush": choice.is_rush,
    } for file_id, choice in options.items()}
    for key in ("payment_method", "payment_reference", "review"):
        saved.pop(key, None)
    save(saved)
    return redirect(url_for("checkout.payment"))


def render_payment(quote, fulfillment, *, error=None, status=200):
    online_details = online_payment_details(quote.shop)
    cash_available = quote.shop.cash_enabled and fulfillment.destination != OrderDestination.PROFESSOR
    chosen = request.form.get("payment_method") if request.method == "POST" else draft().get("payment_method")
    reference = request.form.get("payment_reference", "") if request.method == "POST" else draft().get("payment_reference", "")
    return render_template(
        "checkout/payment.html", quote=quote, fulfillment=fulfillment,
        error=error, chosen=chosen, reference=reference,
        online_details=online_details, cash_available=cash_available,
        no_method_available=not cash_available and online_details is None,
        step=4,
    ), status


@checkout_bp.get("/payment/qr")
@roles_required(*ROLES)
def payment_qr():
    saved = draft()
    shop = selected_shop(saved)
    if shop is None or selected_files(saved) is None or online_payment_details(shop) is None:
        abort(404)
    response = send_file(BytesIO(shop.payment_qr_data), mimetype=shop.payment_qr_mime)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@checkout_bp.route("/payment", methods=["GET", "POST"])
@roles_required(*ROLES)
def payment():
    saved = draft().copy()
    if selected_files(saved) is None:
        return redirect(url_for("checkout.upload"))
    if selected_shop(saved) is None:
        return redirect(url_for("checkout.shop"))
    try:
        quote, fulfillment = current_quote(saved)
    except (PricingError, FulfillmentError):
        return redirect(url_for("checkout.configure"))
    if request.method == "GET":
        return render_payment(quote, fulfillment)
    if not FlaskForm().validate_on_submit():
        abort(400)
    if len(request.form.getlist("payment_method")) != 1 or len(request.form.getlist("payment_reference")) > 1:
        return render_payment(quote, fulfillment, error="Select one valid payment method.", status=400)
    try:
        method, reference = validate_checkout_payment(
            shop=quote.shop,
            destination=fulfillment.destination,
            method=request.form.get("payment_method", ""),
            reference=request.form.get("payment_reference", ""),
        )
    except PaymentError as error:
        return render_payment(quote, fulfillment, error=str(error), status=error.status_code)
    saved["payment_method"] = method.value
    saved["payment_reference"] = reference or ""
    saved["review"] = review_state(quote, fulfillment)
    save(saved)
    return redirect(url_for("checkout.review"))


def render_review(quote, fulfillment, saved, *, warning=None, status=200):
    return render_template("checkout/review.html", quote=quote, fulfillment=fulfillment,
                           payment_method=saved["payment_method"],
                           payment_reference=saved.get("payment_reference"),
                           warning=warning, step=5), status


@checkout_bp.get("/review")
@roles_required(*ROLES)
def review():
    saved = draft().copy()
    if not saved.get("payment_method"):
        return redirect(url_for("checkout.payment"))
    try:
        quote, fulfillment = current_quote(saved)
        validate_checkout_payment(shop=quote.shop, destination=fulfillment.destination,
                                  method=saved["payment_method"],
                                  reference=saved.get("payment_reference", ""))
    except (PricingError, FulfillmentError, PaymentError):
        return redirect(url_for("checkout.configure"))
    current = review_state(quote, fulfillment)
    if saved.get("review") != current:
        saved["review"] = current
        save(saved)
        return render_review(quote, fulfillment, saved,
                             warning="Shop, price, or recipient details changed. Review the current order before placing it.",
                             status=409)
    return render_review(quote, fulfillment, saved)


@checkout_bp.post("/place")
@roles_required(*ROLES)
def place():
    if not FlaskForm().validate_on_submit():
        abort(400)
    if "checkout_draft" not in session:
        last = session.get("checkout_last_order")
        if last and db.session.scalar(select(Order.id).where(
            Order.order_reference == last, Order.user_id == current_user.id,
        )):
            return redirect(url_for("checkout.success", reference=last))
    saved = draft().copy()
    if not saved.get("payment_method"):
        return redirect(url_for("checkout.upload"))
    try:
        quote, fulfillment = current_quote(saved)
        validate_checkout_payment(shop=quote.shop, destination=fulfillment.destination,
                                  method=saved["payment_method"],
                                  reference=saved.get("payment_reference", ""))
    except (PricingError, FulfillmentError, PaymentError):
        return redirect(url_for("checkout.configure"))
    current = review_state(quote, fulfillment)
    if saved.get("review") != current:
        saved["review"] = current
        save(saved)
        return render_review(quote, fulfillment, saved,
                             warning="The order or price changed. Review it and place the order again.", status=409)
    try:
        order = create_order(quote, fulfillment=fulfillment,
                             payment_method=saved["payment_method"],
                             payment_reference=saved.get("payment_reference", ""))
    except (PaymentError, FulfillmentError):
        return redirect(url_for("checkout.configure"))
    except (SQLAlchemyError, RuntimeError):
        db.session.rollback()
        current_app.logger.exception("Could not create checkout order")
        abort(500)
    session.pop("checkout_draft", None)
    session["checkout_last_order"] = order.order_reference
    return redirect(url_for("checkout.success", reference=order.order_reference))


@checkout_bp.get("/success/<reference>")
@roles_required(*ROLES)
def success(reference):
    order = db.session.scalar(select(Order).where(
        Order.order_reference == reference, Order.user_id == current_user.id,
    ))
    if order is None:
        abort(404)
    if order.payment is None:
        return redirect(url_for("orders.detail", order_reference=reference))
    return render_template("checkout/success.html", order=order)
