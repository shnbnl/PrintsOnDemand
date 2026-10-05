"""Role-protected placeholder pages for access checks."""

from flask import Blueprint, render_template, url_for
from flask_login import current_user

from app.authorization import roles_required
from app.models import OrderStatus, PaymentStatus, UserRole
from app.routes.shops import detail_context
from app.services.order_processing import available_action, list_staff_orders


access_bp = Blueprint("access", __name__)


@access_bp.get("/student")
@roles_required(UserRole.STUDENT)
def student():
    return render_template(
        "main/protected.html", title="Student access", next_url=url_for("shops.index"),
        next_label="Browse printing shops",
        files_url=url_for("files.index"),
        orders_url=url_for("orders.index"),
    )


@access_bp.get("/professor")
@roles_required(UserRole.PROFESSOR)
def professor():
    return render_template(
        "main/protected.html", title="Professor access", next_url=url_for("shops.index"),
        next_label="Browse printing shops", files_url=url_for("files.index"),
        orders_url=url_for("orders.index"),
    )


@access_bp.get("/shop")
@roles_required(UserRole.SHOP_STAFF)
def shop():
    if current_user.shop is not None:
        orders = list_staff_orders(current_user)
        queue = {
            "payment_review": sum(bool(order.payment and order.payment.payment_status == PaymentStatus.SUBMITTED)
                                  for order in orders),
            "ready_to_print": sum(available_action(order) == "start_processing" for order in orders),
            "printing": sum(order.status == OrderStatus.PROCESSING for order in orders),
            "ready": sum(order.status == OrderStatus.READY for order in orders),
            "delivered": sum(order.status == OrderStatus.DELIVERED for order in orders),
            "completed": sum(order.status == OrderStatus.COMPLETED for order in orders),
        }
        attention_orders = [order for order in orders if
                            (order.payment and order.payment.payment_status == PaymentStatus.SUBMITTED)
                            or available_action(order) == "start_processing"][:5]
        return render_template("shops/detail.html", staff_view=True, queue=queue,
                               attention_orders=attention_orders, recent_orders=orders[:5],
                               **detail_context(current_user.shop))
    return render_template("main/protected.html", title="Shop Staff access")


@access_bp.get("/admin")
@roles_required(UserRole.ADMIN)
def admin():
    return render_template("admin/index.html")
