"""Owner-only order selection, quote review, creation, and detail."""

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, session, url_for
from io import BytesIO
from flask_login import current_user
from datetime import timedelta
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload

from app.authorization import roles_required
from app.extensions import db
from app.models import (
    Order, OrderDestination, OrderItem, OrderStatus, Payment, PaymentMethod, PaymentStatus,
    ColorMode, PaperSize, PrintConfiguration, PrintingShop, UploadedFile, UserRole,
)
from app.order_forms import PlaceOrderForm, SelectProfessorForm
from app.payment_forms import PaymentMethodForm, PaymentReferenceForm
from app.services.orders import create_order
from app.services.order_processing import ProcessingError, complete_customer_order, customer_can_complete
from app.services.fulfillment import (
    FIELDS, FulfillmentError, availability, slot_options, today, validate_fulfillment,
)
from app.services.payments import (
    PaymentError, online_payment_details, owned_order,
    select_payment_method, submit_online_reference,
)
from app.services.pricing import PricingError, PrintOptions, quote_cart
from app.services.professors import (
    ProfessorSelectionError, assign_professor, professor_service_available,
    professor_can_self_deliver, selectable_professors, validate_professor_selection,
)
from app.services.tracking import build_tracking


orders_bp = Blueprint("orders", __name__, url_prefix="/orders")
ORDERING_ROLES = (UserRole.STUDENT, UserRole.PROFESSOR)
HISTORY_PAGE_SIZE = 20
MAX_DATABASE_ID = 2**63 - 1
MAX_HISTORY_PAGE = MAX_DATABASE_ID // HISTORY_PAGE_SIZE


@orders_bp.get("")
@roles_required(*ORDERING_ROLES)
def index():
    """Show the signed-in student's stored orders, newest first."""
    status = request.args.get("status", "").strip()
    payment_status = request.args.get("payment_status", "").strip()
    raw_page = request.args.get("page", "1")
    if status and status not in OrderStatus.__members__:
        abort(400)
    if payment_status and payment_status not in PaymentStatus.__members__ and payment_status != "NONE":
        abort(400)
    try:
        page = int(raw_page)
    except ValueError:
        abort(400)
    if not 1 <= page <= MAX_HISTORY_PAGE:
        abort(400)

    statement = select(Order).where(Order.user_id == current_user.id)
    if status:
        statement = statement.where(Order.status == OrderStatus[status])
    if payment_status == "NONE":
        statement = statement.outerjoin(Order.payment).where(Payment.id.is_(None))
    elif payment_status:
        statement = statement.join(Order.payment).where(
            Payment.payment_status == PaymentStatus[payment_status]
        )
    statement = statement.options(selectinload(Order.payment), selectinload(Order.shop)).order_by(
        Order.created_at.desc(), Order.id.desc()
    )
    orders = db.paginate(statement, page=page, per_page=HISTORY_PAGE_SIZE, error_out=False)
    return render_template(
        "orders/index.html", orders=orders, status=status, payment_status=payment_status,
        completable_ids={order.id for order in orders.items if customer_can_complete(order)},
        order_statuses=OrderStatus, payment_statuses=PaymentStatus,
    )


def positive_id(value: str | None) -> int | None:
    try:
        number = int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and 0 < number <= MAX_DATABASE_ID else None


def choices():
    files = db.session.scalars(
        select(UploadedFile)
        .join(PrintConfiguration, PrintConfiguration.file_id == UploadedFile.id)
        .where(
            UploadedFile.user_id == current_user.id,
            PrintConfiguration.paper_size.in_(list(PaperSize)),
            PrintConfiguration.color_mode.in_(list(ColorMode)),
            PrintConfiguration.quantity.between(1, current_app.config["UPLOAD_MAX_QUANTITY"]),
        )
        .options(selectinload(UploadedFile.configuration))
        .order_by(UploadedFile.created_at.desc(), UploadedFile.id.desc())
    ).all()
    shops = db.session.scalars(
        select(PrintingShop).where(PrintingShop.is_active.is_(True))
        .order_by(PrintingShop.name)
    ).all()
    return files, shops


def quote_for(file_ids: list[int], shop_id: int, options: dict[int, PrintOptions],
              *, delivery_fee=None, delivery_fee_is_demo=False, verify_pdf=False):
    from decimal import Decimal
    return quote_cart(
        user_id=current_user.id,
        file_ids=file_ids,
        shop_id=shop_id,
        max_quantity=current_app.config["UPLOAD_MAX_QUANTITY"],
        max_files=current_app.config["ORDER_MAX_FILES"],
        currency=current_app.config["ORDER_CURRENCY"],
        options=options,
        delivery_fee=delivery_fee if delivery_fee is not None else Decimal("0.00"),
        delivery_fee_is_demo=delivery_fee_is_demo,
        verify_pdf=verify_pdf,
    )


def parse_files(values):
    """Read repeated file IDs and independent settings from GET or POST data."""
    file_ids = []
    options = {}
    for raw in values.getlist("file_id"):
        file_id = positive_id(raw)
        if file_id is None:
            raise PricingError("Select a valid file.")
        file_ids.append(file_id)
    if len(file_ids) > current_app.config["ORDER_MAX_FILES"]:
        raise PricingError(
            f"Select no more than {current_app.config['ORDER_MAX_FILES']} files per order."
        )
    if len(set(file_ids)) != len(file_ids):
        raise PricingError("Select each file only once per order.")
    for file_id in file_ids:
        names = {key: f"{key}_{file_id}" for key in ("paper_size", "color_mode", "quantity", "is_rush")}
        if not any(name in values for name in names.values()):
            continue  # Existing one-file links use the saved library configuration.
        if any(names[key] not in values for key in ("paper_size", "color_mode", "quantity")):
            raise PricingError("Complete the print settings for each selected file.")
        raw_quantity = values.get(names["quantity"], "")
        if (not raw_quantity.isdecimal()
                or len(raw_quantity) > len(str(current_app.config["UPLOAD_MAX_QUANTITY"]))):
            raise PricingError("Print count is invalid.")
        raw_rush = values.get(names["is_rush"])
        if raw_rush not in (None, "1"):
            raise PricingError("Rush printing selection is invalid.")
        options[file_id] = PrintOptions(
            paper_size=values.get(names["paper_size"], ""),
            color_mode=values.get(names["color_mode"], ""),
            quantity=int(raw_quantity), is_rush=raw_rush == "1",
        )
    return file_ids, options


def render_selection(*, file_ids=None, shop_id=None, destination=None, professor_id=None,
                     options=None, fulfillment_fields=None, error=None, status=200):
    files, shops = choices()
    professors = selectable_professors() if current_user.role == UserRole.STUDENT else []
    shop_availability = {shop.id: availability(shop) for shop in shops}
    if (not professors and current_user.role == UserRole.STUDENT) or (
        current_user.role == UserRole.PROFESSOR and not professor_can_self_deliver(current_user)
    ):
        for offered in shop_availability.values():
            offered[OrderDestination.PROFESSOR.value] = False
    selected_order = {file_id: index for index, file_id in enumerate(file_ids or [])}
    files.sort(key=lambda file: (0, selected_order[file.id]) if file.id in selected_order else (1, 0))
    return render_template(
        "orders/new.html", files=files, shops=shops,
        professors=professors, selected_file_ids=set(file_ids or []),
        own_professor=current_user.professor if professor_can_self_deliver(current_user) else None,
        selected_shop_id=shop_id, selected_destination=destination,
        selected_professor_id=professor_id, selected_options=options or {},
        fulfillment_fields=fulfillment_fields or {},
        shop_availability=shop_availability,
        pickup_slots=slot_options(OrderDestination.PICKUP),
        delivery_slots=slot_options(OrderDestination.DELIVERY),
        pickup_min=(today() + timedelta(days=max(0, current_app.config["PICKUP_LEAD_DAYS"]))).isoformat(),
        pickup_max=(today() + timedelta(days=current_app.config["PICKUP_MAX_DAYS"])).isoformat(),
        delivery_min=(today() + timedelta(days=max(1, current_app.config["DELIVERY_LEAD_DAYS"]))).isoformat(),
        delivery_max=(today() + timedelta(days=current_app.config["DELIVERY_MAX_DAYS"])).isoformat(),
        paper_sizes=PaperSize, color_modes=ColorMode,
        max_quantity=current_app.config["UPLOAD_MAX_QUANTITY"],
        max_files=current_app.config["ORDER_MAX_FILES"], error=error,
    ), status


def review_state(quote, fulfillment):
    return {
        "file_ids": [item.uploaded_file.id for item in quote.items],
        "shop_id": quote.shop.id,
        "fingerprint": quote.fingerprint, "fulfillment": fulfillment.snapshot(),
    }


def selection_url(quote, fulfillment, *, remove_file_id=None):
    items = [item for item in quote.items if item.uploaded_file.id != remove_file_id]
    args = {
        "edit": "1", "file_id": [item.uploaded_file.id for item in items],
        "shop_id": quote.shop.id,
    }
    for item in items:
        suffix = f"_{item.uploaded_file.id}"
        args[f"paper_size{suffix}"] = item.paper_size.value
        args[f"color_mode{suffix}"] = item.color_mode.value
        args[f"quantity{suffix}"] = item.quantity
        if item.is_rush:
            args[f"is_rush{suffix}"] = "1"
    return url_for("orders.new", **args)


def render_review(quote, *, fulfillment, warning=None, status=200):
    form = PlaceOrderForm(formdata=None)
    form.file_id.data = str(quote.items[0].uploaded_file.id)
    form.shop_id.data = str(quote.shop.id)
    for field, value in fulfillment.fields().items():
        getattr(form, field).data = value
    return render_template(
        "orders/review.html", quote=quote, form=form, fulfillment=fulfillment,
        warning=warning, selection_url=selection_url(quote, fulfillment),
        remove_urls={item.uploaded_file.id: selection_url(
            quote, fulfillment, remove_file_id=item.uploaded_file.id,
        ) for item in quote.items},
    ), status


@orders_bp.route("/new", methods=["GET", "POST"])
@roles_required(*ORDERING_ROLES)
def new():
    previous_review = session.pop("order_quote", None)
    values = request.form if request.method == "POST" else request.args
    raw_shop = values.get("shop_id")
    fulfillment_fields = {field: values.get(field, "") for field in FIELDS}
    if values.get("edit") == "1" and previous_review:
        saved = previous_review.get("fulfillment") or {}
        for field in FIELDS:
            fulfillment_fields[field] = saved.get(field) or ""
        fulfillment_fields["professor_id"] = (str((saved.get("professor") or {}).get("id") or "")
                                              if current_user.role == UserRole.STUDENT else "")
        fulfillment_fields["professor_faculty"] = ((saved.get("professor") or {}).get("faculty") or ""
                                                    if current_user.role == UserRole.PROFESSOR else "")
    destination = fulfillment_fields["destination"] or None
    professor_id = fulfillment_fields["professor_id"] or None
    shop_id = positive_id(raw_shop)
    try:
        file_ids, options = parse_files(values)
    except PricingError as error:
        return render_selection(error=str(error), status=error.status_code)
    if raw_shop and shop_id is None:
        return render_selection(file_ids=file_ids, options=options,
                                error="Select a valid printing shop.", status=400)
    if values.get("edit") == "1" or not file_ids or shop_id is None:
        error = "Select at least one file for this order." if values.get("review") == "1" and not file_ids else None
        return render_selection(
            file_ids=file_ids, shop_id=shop_id, options=options,
            destination=destination, professor_id=professor_id,
            fulfillment_fields=fulfillment_fields,
            error=error, status=400 if error else 200,
        )
    try:
        preliminary = quote_for(file_ids, shop_id, options)
        if request.method == "GET" and "destination" not in values:
            return render_selection(
                file_ids=file_ids, shop_id=shop_id, options=options,
                fulfillment_fields=fulfillment_fields,
            )
        shop = preliminary.shop
        fulfillment = validate_fulfillment(shop=shop, values=values, actor=current_user)
        quote = (quote_for(file_ids, shop_id, options, delivery_fee=fulfillment.delivery_fee,
                           delivery_fee_is_demo=fulfillment.delivery_fee_is_demo)
                 if fulfillment.destination == OrderDestination.DELIVERY else preliminary)
    except PricingError as error:
        return render_selection(
            file_ids=file_ids, shop_id=shop_id, options=options,
            error=str(error), status=error.status_code,
        )
    except FulfillmentError as error:
        return render_selection(
            file_ids=file_ids, shop_id=shop_id, options=options,
            destination=destination, professor_id=professor_id,
            fulfillment_fields=fulfillment_fields,
            error=str(error), status=400,
        )
    session["order_quote"] = review_state(quote, fulfillment)
    return render_review(quote, fulfillment=fulfillment)


@orders_bp.post("/create")
@roles_required(*ORDERING_ROLES)
def create():
    form = PlaceOrderForm()
    if not form.validate_on_submit():
        return render_selection(error="Review a valid order before submitting.", status=400)
    shop_id = positive_id(form.shop_id.data)
    try:
        file_ids, options = parse_files(request.form)
    except PricingError as error:
        return render_selection(error=str(error), status=error.status_code)
    if not file_ids:
        return render_selection(error="Select at least one file for this order.", status=400)
    if shop_id is None:
        return render_selection(file_ids=file_ids, options=options,
                                error="Select a valid printing shop.", status=400)
    try:
        preliminary = quote_for(file_ids, shop_id, options)
        shop = preliminary.shop
        fulfillment = validate_fulfillment(shop=shop, values=request.form, actor=current_user)
        quote = (quote_for(file_ids, shop_id, options, delivery_fee=fulfillment.delivery_fee,
                           delivery_fee_is_demo=fulfillment.delivery_fee_is_demo)
                 if fulfillment.destination == OrderDestination.DELIVERY else preliminary)
    except PricingError as error:
        return render_selection(
            file_ids=file_ids, shop_id=shop_id, options=options,
            error=str(error), status=error.status_code,
        )
    except FulfillmentError as error:
        return render_selection(
            file_ids=file_ids, shop_id=shop_id, options=options,
            destination=form.destination.data, professor_id=form.professor_id.data,
            fulfillment_fields={field: request.form.get(field, "") for field in FIELDS},
            error=str(error), status=400,
        )
    reviewed = session.get("order_quote")
    current_review = review_state(quote, fulfillment)
    if reviewed != current_review:
        session["order_quote"] = current_review
        return render_review(
            quote, fulfillment=fulfillment,
            warning="The order or price changed, including any professor details. Review the current details and place the order again.",
            status=409,
        )
    try:
        order = create_order(quote, fulfillment=fulfillment)
    except (ProfessorSelectionError, FulfillmentError) as error:
        return render_selection(
            file_ids=file_ids, shop_id=shop_id, options=options,
            destination=form.destination.data, professor_id=form.professor_id.data,
            fulfillment_fields={field: request.form.get(field, "") for field in FIELDS},
            error=str(error), status=400,
        )
    except (SQLAlchemyError, RuntimeError):
        db.session.rollback()
        current_app.logger.exception("Could not create order")
        abort(500)
    session.pop("order_quote", None)
    return redirect(url_for("orders.detail", order_reference=order.order_reference))


@orders_bp.get("/<order_reference>")
@roles_required(*ORDERING_ROLES)
def detail(order_reference: str):
    order = db.session.scalar(
        select(Order).where(
            Order.order_reference == order_reference, Order.user_id == current_user.id
        )
    )
    if order is None:
        abort(404)
    return render_order_detail(order)


@orders_bp.post("/<order_reference>/complete")
@roles_required(*ORDERING_ROLES)
def complete(order_reference: str):
    try:
        complete_customer_order(current_user, order_reference)
    except ProcessingError as error:
        abort(error.status_code, description=error.message)
    flash("Order completed. Thank you for confirming receipt.", "success")
    return redirect(url_for("orders.detail", order_reference=order_reference))


@orders_bp.get("/<order_reference>/files/<int:item_id>/download")
@roles_required(*ORDERING_ROLES)
def download_file(order_reference: str, item_id: int):
    """Read a private attachment only through its owner's actual order."""
    from app.routes.files import send_private_file

    item = db.session.scalar(select(OrderItem).join(Order).where(
        Order.order_reference == order_reference, Order.user_id == current_user.id,
        OrderItem.id == item_id,
    ))
    if item is None:
        abort(404)
    return send_private_file(item.uploaded_file)


def render_order_detail(order, *, payment_error=None, professor_error=None, status=200):
    online_details = online_payment_details(order.shop)
    method_form = None
    if order.status == OrderStatus.PENDING_PAYMENT and order.payment is None:
        method_form = PaymentMethodForm()
        method_form.payment_method.choices = ([] if order.destination == OrderDestination.PROFESSOR or not order.shop.cash_enabled
                                              else [(PaymentMethod.ONSITE.value, "Onsite payment")])
        if online_details is not None:
            method_form.payment_method.choices.append((PaymentMethod.ONLINE.value, "Online payment"))
        if not method_form.payment_method.choices:
            method_form = None
        if request.method == "GET" and order.payment is not None:
            method_form.payment_method.data = order.payment.payment_method.value
    reference_form = None
    if (
        order.payment is not None
        and order.payment.payment_method == PaymentMethod.ONLINE
        and order.payment.payment_status == PaymentStatus.PENDING
        and online_details is not None
    ):
        reference_form = PaymentReferenceForm()
    return render_template(
        "orders/detail.html", order=order, professor_form=professor_form(order),
        can_complete=customer_can_complete(order),
        method_form=method_form, reference_form=reference_form,
        online_details=online_details,
        payment_qr_image_url=url_for("orders.payment_qr", order_reference=order.order_reference) if online_details else None,
        payment_error=payment_error,
        professor_error=professor_error,
        onsite_instructions="Pay at the printing shop with your order reference. Your payment remains pending until staff records it.",
        tracking=build_tracking(order),
    ), status


@orders_bp.post("/<order_reference>/payment")
@roles_required(*ORDERING_ROLES)
def choose_payment(order_reference: str):
    try:
        order = owned_order(order_reference, current_user.id)
    except PaymentError:
        abort(404)
    form = PaymentMethodForm()
    form.payment_method.choices = ([] if order.destination == OrderDestination.PROFESSOR or not order.shop.cash_enabled
                                   else [(PaymentMethod.ONSITE.value, "Onsite payment")])
    if online_payment_details(order.shop) is not None:
        form.payment_method.choices.append((PaymentMethod.ONLINE.value, "Online payment"))
    if not form.validate_on_submit():
        return render_order_detail(order, payment_error="Select a valid payment method.", status=400)
    try:
        select_payment_method(
            order_reference=order_reference, user_id=current_user.id,
            method=form.payment_method.data,
        )
    except PaymentError as error:
        if error.status_code == 404:
            abort(404)
        return render_order_detail(order, payment_error=str(error), status=error.status_code)
    return redirect(url_for("orders.detail", order_reference=order_reference))


@orders_bp.get("/<order_reference>/payment/qr")
@roles_required(*ORDERING_ROLES)
def payment_qr(order_reference: str):
    try:
        order = owned_order(order_reference, current_user.id)
    except PaymentError:
        abort(404)
    if online_payment_details(order.shop) is None:
        abort(404)
    response = send_file(BytesIO(order.shop.payment_qr_data), mimetype=order.shop.payment_qr_mime)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@orders_bp.post("/<order_reference>/payment/submit")
@roles_required(*ORDERING_ROLES)
def submit_payment(order_reference: str):
    try:
        order = owned_order(order_reference, current_user.id)
    except PaymentError:
        abort(404)
    form = PaymentReferenceForm()
    if not form.validate_on_submit():
        return render_order_detail(order, payment_error="Enter a valid payment reference.", status=400)
    try:
        submit_online_reference(
            order_reference=order_reference, user_id=current_user.id,
            reference=form.payment_reference.data,
        )
    except PaymentError as error:
        if error.status_code == 404:
            abort(404)
        return render_order_detail(order, payment_error=str(error), status=error.status_code)
    return redirect(url_for("orders.detail", order_reference=order_reference))


def professor_form(order):
    if (current_user.role != UserRole.STUDENT
            or order.destination is not None
            or order.status != OrderStatus.PENDING_PAYMENT
            or (order.payment is not None and order.payment.payment_method == PaymentMethod.ONSITE)
            or not professor_service_available(order.shop_id)):
        return None
    professors = selectable_professors()
    if not professors:
        return None
    form = SelectProfessorForm()
    form.professor_id.choices = [
        (str(professor.id), f"{professor.name} — {professor.department or 'Department not listed'}")
        for professor in professors
    ]
    if request.method == "GET" and order.professor_id is not None:
        form.professor_id.data = str(order.professor_id)
    return form


@orders_bp.post("/<order_reference>/professor")
@roles_required(UserRole.STUDENT)
def select_professor(order_reference: str):
    order = db.session.scalar(
        select(Order).where(
            Order.order_reference == order_reference, Order.user_id == current_user.id
        )
    )
    if order is None:
        abort(404)
    form = professor_form(order)
    if form is None or not form.validate_on_submit():
        return render_order_detail(
            order, professor_error="Select an active, approved professor.", status=400
        )
    try:
        professor = validate_professor_selection(
            shop_id=order.shop_id, destination=OrderDestination.PROFESSOR,
            professor_id=form.professor_id.data, actor=current_user,
        )
        assign_professor(order, professor)
        order.professor_recipient_type = "STUDENT_SELECTED"
        db.session.commit()
    except ProfessorSelectionError as error:
        return render_order_detail(order, professor_error=str(error), status=400)
    return redirect(url_for("orders.detail", order_reference=order_reference))
