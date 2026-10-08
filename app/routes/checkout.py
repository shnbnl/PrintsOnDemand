"""Guided customer checkout built on the existing private-file and order services."""

from datetime import timedelta
from io import BytesIO

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, send_file, session, url_for
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
from app.security_limits import enforce_limit
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
            if saved.get("shop_id") != shop.id:
                for key in ("fulfillment", "payment_method", "payment_reference", "review"):
                    saved.pop(key, None)
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
    enforce_limit("file-upload", str(current_user.id), attempts=100, seconds=86400)
    asynchronous = request.headers.get("Accept") == "application/json"

    def upload_error(message, status):
        if asynchronous:
            return jsonify(error=message), status
        return render_upload(error=message, status=status)

    uploads = [file for file in request.files.getlist("files") if file.filename]
    saved = draft().copy()
    if not uploads or len(uploads) + len(saved["file_ids"]) > current_app.config["ORDER_MAX_FILES"]:
        return upload_error("Choose files within the order's file limit.", 400)
    try:
        validated = [validate_upload(file, current_app.config["UPLOAD_MAX_SIZE"]) for file in uploads]
    except UploadValidationError as error:
        return upload_error(str(error), error.status_code)
    try:
        storage = get_storage()
    except StorageError:
        if asynchronous:
            return jsonify(error="Private file storage is unavailable."), 503
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
                pdf_page_count=item.pdf_page_count,
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
        if asynchronous:
            return jsonify(error="Private file storage is unavailable."), 503
        abort(503, description="Private file storage is unavailable.")
    saved["file_ids"] = [*saved["file_ids"], *(record.id for record in records)]
    saved.pop("fulfillment", None)
    saved.pop("options", None)
    saved.pop("payment_method", None)
    saved.pop("payment_reference", None)
    saved.pop("review", None)
    save(saved)
    flash(f"{len(records)} {'file' if len(records) == 1 else 'files'} uploaded privately.", "success")
    if asynchronous:
        return jsonify(redirect=url_for("checkout.upload"))
    return redirect(url_for("checkout.upload"))


@checkout_bp.errorhandler(RequestEntityTooLarge)
def upload_too_large(error):
    if request.headers.get("Accept") == "application/json":
        return jsonify(error="The combined upload is too large. Add fewer files at a time."), 413
    return render_upload(error="The combined upload is too large. Add fewer files at a time.", status=413)


def print_options(files, saved):
    """Preserve saved per-file choices, with defaults for newly staged files."""
    raw = saved.get("options", {})
    return {file.id: PrintOptions(**raw[str(file.id)]) if str(file.id) in raw else PrintOptions(
        paper_size=file.configuration.paper_size.value if file.configuration else "A4",
        color_mode=file.configuration.color_mode.value if file.configuration else "GRAYSCALE",
        quantity=file.configuration.quantity if file.configuration else 1,
        is_rush=file.configuration.is_rush if file.configuration else False,
    ) for file in files}


def options_state(options):
    return {str(file_id): {
        "paper_size": choice.paper_size, "color_mode": choice.color_mode,
        "quantity": choice.quantity, "is_rush": choice.is_rush,
    } for file_id, choice in options.items()}


def submitted_options(files, values):
    values = values.copy()
    for file in files:
        key = f"print_choice_{file.id}"
        if key in values:
            choices = values.getlist(key)
            if len(choices) != 1 or len(choices[0].split(":")) != 2:
                raise PricingError("Select one valid price cell for each file.")
            paper, mode = choices[0].split(":")
            values.setlist(f"paper_size_{file.id}", [paper])
            values.setlist(f"color_mode_{file.id}", [mode])
    posted_ids, options = parse_files(values)
    if posted_ids != [file.id for file in files] or len(options) != len(files):
        raise PricingError("Complete the print settings for each selected file.")
    for file in files:
        choice = options[file.id]
        if not 1 <= choice.quantity <= current_app.config["UPLOAD_MAX_QUANTITY"]:
            raise PricingError("Print count is invalid.")
        if choice.paper_size not in PaperSize._value2member_map_ or choice.color_mode not in ColorMode._value2member_map_:
            raise PricingError("Print configuration is invalid.")
        if any(len(values.getlist(f"{key}_{file.id}")) > 1
               for key in ("paper_size", "color_mode", "quantity", "is_rush")):
            raise PricingError("Select one value for each print setting.")
    return options


def workspace_context(files, selected, options, *, error=None):
    from app.routes.shops import detail_context

    quote = None
    if selected:
        try:
            quote = quote_for([file.id for file in files], selected.id, options)
        except PricingError as issue:
            error = error or str(issue)
    return dict(files=files, shop=selected, options=options, error=error, preview_quote=quote,
                shop_details=detail_context(selected) if selected else None,
                rush_available=bool(selected and service_available(selected.id, ServiceType.RUSH_PRINTING)),
                paper_sizes=list(PaperSize), color_modes=list(ColorMode),
                max_quantity=current_app.config["UPLOAD_MAX_QUANTITY"])


def render_shop(*, error=None, status=200, options=None):
    from app.routes.shops import SCHOOL_AREA_CENTER, map_markers

    shops = db.session.scalars(select(PrintingShop).where(
        PrintingShop.is_active.is_(True),
    ).order_by(PrintingShop.name)).all()
    files = selected_files(draft()) or []
    selected = selected_shop(draft())
    context = workspace_context(files, selected, options or print_options(files, draft()), error=error)
    return render_template("checkout/shop.html", shops=shops, selected_shop_id=selected.id if selected else None,
                           markers=map_markers(), center=SCHOOL_AREA_CENTER,
                           maps_api_key=current_app.config["GOOGLE_MAPS_API_KEY"],
                           maps_map_id=current_app.config["GOOGLE_MAPS_MAP_ID"],
                           step=2, **context), status


@checkout_bp.route("/shop", methods=["GET", "POST"])
@roles_required(*ROLES)
def shop():
    saved = draft().copy()
    files = selected_files(saved)
    if files is None:
        return redirect(url_for("checkout.upload"))
    if request.method == "GET":
        if selected_shop(saved) is None:
            blue_and_silver = db.session.scalar(select(PrintingShop).where(
                PrintingShop.is_active.is_(True),
                PrintingShop.name == "Blue and Silver Bookstore",
            ))
            if blue_and_silver is not None:
                saved["shop_id"] = blue_and_silver.id
                save(saved)
        return render_shop()
    if not FlaskForm().validate_on_submit():
        abort(400)
    intent = request.form.get("intent", "proceed")
    asynchronous = request.headers.get("Accept") == "application/json"
    shop_id = positive_id(request.form.get("shop_id"))
    selected = db.session.get(PrintingShop, shop_id) if shop_id else None
    if selected is None or not selected.is_active or len(request.form.getlist("shop_id")) != 1:
        if asynchronous:
            return jsonify(error="Select an available printing shop."), 400
        return render_shop(error="Select an available printing shop.", status=400)
    if intent not in {"select", "quote", "preview", "proceed"}:
        abort(400)
    try:
        options = submitted_options(files, request.form)
    except PricingError as issue:
        if asynchronous:
            return jsonify(error=str(issue)), 400
        return render_shop(error=str(issue), status=400)
    if intent == "preview":
        if not asynchronous:
            abort(400)
        return jsonify(
            html=render_template("checkout/shop_workspace.html", **workspace_context(files, selected, options)),
            shop_id=selected.id,
        )
    changed_shop = saved.get("shop_id") != selected.id
    if intent == "select" and changed_shop and not service_available(selected.id, ServiceType.RUSH_PRINTING):
        options = {file_id: PrintOptions(choice.paper_size, choice.color_mode, choice.quantity, False)
                   for file_id, choice in options.items()}
    if intent == "quote":
        try:
            quote = quote_for(saved["file_ids"], selected.id, options)
        except PricingError as issue:
            return jsonify(error=str(issue)), issue.status_code
        return jsonify(total=str(quote.total), subtotal=str(quote.subtotal), rush_fee=str(quote.rush_fee), currency=quote.currency)
    if changed_shop or saved.get("options") != options_state(options):
        for key in ("fulfillment", "payment_method", "payment_reference", "review"):
            saved.pop(key, None)
    saved["shop_id"] = selected.id
    saved["options"] = options_state(options)
    save(saved)
    if intent == "select":
        if asynchronous:
            return jsonify(html=render_template("checkout/shop_workspace.html", **workspace_context(files, selected, options)), shop_id=selected.id)
        return redirect(url_for("checkout.shop"))
    try:
        quote_for(saved["file_ids"], selected.id, options)
        for file in files:
            choice = options[file.id]
            if file.configuration is None:
                db.session.add(PrintConfiguration(uploaded_file=file, paper_size=PaperSize(choice.paper_size),
                    color_mode=ColorMode(choice.color_mode), quantity=choice.quantity, is_rush=choice.is_rush))
            else:
                file.configuration.paper_size = PaperSize(choice.paper_size)
                file.configuration.color_mode = ColorMode(choice.color_mode)
                file.configuration.quantity = choice.quantity
                file.configuration.is_rush = choice.is_rush
        db.session.commit()
    except (PricingError, ValueError) as issue:
        db.session.rollback()
        return render_shop(error=str(issue), status=400, options=options)
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not save checkout print settings")
        return render_shop(error="Print settings could not be saved. Please try again.", status=503, options=options)
    return redirect(url_for("checkout.fulfillment"))


def render_fulfillment(shop, *, fields=None, error=None, status=200):
    offered = availability(shop)
    professors = (selectable_professors() if current_user.role == UserRole.STUDENT
                  and offered[OrderDestination.PROFESSOR.value] else [])
    own_professor = current_user.professor if professor_can_self_deliver(current_user) else None
    if (current_user.role == UserRole.STUDENT and not professors) or (
        current_user.role == UserRole.PROFESSOR and own_professor is None
    ):
        offered[OrderDestination.PROFESSOR.value] = False
    fields = fields or {}
    return render_template(
        "checkout/fulfillment.html", shop=shop,
        fields=fields, error=error, offered=offered,
        professors=professors, own_professor=own_professor,
        pickup_slots=slot_options(OrderDestination.PICKUP),
        delivery_slots=slot_options(OrderDestination.DELIVERY),
        pickup_min=(today() + timedelta(days=max(1, current_app.config["PICKUP_LEAD_DAYS"]))).isoformat(),
        pickup_max=(today() + timedelta(days=current_app.config["PICKUP_MAX_DAYS"])).isoformat(),
        delivery_min=(today() + timedelta(days=max(1, current_app.config["DELIVERY_LEAD_DAYS"]))).isoformat(),
        delivery_max=(today() + timedelta(days=current_app.config["DELIVERY_MAX_DAYS"])).isoformat(),
        step=3,
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


def current_quote(saved, *, verify_pdf=False):
    files = selected_files(saved)
    shop = selected_shop(saved)
    if files is None or shop is None or not saved.get("fulfillment"):
        raise FulfillmentError("Complete the Shop and Fulfillment steps first.")
    options = checkout_options(saved)
    preliminary = quote_for(saved["file_ids"], shop.id, options, verify_pdf=verify_pdf)
    fulfillment = validate_fulfillment(shop=shop, values=saved["fulfillment"], actor=current_user)
    quote = (quote_for(saved["file_ids"], shop.id, options, delivery_fee=fulfillment.delivery_fee,
                       delivery_fee_is_demo=fulfillment.delivery_fee_is_demo, verify_pdf=verify_pdf)
             if fulfillment.destination == OrderDestination.DELIVERY else preliminary)
    return quote, fulfillment


@checkout_bp.get("/configure")
@roles_required(*ROLES)
def configure():
    """Keep old bookmarks usable without retaining the old combined form."""
    return redirect(url_for("checkout.fulfillment"))


@checkout_bp.route("/fulfillment", methods=["GET", "POST"])
@roles_required(*ROLES)
def fulfillment():
    saved = draft().copy()
    files = selected_files(saved)
    if files is None:
        return redirect(url_for("checkout.upload"))
    shop = selected_shop(saved)
    if shop is None:
        return redirect(url_for("checkout.shop"))
    try:
        options = checkout_options(saved)
        quote_for(saved["file_ids"], shop.id, options)
    except PricingError:
        return redirect(url_for("checkout.shop"))
    if request.method == "GET":
        return render_fulfillment(shop, fields=saved.get("fulfillment"))
    if not FlaskForm().validate_on_submit():
        abort(400)
    try:
        fulfillment = validate_fulfillment(shop=shop, values=request.form, actor=current_user)
        if fulfillment.destination == OrderDestination.DELIVERY:
            quote_for(saved["file_ids"], shop.id, options, delivery_fee=fulfillment.delivery_fee,
                      delivery_fee_is_demo=fulfillment.delivery_fee_is_demo)
    except (PricingError, FulfillmentError, ValueError) as error:
        db.session.rollback()
        return render_fulfillment(shop, fields=request.form,
                             error=str(error), status=getattr(error, "status_code", 400))
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not validate checkout fulfillment")
        abort(500)
    saved["fulfillment"] = fulfillment.fields()
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
        return redirect(url_for("checkout.fulfillment"))
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
        return redirect(url_for("checkout.fulfillment"))
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
    enforce_limit("order-place", str(current_user.id), attempts=30, seconds=86400)
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
        return redirect(url_for("checkout.fulfillment"))
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
        return redirect(url_for("checkout.fulfillment"))
    except (SQLAlchemyError, RuntimeError):
        db.session.rollback()
        current_app.logger.exception("Could not create checkout order")
        abort(500)
    session.pop("checkout_draft", None)
    session["checkout_last_order"] = order.order_reference
    session["checkout_animate_success"] = order.order_reference
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
    play_order_transition = session.pop("checkout_animate_success", None) == reference
    return render_template("checkout/success.html", order=order,
                           play_order_transition=play_order_transition)
