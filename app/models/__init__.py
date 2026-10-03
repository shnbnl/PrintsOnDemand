"""Import models so Flask-Migrate can discover their metadata."""

from app.models.user import User, UserRole
from app.models.shop import ColorMode, FeeType, PaperSize, PrintPrice, PrintingShop, ServiceType, ShopFee, ShopService
from app.models.file import PrintConfiguration, UploadedFile
from app.models.order import Order, OrderDestination, OrderItem, OrderStatus
from app.models.professor import Professor
from app.models.payment import Payment, PaymentMethod, PaymentStatus
from app.models.payment_settings import PaymentSettings

__all__ = [
    "ColorMode",
    "FeeType",
    "Order",
    "OrderDestination",
    "OrderItem",
    "OrderStatus",
    "Payment",
    "PaymentMethod",
    "PaymentStatus",
    "PaymentSettings",
    "PaperSize",
    "PrintPrice",
    "Professor",
    "PrintConfiguration",
    "PrintingShop",
    "ServiceType",
    "ShopFee",
    "ShopService",
    "User",
    "UserRole",
    "UploadedFile",
]
