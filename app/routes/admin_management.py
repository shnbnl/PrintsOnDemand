"""Admin pages for staff assignments, professors, and payment information."""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import select

from app.admin_forms import PaymentSettingsForm, ProfessorForm, StaffShopForm
from app.authorization import roles_required
from app.extensions import db
from app.models import PaymentSettings, PrintingShop, Professor, User, UserRole
from app.services.admin_management import (
    ManagementError, assign_staff_to_shop, save_payment_settings, save_professor,
)
from app.services.payments import payment_configuration


admin_management_bp = Blueprint("admin_management", __name__, url_prefix="/admin")


@admin_management_bp.get("/staff")
@roles_required(UserRole.ADMIN)
def staff_index():
    staff = db.session.scalars(
        select(User).where(User.role == UserRole.SHOP_STAFF).order_by(User.name, User.id)
    ).all()
    shops = db.session.scalars(select(PrintingShop).order_by(PrintingShop.name)).all()
    return render_template("admin/staff.html", staff=staff, shops=shops)


@admin_management_bp.route("/staff/<int:staff_id>/assignment", methods=["GET", "POST"])
@roles_required(UserRole.ADMIN)
def staff_assignment(staff_id):
    user = db.get_or_404(User, staff_id)
    if user.role != UserRole.SHOP_STAFF:
        abort(404)
    form = StaffShopForm()
    shops = db.session.scalars(select(PrintingShop).order_by(PrintingShop.name)).all()
    form.shop_id.choices = [(0, "Unassigned")] + [(shop.id, shop.name) for shop in shops]
    if form.validate_on_submit():
        try:
            assign_staff_to_shop(user.id, form.shop_id.data or None)
        except ManagementError as error:
            form.shop_id.errors.append(str(error))
        else:
            flash("Staff assignment updated.", "success")
            return redirect(url_for("admin_management.staff_index"))
    elif request.method == "GET":
        form.shop_id.data = user.shop_id or 0
    return render_template("admin/staff_assignment.html", user=user, form=form)


@admin_management_bp.get("/professors")
@roles_required(UserRole.ADMIN)
def professors():
    records = db.session.scalars(select(Professor).order_by(Professor.name, Professor.id)).all()
    return render_template("admin/professors.html", professors=records)


def professor_editor(record=None):
    form = ProfessorForm(obj=record)
    if form.validate_on_submit():
        try:
            saved = save_professor(
                record, name=form.name.data, email=form.email.data,
                department=form.department.data, office=form.office.data,
                is_active=bool(form.is_active.data),
                direct_send_approved=bool(form.direct_send_approved.data),
            )
        except ManagementError as error:
            form.email.errors.append(str(error))
        else:
            flash("Professor saved.", "success")
            return redirect(url_for("admin_management.edit_professor", professor_id=saved.id))
    return render_template("admin/professor_form.html", professor=record, form=form)


@admin_management_bp.route("/professors/new", methods=["GET", "POST"])
@roles_required(UserRole.ADMIN)
def new_professor():
    return professor_editor()


@admin_management_bp.route("/professors/<int:professor_id>/edit", methods=["GET", "POST"])
@roles_required(UserRole.ADMIN)
def edit_professor(professor_id):
    return professor_editor(db.get_or_404(Professor, professor_id))


@admin_management_bp.route("/payment", methods=["GET", "POST"])
@roles_required(UserRole.ADMIN)
def payment():
    form = PaymentSettingsForm()
    saved = db.session.get(PaymentSettings, 1)
    if form.validate_on_submit():
        save_payment_settings(
            online_enabled=bool(form.online_enabled.data),
            online_instructions=form.online_instructions.data or "",
            online_account_name=form.online_account_name.data or "",
            online_destination=form.online_destination.data or "",
            onsite_instructions=form.onsite_instructions.data,
        )
        flash("Public payment information updated.", "success")
        return redirect(url_for("admin_management.payment"))
    if request.method == "GET":
        values = payment_configuration()
        for key, value in values.items():
            getattr(form, key).data = value
    return render_template("admin/payment.html", form=form, saved=saved)
