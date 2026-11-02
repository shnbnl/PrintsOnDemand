"""Admin pages for staff assignments, professors, and payment information."""

from functools import wraps

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from flask_wtf import FlaskForm
from sqlalchemy import select

from app.admin_forms import ProfessorForm, StaffProfessorForm, StaffShopForm
from app.authorization import roles_required
from app.extensions import db
from app.models import PaymentSettings, PrintingShop, Professor, ProfessorVerificationStatus, User, UserRole
from app.services.admin_management import (
    ManagementError, assign_staff_to_shop, delete_managed_professor,
    save_professor_approvals, save_staff_professor, verify_professor_with_profile,
)
from app.services.account_deletion import (
    AccountDeletionCleanupError, AccountDeletionError, delete_customer_account,
)
from app.services.professors import PROFESSOR_DELIVERY_SHOP
from app.professor_faculties import DELIVERY_LOCATIONS_BY_DEPARTMENT, FACULTIES_BY_DEPARTMENT


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
    try:
        verify_professor_with_profile(account)
    except ManagementError as error:
        abort(409, description=str(error))
    flash("Professor account verified and its managed profile created.", "success")
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


def professor_editor(record):
    form = ProfessorForm(obj=record)
    if form.validate_on_submit():
        try:
            save_professor_approvals(
                record, is_active=bool(form.is_active.data),
                direct_send_approved=bool(form.direct_send_approved.data),
                accepts_student_deliveries=bool(form.accepts_student_deliveries.data),
            )
        except ManagementError as error:
            form.is_active.errors.append(str(error))
        else:
            flash("Professor approval settings saved.", "success")
            return redirect(url_for("admin_management.professors"))
    return render_template("admin/professor_form.html", professor=record, form=form)


@admin_management_bp.route("/professors/new", methods=["GET", "POST"])
@professor_management_required
def new_professor():
    return staff_professor_editor(None)


def staff_professor_editor(record):
    form = StaffProfessorForm(obj=record)
    if form.validate_on_submit():
        try:
            save_staff_professor(record, **{key: getattr(form, key).data for key in (
                "name", "email", "department", "faculty", "office", "is_active",
                "direct_send_approved", "accepts_student_deliveries",
            )})
        except ManagementError as error:
            form.email.errors.append(str(error))
        else:
            flash("Professor delivery recipient saved.", "success")
            return redirect(url_for("admin_management.professors"))
    return render_template("admin/staff_professor_form.html", professor=record, form=form,
                           faculties_by_department=FACULTIES_BY_DEPARTMENT,
                           delivery_locations=DELIVERY_LOCATIONS_BY_DEPARTMENT)


@admin_management_bp.route("/professors/<int:professor_id>/edit", methods=["GET", "POST"])
@professor_management_required
def edit_professor(professor_id):
    record = db.get_or_404(Professor, professor_id)
    if record.account is None:
        if record.is_staff_managed:
            return staff_professor_editor(record)
        abort(404)
    return professor_editor(record)


def confirm_deletion(*, title: str, name: str, impact: str, action: str, error=None, status=200):
    return render_template(
        "admin/professor_delete.html", title=title, name=name, impact=impact,
        action=action, form=FlaskForm(), error=error,
    ), status


@admin_management_bp.route("/professors/<int:professor_id>/delete", methods=["GET", "POST"])
@professor_management_required
def delete_professor(professor_id):
    profile = db.get_or_404(Professor, professor_id)
    if profile.account is not None:
        abort(404)
    page = dict(title="Delete legacy professor profile", name=profile.name,
                impact="Existing orders keep their saved recipient and Faculty details.",
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
                impact="This permanently removes the login, managed profile, private files, orders, payment details, and history. Other customers' past order details remain; new student deliveries to this professor stop.",
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
    if request.method == "POST":
        abort(405)
    shops = db.session.scalars(select(PrintingShop).order_by(PrintingShop.name)).all()
    return render_template("admin/payment.html", shops=shops)
