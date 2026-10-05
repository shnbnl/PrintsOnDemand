"""Legacy global payment record retained for migration/backward data access."""

from datetime import datetime

from sqlalchemy import CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.user import utc_now


class PaymentSettings(db.Model):
    __tablename__ = "payment_settings"
    __table_args__ = (CheckConstraint("id = 1", name="payment_settings_singleton"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    online_enabled: Mapped[bool] = mapped_column(db.Boolean, nullable=False)
    online_instructions: Mapped[str] = mapped_column(db.Text, nullable=False)
    online_account_name: Mapped[str] = mapped_column(db.String(120), nullable=False)
    online_destination: Mapped[str] = mapped_column(db.String(255), nullable=False)
    onsite_instructions: Mapped[str] = mapped_column(db.Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
