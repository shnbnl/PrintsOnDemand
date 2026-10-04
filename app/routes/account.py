"""Self-service settings and confirmed customer account removal."""

from flask import Blueprint, current_app, flash, redirect, render_template, session, url_for
from flask_login import current_user, logout_user
from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, SubmitField
from wtforms.validators import DataRequired

from app.authorization import roles_required
from app.models import UserRole
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


@account_bp.get("")
@roles_required(UserRole.STUDENT, UserRole.PROFESSOR)
def settings():
    return render_template("account/settings.html")


@account_bp.route("/delete", methods=["GET", "POST"])
@roles_required(UserRole.STUDENT, UserRole.PROFESSOR)
def delete_account():
    form = DeleteAccountForm()
    if form.is_submitted():
        if form.validate() and current_user.check_password(form.password.data):
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
            flash("Your account and associated data were permanently deleted.", "success")
            return redirect(url_for("main.index"))
        if form.password.data and not form.password.errors and form.confirm.data:
            form.password.errors.append("The current password is incorrect.")
        return render_template("account/delete.html", form=form), 400
    return render_template("account/delete.html", form=form)
