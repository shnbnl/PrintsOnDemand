"""Role-protected online review and onsite cash confirmation pages."""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.authorization import roles_required
from app.extensions import db
from app.models import UserRole
from app.services.payment_verification import (
    VerificationError, can_collect_onsite_cash, confirm_onsite_cash, decide_payment, review_payment, review_queue,
)


payment_verification_bp = Blueprint("payment_verification", __name__, url_prefix="/payments/verification")
REVIEW_ROLES = (UserRole.ADMIN, UserRole.SHOP_STAFF)


def payment_or_abort(payment_id):
    try:
        return review_payment(current_user, payment_id)
    except VerificationError as error:
        abort(error.status_code, description=str(error))


def render_review(payment, *, error=None, status=200):
    return render_template("payment_verification/detail.html", payment=payment, error=error,
                           cash_confirmable=can_collect_onsite_cash(payment)), status


@payment_verification_bp.get("")
@roles_required(*REVIEW_ROLES)
def index():
    try:
        payments = review_queue(current_user)
    except VerificationError as error:
        abort(error.status_code, description=str(error))
    return render_template("payment_verification/index.html", payments=payments)


@payment_verification_bp.get("/<int:payment_id>")
@roles_required(*REVIEW_ROLES)
def detail(payment_id):
    payment = payment_or_abort(payment_id)
    return render_review(payment)


def decide(payment_id, *, reject):
    payment = payment_or_abort(payment_id)
    try:
        decided = decide_payment(
            current_user, payment_id, reject=reject,
            reason=request.form.get("reason", "") if reject else "",
        )
    except VerificationError as error:
        if error.status_code in (400, 409):
            db.session.expire_all()
            payment = payment_or_abort(payment_id)
            return render_review(payment, error=str(error), status=error.status_code)
        abort(error.status_code, description=str(error))
    flash("Payment rejected." if reject else "Payment verified. The order is now Printing.", "success")
    return redirect(url_for("payment_verification.detail", payment_id=decided.id))


@payment_verification_bp.post("/<int:payment_id>/verify")
@roles_required(*REVIEW_ROLES)
def verify(payment_id):
    return decide(payment_id, reject=False)


@payment_verification_bp.post("/<int:payment_id>/reject")
@roles_required(*REVIEW_ROLES)
def reject(payment_id):
    return decide(payment_id, reject=True)


@payment_verification_bp.post("/<int:payment_id>/confirm-onsite")
@roles_required(*REVIEW_ROLES)
def confirm_onsite(payment_id):
    if request.form.get("cash_received") != "yes":
        payment = payment_or_abort(payment_id)
        return render_review(payment, error="Confirm that the full cash amount was received.", status=400)
    try:
        decided = confirm_onsite_cash(current_user, payment_id)
    except VerificationError as error:
        if error.status_code in (400, 409):
            db.session.expire_all()
            payment = payment_or_abort(payment_id)
            return render_review(payment, error=str(error), status=error.status_code)
        abort(error.status_code, description=str(error))
    flash("Onsite cash payment recorded. Printing starts if the order has not already progressed.", "success")
    return redirect(url_for("payment_verification.detail", payment_id=decided.id))
