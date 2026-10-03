"""Staff views and explicit processing actions for the assigned shop."""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.authorization import roles_required
from app.models import UserRole
from app.routes.files import send_private_file
from app.services.order_processing import (
    ProcessingError, advance_order, available_action, get_staff_order, list_staff_orders,
)


staff_orders_bp = Blueprint("staff_orders", __name__, url_prefix="/staff/orders")


def staff_order_or_abort(order_reference):
    try:
        return get_staff_order(current_user, order_reference)
    except ProcessingError as error:
        abort(error.status_code, description=error.message)


@staff_orders_bp.get("")
@roles_required(UserRole.SHOP_STAFF)
def index():
    try:
        orders = list_staff_orders(current_user)
    except ProcessingError as error:
        abort(error.status_code, description=error.message)
    return render_template("staff_orders/index.html", orders=orders)


@staff_orders_bp.get("/<order_reference>")
@roles_required(UserRole.SHOP_STAFF)
def detail(order_reference):
    order = staff_order_or_abort(order_reference)
    return render_template("staff_orders/detail.html", order=order, action=available_action(order))


@staff_orders_bp.get("/<order_reference>/files/<int:item_id>/download")
@roles_required(UserRole.SHOP_STAFF)
def download_file(order_reference, item_id):
    order = staff_order_or_abort(order_reference)
    item = next((item for item in order.items if item.id == item_id), None)
    if item is None:
        abort(404)
    return send_private_file(item.uploaded_file)


@staff_orders_bp.post("/<order_reference>/advance")
@roles_required(UserRole.SHOP_STAFF)
def advance(order_reference):
    action = request.form.get("action", "")
    try:
        order = advance_order(current_user, order_reference, action)
    except ProcessingError as error:
        abort(error.status_code, description=error.message)
    flash(f"Order status updated to {order.status.value}.", "success")
    return redirect(url_for("staff_orders.detail", order_reference=order_reference))
