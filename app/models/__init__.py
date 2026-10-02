"""Import models so Flask-Migrate can discover their metadata."""

from app.models.user import User, UserRole
from app.models.shop import ColorMode, FeeType, PaperSize, PrintPrice, PrintingShop, ServiceType, ShopFee, ShopService
from app.models.file import PrintConfiguration, UploadedFile

__all__ = [
    "ColorMode",
    "FeeType",
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
