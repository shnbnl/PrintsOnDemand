"""Server-side Stage 3 rate lookup and Stage 5 order quotation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app.extensions import db
from app.models import (
    ColorMode, FeeType, PaperSize, PrintPrice, PrintingShop, ServiceType,
    ShopFee, ShopService, UploadedFile,
)
from app.storage import StorageError, get_storage


CENT = Decimal("0.01")
MAX_MONEY = Decimal("999999999999.99")


class PricingError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class PrintOptions:
    """Untrusted checkout settings, validated again against model enums and limits."""

    paper_size: str
    color_mode: str
    quantity: int
    is_rush: bool


@dataclass(frozen=True)
class OrderQuote:
    user_id: int
    shop: PrintingShop
    uploaded_file: UploadedFile
    paper_size: PaperSize
    color_mode: ColorMode
    quantity: int
    is_rush: bool
    unit_price: Decimal
    line_total: Decimal
    subtotal: Decimal
    rush_fee: Decimal
    fees_total: Decimal
    total: Decimal
    currency: str
    is_demo: bool

    @property
    def fingerprint(self) -> str:
        values = (
            self.user_id, self.shop.id, self.shop.name, self.uploaded_file.id,
            self.uploaded_file.sha256, self.paper_size.value, self.color_mode.value,
            self.quantity, self.is_rush, self.unit_price, self.rush_fee, self.total,
            self.currency,
        )
        return hashlib.sha256("|".join(map(str, values)).encode()).hexdigest()


@dataclass(frozen=True)
class CartQuote:
    user_id: int
    shop: PrintingShop
    items: tuple[OrderQuote, ...]
    subtotal: Decimal
    rush_fee: Decimal
    delivery_fee: Decimal
    fees_total: Decimal
    total: Decimal
    currency: str
    is_demo: bool

    @property
    def fingerprint(self) -> str:
        values = (
            self.user_id, self.shop.id, self.shop.name,
            *(item.fingerprint for item in self.items),
            self.subtotal, self.rush_fee, self.delivery_fee, self.fees_total, self.total,
            self.currency, self.is_demo,
        )
        return hashlib.sha256("|".join(map(str, values)).encode()).hexdigest()


def money(value: Decimal | None, label: str) -> Decimal:
    if value is None or not isinstance(value, Decimal):
        raise PricingError(f"{label} is unavailable.")
    try:
        if not value.is_finite() or value < 0 or value > MAX_MONEY or value != value.quantize(CENT):
            raise PricingError(f"{label} is invalid.")
    except InvalidOperation as error:
        raise PricingError(f"{label} is invalid.") from error
    return value


def quote_order(
    *, user_id: int, file_id: int, shop_id: int, max_quantity: int,
    currency: str = "PHP", options: PrintOptions | None = None,
) -> OrderQuote:
    """Rebuild a quote from owned file settings and current shop prices."""
    uploaded_file = db.session.scalar(
        select(UploadedFile).where(UploadedFile.id == file_id, UploadedFile.user_id == user_id)
    )
    if uploaded_file is None:
        raise PricingError("File not found.", 404)
    shop = db.session.get(PrintingShop, shop_id)
    if shop is None or not shop.is_active:
        raise PricingError("Printing shop is unavailable.", 404)

    try:
        configuration = uploaded_file.configuration
        if configuration is None and options is None:
            raise PricingError("Configure this file before ordering.")
        paper_size = PaperSize(options.paper_size if options else configuration.paper_size)
        color_mode = ColorMode(options.color_mode if options else configuration.color_mode)
    except (LookupError, ValueError) as error:
        if isinstance(error, PricingError):
            raise
        raise PricingError("Print configuration is invalid.") from error
    quantity = options.quantity if options else configuration.quantity
    if type(quantity) is not int or not 1 <= quantity <= max_quantity:
        raise PricingError("Print count is invalid.")
    is_rush = options.is_rush if options else configuration.is_rush
    if type(is_rush) is not bool:
        raise PricingError("Rush printing selection is invalid.")

    try:
        data = get_storage().read(uploaded_file.storage_key)
    except (StorageError, OSError) as error:
        raise PricingError("The uploaded file is unavailable.", 409) from error
    if len(data) != uploaded_file.file_size or hashlib.sha256(data).hexdigest() != uploaded_file.sha256:
        raise PricingError("The uploaded file is unavailable.", 409)

    rate = db.session.scalar(
        select(PrintPrice).where(
            PrintPrice.shop_id == shop.id,
            PrintPrice.paper_size == paper_size,
            PrintPrice.color_mode == color_mode,
        )
    )
    if rate is None:
        raise PricingError("This shop has no price for the selected paper and color.")
    unit_price = money(rate.price, "Print price")
    line_total = money(unit_price * quantity, "Line total")

    rush_fee = Decimal("0.00")
    fee_is_demo = False
    if is_rush:
        rush_service = db.session.scalar(
            select(ShopService).where(
                ShopService.shop_id == shop.id,
                ShopService.service_type == ServiceType.RUSH_PRINTING,
                ShopService.enabled.is_(True),
            )
        )
        if rush_service is None:
            raise PricingError("Rush printing is not offered by this shop.")
        fee = db.session.scalar(
            select(ShopFee).where(
                ShopFee.shop_id == shop.id, ShopFee.fee_type == FeeType.RUSH_PRINTING
            )
        )
        if fee is None:
            raise PricingError("Rush fee is not configured for this shop.")
        rush_fee = money(fee.amount, "Rush fee")
        fee_is_demo = fee.is_demo

    subtotal = line_total
    fees_total = rush_fee
    total = money(subtotal + fees_total, "Order total")
    return OrderQuote(
        user_id=user_id, shop=shop, uploaded_file=uploaded_file,
        paper_size=paper_size, color_mode=color_mode, quantity=quantity,
        is_rush=is_rush, unit_price=unit_price, line_total=line_total,
        subtotal=subtotal, rush_fee=rush_fee, fees_total=fees_total, total=total,
        currency=currency, is_demo=shop.is_demo or rate.is_demo or fee_is_demo,
    )


def quote_cart(
    *, user_id: int, file_ids: list[int], shop_id: int, max_quantity: int,
    max_files: int, currency: str = "PHP",
    options: dict[int, PrintOptions] | None = None,
    delivery_fee: Decimal = Decimal("0.00"),
    delivery_fee_is_demo: bool = False,
) -> CartQuote:
    """Quote unique owned files; apply a shop's rush fee once per order."""
    if not file_ids:
        raise PricingError("Select at least one file for this order.")
    if len(file_ids) > max_files:
        raise PricingError(f"Select no more than {max_files} files per order.")
    if len(set(file_ids)) != len(file_ids):
        raise PricingError("Select each file only once per order.")
    items = tuple(quote_order(
        user_id=user_id, file_id=file_id, shop_id=shop_id,
        max_quantity=max_quantity, currency=currency,
        options=(options or {}).get(file_id),
    ) for file_id in file_ids)
    subtotal = money(sum((item.line_total for item in items), Decimal("0.00")), "Order subtotal")
    rush_fee = next((item.rush_fee for item in items if item.is_rush), Decimal("0.00"))
    delivery_fee = money(delivery_fee, "Delivery fee")
    fees_total = money(rush_fee + delivery_fee, "Order fees")
    total = money(subtotal + fees_total, "Order total")
    return CartQuote(
        user_id=user_id, shop=items[0].shop, items=items,
        subtotal=subtotal, rush_fee=rush_fee, delivery_fee=delivery_fee,
        fees_total=fees_total, total=total,
        currency=currency, is_demo=any(item.is_demo for item in items) or delivery_fee_is_demo,
    )
