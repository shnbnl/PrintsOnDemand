"""Student-only order selection, quote review, creation, and detail."""

from flask import Blueprint, abort, current_app, redirect, render_template, request, session, url_for
from flask_login import current_user
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload

from app.authorization import roles_required
from app.extensions import db
from app.models import (
    Order, OrderDestination, OrderStatus, Payment, PaymentMethod, PaymentStatus,
    PrintConfiguration, PrintingShop, UploadedFile, UserRole,
)
from app.order_forms import PlaceOrderForm, SelectProfessorForm
from app.payment_forms import PaymentMethodForm, PaymentReferenceForm
from app.services.orders import create_order
from app.services.payments import (
    PaymentError, online_payment_details, owned_order, payment_configuration,
    select_payment_method, submit_online_reference,
)
from app.services.pricing import PricingError, quote_order
from app.services.professors import (
    ProfessorSelectionError, assign_professor, professor_service_available,
    professor_snapshot, selectable_professors, validate_professor_selection,
)
from app.services.tracking import build_tracking


orders_bp = Blueprint("orders", __name__, url_prefix="/orders")
HISTORY_PAGE_SIZE = 20
MAX_DATABASE_ID = 2**63 - 1
MAX_HISTORY_PAGE = MAX_DATABASE_ID // HISTORY_PAGE_SIZE


@orders_bp.get("")
@roles_required(UserRole.STUDENT)
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
    statement = statement.options(selectinload(Order.payment)).order_by(
        Order.created_at.desc(), Order.id.desc()
    )
    orders = db.paginate(statement, page=page, per_page=HISTORY_PAGE_SIZE, error_out=False)
    return render_template(
        "orders/index.html", orders=orders, status=status, payment_status=payment_status,
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


def render_selection(*, file_id=None, shop_id=None, destination=None, professor_id=None,
                     error=None, status=200):
    files, shops = choices()
    return render_template(
        "orders/new.html", files=files, shops=shops,
        professors=selectable_professors(), selected_file_id=file_id,
        selected_shop_id=shop_id, selected_destination=destination,
        selected_professor_id=professor_id, error=error,
    ), status


def review_state(quote, destination, professor):
    return {
        "file_id": quote.uploaded_file.id, "shop_id": quote.shop.id,
        "fingerprint": quote.fingerprint, "destination": destination or None,
        "professor": professor_snapshot(professor),
    }


def render_review(quote, *, destination=None, professor=None, warning=None, status=200):
    form = PlaceOrderForm(formdata=None)
    form.file_id.data = str(quote.uploaded_file.id)
    form.shop_id.data = str(quote.shop.id)
    form.destination.data = destination or ""
    form.professor_id.data = str(professor.id) if professor else ""
    return render_template(
        "orders/review.html", quote=quote, form=form, professor=professor,
        warning=warning,
    ), status


@orders_bp.get("/new")
@roles_required(UserRole.STUDENT)
def new():
    raw_file = request.args.get("file_id")
    raw_shop = request.args.get("shop_id")
    destination = request.args.get("destination") or None
    professor_id = request.args.get("professor_id") or None
    file_id, shop_id = positive_id(raw_file), positive_id(raw_shop)
    if (raw_file and file_id is None) or (raw_shop and shop_id is None):
        return render_selection(error="Select a valid file and printing shop.", status=400)
    if file_id is None or shop_id is None:
        return render_selection(file_id=file_id, shop_id=shop_id,
                                destination=destination, professor_id=professor_id)
    try:
        quote = quote_for(file_id, shop_id)
        professor = validate_professor_selection(
            shop_id=shop_id, destination=destination, professor_id=professor_id
        )
    except PricingError as error:
        return render_selection(
            file_id=file_id, shop_id=shop_id, error=str(error), status=error.status_code
        )
    except ProfessorSelectionError as error:
        return render_selection(
            file_id=file_id, shop_id=shop_id, destination=destination,
            professor_id=professor_id, error=str(error), status=400,
        )
    session["order_quote"] = review_state(quote, destination, professor)
    return render_review(quote, destination=destination, professor=professor)


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
        professor = validate_professor_selection(
            shop_id=shop_id, destination=form.destination.data,
            professor_id=form.professor_id.data,
        )
    except PricingError as error:
        return render_selection(
            file_id=file_id, shop_id=shop_id, error=str(error), status=error.status_code
        )
    except ProfessorSelectionError as error:
        return render_selection(
            file_id=file_id, shop_id=shop_id, destination=form.destination.data,
            professor_id=form.professor_id.data, error=str(error), status=400,
        )
    reviewed = session.get("order_quote")
    current_review = review_state(quote, form.destination.data, professor)
    if reviewed != current_review:
        session["order_quote"] = current_review
        return render_review(
            quote, destination=form.destination.data, professor=professor,
            warning="The order or price changed, including any professor details. Review the current details and place the order again.",
            status=409,
        )
    try:
        order = create_order(
            quote, destination=form.destination.data, professor_id=form.professor_id.data
        )
    except ProfessorSelectionError as error:
        return render_selection(
            file_id=file_id, shop_id=shop_id, destination=form.destination.data,
            professor_id=form.professor_id.data, error=str(error), status=400,
        )
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
    return render_order_detail(order)


def render_order_detail(order, *, payment_error=None, professor_error=None, status=200):
    online_details = online_payment_details()
    method_form = None
    if order.status == OrderStatus.PENDING_PAYMENT and (
        order.payment is None or order.payment.payment_status == PaymentStatus.PENDING
    ):
        method_form = PaymentMethodForm()
        method_form.payment_method.choices = [(PaymentMethod.ONSITE.value, "Onsite payment")]
        if online_details is not None:
            method_form.payment_method.choices.append((PaymentMethod.ONLINE.value, "Online payment"))
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
        method_form=method_form, reference_form=reference_form,
        online_details=online_details, payment_error=payment_error,
        professor_error=professor_error,
        onsite_instructions=payment_configuration()["onsite_instructions"],
        tracking=build_tracking(order),
    ), status


@orders_bp.post("/<order_reference>/payment")
@roles_required(UserRole.STUDENT)
def choose_payment(order_reference: str):
    try:
        order = owned_order(order_reference, current_user.id)
    except PaymentError:
        abort(404)
    form = PaymentMethodForm()
    form.payment_method.choices = [(PaymentMethod.ONSITE.value, "Onsite payment")]
    if online_payment_details() is not None:
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


@orders_bp.post("/<order_reference>/payment/submit")
@roles_required(UserRole.STUDENT)
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
    if order.status != OrderStatus.PENDING_PAYMENT or not professor_service_available(order.shop_id):
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
            professor_id=form.professor_id.data,
        )
        assign_professor(order, professor)
        db.session.commit()
    except ProfessorSelectionError as error:
        return render_order_detail(order, professor_error=str(error), status=400)
    return redirect(url_for("orders.detail", order_reference=order_reference))
