"""Admin pages for staff assignments, professors, and payment information."""

from functools import wraps

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from flask_wtf import FlaskForm
from sqlalchemy import select

from app.admin_forms import PaymentSettingsForm, ProfessorForm, StaffShopForm
from app.authorization import roles_required
from app.extensions import db
from app.models import PaymentSettings, PrintingShop, Professor, ProfessorVerificationStatus, User, UserRole
from app.services.admin_management import (
    ManagementError, assign_staff_to_shop, delete_managed_professor, save_payment_settings, save_professor,
)
from app.services.account_deletion import (
    AccountDeletionCleanupError, AccountDeletionError, delete_customer_account,
)
from app.services.payments import payment_configuration
from app.services.professors import PROFESSOR_DELIVERY_SHOP


admin_management_bp = Blueprint("admin_management", __name__, url_prefix="/admin")


def professor_management_required(view):
    @wraps(view)
    @roles_required(UserRole.SHOP_STAFF)
    def guarded(*args, **kwargs):
        if current_user.shop is None or current_user.shop.name != PROFESSOR_DELIVERY_SHOP:
            abort(403)
        return view(*args, **kwargs)
    return guarded


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
@professor_management_required
def professors():
    records = db.session.scalars(select(Professor).order_by(Professor.name, Professor.id)).all()
    accounts = db.session.scalars(select(User).where(
        User.role == UserRole.PROFESSOR,
    ).order_by(User.name, User.id)).all()
    return render_template(
        "admin/professors.html", professors=records,
        pending=[user for user in accounts if user.professor_verification_status == ProfessorVerificationStatus.PENDING],
        verified=[user for user in accounts if user.professor_verification_status == ProfessorVerificationStatus.VERIFIED],
        rejected=[user for user in accounts if user.professor_verification_status == ProfessorVerificationStatus.REJECTED],
        verification_form=FlaskForm(),
    )


@admin_management_bp.post("/professors/accounts/<int:account_id>/verify")
@professor_management_required
def verify_professor_account(account_id):
    if not FlaskForm().validate_on_submit():
        abort(400)
    account = db.get_or_404(User, account_id)
    if account.role != UserRole.PROFESSOR or account.professor_verification_status != ProfessorVerificationStatus.PENDING:
        abort(400)
    account.professor_verification_status = ProfessorVerificationStatus.VERIFIED
    db.session.commit()
    flash("Professor account verified. Link it to a managed profile to enable delivery.", "success")
    return redirect(url_for("admin_management.professors"))


@admin_management_bp.post("/professors/accounts/<int:account_id>/reject")
@professor_management_required
def reject_professor_account(account_id):
    if not FlaskForm().validate_on_submit():
        abort(400)
    account = db.get_or_404(User, account_id)
    if account.role != UserRole.PROFESSOR or account.professor_verification_status != ProfessorVerificationStatus.PENDING:
        abort(400)
    account.professor_verification_status = ProfessorVerificationStatus.REJECTED
    db.session.commit()
    flash("Professor request rejected.", "success")
    return redirect(url_for("admin_management.professors"))


def professor_editor(record=None):
    form = ProfessorForm(obj=record)
    accounts = db.session.scalars(select(User).where(
        User.role == UserRole.PROFESSOR,
        User.professor_verification_status == ProfessorVerificationStatus.VERIFIED,
    ).order_by(User.name, User.id)).all()
    form.account_id.choices = [(0, "Unlinked")] + [
        (user.id, f"{user.name} ({user.email}) — {user.professor_department or 'Department not supplied'}")
        for user in accounts
        if user.professor_id is None or (record is not None and user.professor_id == record.id)
    ]
    if form.validate_on_submit():
        try:
            save_professor(
                record, name=form.name.data, email=form.email.data,
                department=form.department.data, office=form.office.data,
                faculty=form.faculty.data, account_id=form.account_id.data or None,
                is_active=bool(form.is_active.data),
                direct_send_approved=bool(form.direct_send_approved.data),
                accepts_student_deliveries=bool(form.accepts_student_deliveries.data),
            )
        except ManagementError as error:
            form.email.errors.append(str(error))
        else:
            flash("Professor saved.", "success")
            return redirect(url_for("admin_management.professors"))
    elif request.method == "GET":
        form.account_id.data = (
            record.account.id if record is not None and record.account
            else request.args.get("account_id", default=0, type=int)
        )
        if record is None and form.account_id.data:
            account = next((item for item in accounts if item.id == form.account_id.data), None)
            if account is not None:
                form.name.data = account.name
                form.email.data = account.email
                form.department.data = account.professor_department
                form.faculty.data = account.professor_department
    return render_template("admin/professor_form.html", professor=record, form=form)


@admin_management_bp.route("/professors/new", methods=["GET", "POST"])
@professor_management_required
def new_professor():
    return professor_editor()


@admin_management_bp.route("/professors/<int:professor_id>/edit", methods=["GET", "POST"])
@professor_management_required
def edit_professor(professor_id):
    return professor_editor(db.get_or_404(Professor, professor_id))


def confirm_deletion(*, title: str, name: str, impact: str, action: str, error=None, status=200):
    return render_template(
        "admin/professor_delete.html", title=title, name=name, impact=impact,
        action=action, form=FlaskForm(), error=error,
    ), status


@admin_management_bp.route("/professors/<int:professor_id>/delete", methods=["GET", "POST"])
@professor_management_required
def delete_professor(professor_id):
    profile = db.get_or_404(Professor, professor_id)
    page = dict(title="Delete managed professor profile", name=profile.name,
                impact="The linked Professor account will remain verified but become unlinked. Existing orders keep their saved recipient and Faculty details.",
                action=url_for("admin_management.delete_professor", professor_id=professor_id))
    if request.method == "POST":
        if not FlaskForm().validate_on_submit():
            abort(400)
        if request.form.get("confirm_delete") != "yes":
            return confirm_deletion(**page, error="Confirm the profile deletion to continue.", status=400)
        try:
            delete_managed_professor(professor_id)
        except ManagementError:
            current_app.logger.exception("Managed professor deletion failed")
            return confirm_deletion(**page, error="The profile could not be deleted. Try again.", status=503)
        flash("Managed professor profile deleted. Existing order details were preserved.", "success")
        return redirect(url_for("admin_management.professors"))
    return confirm_deletion(**page)


@admin_management_bp.route("/professors/accounts/<int:account_id>/delete", methods=["GET", "POST"])
@professor_management_required
def delete_professor_account(account_id):
    account = db.get_or_404(User, account_id)
    if account.role != UserRole.PROFESSOR or account.professor_verification_status != ProfessorVerificationStatus.VERIFIED:
        abort(404)
    page = dict(title="Delete verified Professor account", name=account.name,
                impact="This permanently removes the login and that account's private files, orders, payment details, and history. The separately managed profile and other customers' past orders remain; new student deliveries to this professor stop.",
                action=url_for("admin_management.delete_professor_account", account_id=account_id))
    if request.method == "POST":
        if not FlaskForm().validate_on_submit():
            abort(400)
        if request.form.get("confirm_delete") != "yes":
            return confirm_deletion(**page, error="Confirm the account deletion to continue.", status=400)
        try:
            delete_customer_account(account_id)
        except AccountDeletionCleanupError:
            current_app.logger.exception("Professor account deleted but private-file cleanup needs attention")
            flash("Professor account deleted. Private-file cleanup needs operator attention.", "warning")
        except AccountDeletionError:
            current_app.logger.exception("Professor account deletion failed")
            return confirm_deletion(**page, error="The account could not be deleted. Try again.", status=503)
        else:
            flash("Verified Professor account and its owned data deleted.", "success")
        return redirect(url_for("admin_management.professors"))
    return confirm_deletion(**page)


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
