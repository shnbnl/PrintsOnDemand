"""Import models so Flask-Migrate can discover their metadata."""

from app.models.user import User, UserRole
from app.models.shop import ColorMode, FeeType, PaperSize, PrintPrice, PrintingShop, ServiceType, ShopFee, ShopService
from app.models.file import PrintConfiguration, UploadedFile
from app.models.order import Order, OrderItem, OrderStatus

__all__ = [
    "ColorMode",
    "FeeType",
    "Order",
    "OrderItem",
    "OrderStatus",
    "PaperSize",
    "PrintPrice",
    "PrintConfiguration",
    "PrintingShop",
    "ServiceType",
    "ShopFee",
    "ShopService",
    "User",
    "UserRole",
    "UploadedFile",
]
