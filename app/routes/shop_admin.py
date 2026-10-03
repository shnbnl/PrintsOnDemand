"""Administrator shop, service, and pricing management."""

from flask import Blueprint, flash, redirect, render_template, url_for
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.authorization import roles_required
from app.extensions import db
from app.models import (
    ColorMode,
    FeeType,
    PaperSize,
    PrintPrice,
    PrintingShop,
    ServiceType,
    ShopFee,
    ShopService,
    User,
    UserRole,
)
from app.shop_forms import FeeForm, PriceForm, ServiceForm, ShopForm, StaffAssignmentForm
from app.services.admin_management import ManagementError, assign_staff_to_shop


shop_admin_bp = Blueprint("shop_admin", __name__, url_prefix="/admin/shops")


def staff_choices() -> list[tuple[int, str]]:
    users = db.session.scalars(
        select(User).where(User.role == UserRole.SHOP_STAFF).order_by(User.name)
    ).all()
    return [(user.id, f"{user.name} ({user.email})") for user in users]


def render_editor(shop: PrintingShop, *, shop_form=None, service_form=None, price_form=None, fee_form=None, staff_form=None):
    staff_form = staff_form or StaffAssignmentForm(formdata=None)
    staff_form.staff_id.choices = staff_choices()
    return render_template(
        "shops/edit.html",
        shop=shop,
        shop_form=shop_form or ShopForm(formdata=None, obj=shop),
        service_form=service_form or ServiceForm(formdata=None),
        price_form=price_form or PriceForm(formdata=None),
        fee_form=fee_form or FeeForm(formdata=None),
        staff_form=staff_form,
        services=sorted(shop.services, key=lambda item: item.service_type.value),
        prices=sorted(shop.prices, key=lambda item: (item.paper_size.value, item.color_mode.value)),
        fees=sorted(shop.fees, key=lambda item: item.fee_type.value),
        assigned_staff=sorted(shop.staff, key=lambda user: user.name),
    )


def commit_or_error(form, field_name: str) -> bool:
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        getattr(form, field_name).errors.append("Unable to save this value.")
        return False
    return True


@shop_admin_bp.get("")
@roles_required(UserRole.ADMIN)
def index():
    shops = db.session.scalars(select(PrintingShop).order_by(PrintingShop.name)).all()
    return render_template("shops/admin_index.html", shops=shops)


@shop_admin_bp.route("/new", methods=["GET", "POST"])
@roles_required(UserRole.ADMIN)
def create():
    form = ShopForm()
    if form.validate_on_submit():
        existing = db.session.scalar(select(PrintingShop).where(PrintingShop.name == form.name.data))
        if existing:
            form.name.errors.append("A shop with this name already exists.")
        else:
            shop = PrintingShop(
                name=form.name.data,
                description=form.description.data or "",
                address=form.address.data,
                opening_time=form.opening_time.data,
                closing_time=form.closing_time.data,
                is_active=bool(form.is_active.data),
                is_demo=bool(form.is_demo.data),
            )
            db.session.add(shop)
            if commit_or_error(form, "name"):
                flash("Shop created.", "success")
                return redirect(url_for("shop_admin.edit", shop_id=shop.id))
    return render_template("shops/new.html", form=form)


@shop_admin_bp.route("/<int:shop_id>/edit", methods=["GET", "POST"])
@roles_required(UserRole.ADMIN)
def edit(shop_id: int):
    shop = db.get_or_404(PrintingShop, shop_id)
    form = ShopForm(obj=shop)
    if form.validate_on_submit():
        existing = db.session.scalar(
            select(PrintingShop).where(PrintingShop.name == form.name.data, PrintingShop.id != shop.id)
        )
        if existing:
            form.name.errors.append("A shop with this name already exists.")
        else:
            shop.name = form.name.data
            shop.description = form.description.data or ""
            shop.address = form.address.data
            shop.opening_time = form.opening_time.data
            shop.closing_time = form.closing_time.data
            shop.is_active = bool(form.is_active.data)
            shop.is_demo = bool(form.is_demo.data)
            if commit_or_error(form, "name"):
                flash("Shop updated.", "success")
                return redirect(url_for("shop_admin.edit", shop_id=shop.id))
    return render_editor(shop, shop_form=form)


@shop_admin_bp.post("/<int:shop_id>/services")
@roles_required(UserRole.ADMIN)
def save_service(shop_id: int):
    shop = db.get_or_404(PrintingShop, shop_id)
    form = ServiceForm()
    if form.validate_on_submit():
        service_type = ServiceType(form.service_type.data)
        service = db.session.scalar(
            select(ShopService).where(
                ShopService.shop_id == shop.id, ShopService.service_type == service_type
            )
        )
        if service is None:
            service = ShopService(shop=shop, service_type=service_type)
            db.session.add(service)
        service.enabled = bool(form.enabled.data)
        if commit_or_error(form, "service_type"):
            flash("Service saved.", "success")
            return redirect(url_for("shop_admin.edit", shop_id=shop.id))
    return render_editor(shop, service_form=form)


@shop_admin_bp.post("/<int:shop_id>/prices")
@roles_required(UserRole.ADMIN)
def save_price(shop_id: int):
    shop = db.get_or_404(PrintingShop, shop_id)
    form = PriceForm()
    if form.validate_on_submit():
        paper_size = PaperSize(form.paper_size.data)
        color_mode = ColorMode(form.color_mode.data)
        price = db.session.scalar(
            select(PrintPrice).where(
                PrintPrice.shop_id == shop.id,
                PrintPrice.paper_size == paper_size,
                PrintPrice.color_mode == color_mode,
            )
        )
        if price is None:
            price = PrintPrice(shop=shop, paper_size=paper_size, color_mode=color_mode)
            db.session.add(price)
        price.price = form.price.data
        price.is_demo = False
        if commit_or_error(form, "price"):
            flash("Price saved.", "success")
            return redirect(url_for("shop_admin.edit", shop_id=shop.id))
    return render_editor(shop, price_form=form)


@shop_admin_bp.post("/<int:shop_id>/fees")
@roles_required(UserRole.ADMIN)
def save_fee(shop_id: int):
    shop = db.get_or_404(PrintingShop, shop_id)
    form = FeeForm()
    if form.validate_on_submit():
        fee_type = FeeType(form.fee_type.data)
        fee = db.session.scalar(
            select(ShopFee).where(ShopFee.shop_id == shop.id, ShopFee.fee_type == fee_type)
        )
        if fee is None:
            fee = ShopFee(shop=shop, fee_type=fee_type)
            db.session.add(fee)
        fee.amount = form.amount.data
        fee.is_demo = False
        if commit_or_error(form, "amount"):
            flash("Fee saved.", "success")
            return redirect(url_for("shop_admin.edit", shop_id=shop.id))
    return render_editor(shop, fee_form=form)


@shop_admin_bp.post("/<int:shop_id>/staff")
@roles_required(UserRole.ADMIN)
def assign_staff(shop_id: int):
    shop = db.get_or_404(PrintingShop, shop_id)
    form = StaffAssignmentForm()
    form.staff_id.choices = staff_choices()
    if form.validate_on_submit():
        try:
            assign_staff_to_shop(form.staff_id.data, shop.id)
        except ManagementError:
            form.staff_id.errors.append("Select a Shop Staff account.")
        else:
            flash("Shop Staff account assigned.", "success")
            return redirect(url_for("shop_admin.edit", shop_id=shop.id))
    return render_editor(shop, staff_form=form)
