"""Import models so Flask-Migrate can discover their metadata."""

from app.models.user import ProfessorVerificationStatus, User, UserRole
from app.models.shop import ColorMode, FeeType, PaperSize, PrintPrice, PrintingShop, ServiceType, ShopFee, ShopService
from app.models.file import PrintConfiguration, UploadedFile
from app.models.order import Order, OrderDestination, OrderItem, OrderStatus
from app.models.professor import Faculty, Professor
from app.models.payment import Payment, PaymentMethod, PaymentStatus
from app.models.payment_settings import PaymentSettings
from app.models.password_reset import PasswordResetAttempt, PasswordResetGrant

__all__ = [
    "ColorMode",
    "FeeType",
    "Faculty",
    "Order",
    "OrderDestination",
    "OrderItem",
    "OrderStatus",
    "Payment",
    "PaymentMethod",
    "PaymentStatus",
    "PaymentSettings",
    "PasswordResetAttempt",
    "PasswordResetGrant",
    "PaperSize",
    "PrintPrice",
    "Professor",
    "ProfessorVerificationStatus",
    "PrintConfiguration",
    "PrintingShop",
    "ServiceType",
    "ShopFee",
    "ShopService",
    "User",
    "UserRole",
    "UploadedFile",
]
