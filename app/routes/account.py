"""Self-service settings and confirmed customer account removal."""

from flask import Blueprint, current_app, flash, redirect, render_template, session, url_for
from flask_login import current_user, logout_user
from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, SelectField, SubmitField
from wtforms.validators import DataRequired, ValidationError

from app.authorization import roles_required
from app.extensions import db
from app.models import Faculty, UserRole
from app.security_limits import enforce_limit
from app.services.account_deletion import (
    AccountDeletionCleanupError, AccountDeletionError, delete_customer_account,
)


account_bp = Blueprint("account", __name__, url_prefix="/account")


@account_bp.after_request
def prevent_private_page_caching(response):
    response.headers["Cache-Control"] = "private, no-store"
    return response


class DeleteAccountForm(FlaskForm):
    password = PasswordField("Current password", validators=[DataRequired()])
    confirm = BooleanField(
        "I understand that deleting my account and its data cannot be undone.",
        validators=[DataRequired(message="Confirm permanent account deletion.")],
    )
    submit = SubmitField("Permanently delete my account")


class ProfessorPreferenceForm(FlaskForm):
    department = SelectField(
        "Department", choices=[("", "Select department")] + [(item.value, item.value) for item in Faculty],
        validate_choice=False,
    )
    accepts_student_deliveries = BooleanField("Accept student print deliveries")
    submit = SubmitField("Save preference")

    def validate_department(self, field):
        if field.data and field.data not in {item.value for item in Faculty}:
            raise ValidationError("Select a valid department.")


def render_settings(*, preference_form=None, status=200):
    if current_user.role == UserRole.PROFESSOR:
        profile = current_user.professor
        department = current_user.professor_department or (profile.department if profile else None)
        form = preference_form or ProfessorPreferenceForm(formdata=None)
        if preference_form is None:
            form.accepts_student_deliveries.data = (
                profile.accepts_student_deliveries if profile is not None
                else current_user.student_delivery_preference
            )
        return render_template("account/settings.html", preference_form=form,
                               department=department, needs_department=not department), status
    return render_template("account/settings.html"), status


@account_bp.get("")
@roles_required(UserRole.STUDENT, UserRole.PROFESSOR)
def settings():
    return render_settings()


@account_bp.post("/professor-preference")
@roles_required(UserRole.PROFESSOR)
def professor_preference():
    profile = current_user.professor
    department = current_user.professor_department or (profile.department if profile else None)
    form = ProfessorPreferenceForm()
    if form.validate_on_submit():
        if not department and not form.department.data:
            form.department.errors.append("Select your department.")
        else:
            if not department:
                current_user.professor_department = form.department.data
            current_user.student_delivery_preference = bool(form.accepts_student_deliveries.data)
            if profile is not None:
                profile.accepts_student_deliveries = current_user.student_delivery_preference
            db.session.commit()
            flash("Professor account preference updated.", "success")
            return redirect(url_for("account.settings"))
    return render_settings(preference_form=form, status=400)


@account_bp.route("/delete", methods=["GET", "POST"])
@roles_required(UserRole.STUDENT, UserRole.PROFESSOR)
def delete_account():
    form = DeleteAccountForm()
    if form.is_submitted():
        valid = form.validate()
        if valid:
            enforce_limit("account-delete", str(current_user.id), attempts=5, seconds=3600)
        if valid and current_user.check_password(form.password.data):
            user_id = current_user.id
            try:
                delete_customer_account(current_user.id)
            except AccountDeletionCleanupError:
                current_app.logger.exception("Account deleted but staged private upload cleanup failed")
                logout_user()
                session.clear()
                session["_remember"] = "clear"
                return render_template(
                    "main/error.html",
                    message="Your account was removed, but private-file cleanup needs support. Contact an administrator.",
                ), 503
            except AccountDeletionError:
                current_app.logger.exception("Customer account deletion failed")
                return render_template("account/delete.html", form=form,
                                       error="Account deletion could not be completed. Please try again."), 503
            logout_user()
            session.clear()
            session["_remember"] = "clear"  # Also clear Flask-Login's remember cookie.
            session["play_account_delete_transition"] = True
            current_app.logger.warning("Customer account deleted: user_id=%s", user_id)
            flash("Your account and associated data were permanently deleted.", "success")
            return redirect(url_for("main.index"))
        if form.password.data and not form.password.errors and form.confirm.data:
            form.password.errors.append("The current password is incorrect.")
        return render_template("account/delete.html", form=form), 400
    return render_template("account/delete.html", form=form)
