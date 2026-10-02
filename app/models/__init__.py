"""Import models so Flask-Migrate can discover their metadata."""

from app.models.user import User, UserRole
from app.models.shop import ColorMode, FeeType, PaperSize, PrintPrice, PrintingShop, ServiceType, ShopFee, ShopService

__all__ = [
    "ColorMode",
    "FeeType",
    "PaperSize",
    "PrintPrice",
    "PrintingShop",
    "ServiceType",
    "ShopFee",
    "ShopService",
    "User",
    "UserRole",
]
