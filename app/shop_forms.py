"""Forms for administrator-managed shop settings."""

from decimal import Decimal

from flask_wtf import FlaskForm
from wtforms import BooleanField, DecimalField, SelectField, StringField, SubmitField, TextAreaField, TimeField
from wtforms.validators import DataRequired, InputRequired, Length, ValidationError

from app.forms import strip_text
from app.models import ColorMode, FeeType, PaperSize, ServiceType


def validate_money(form, field) -> None:
    value = field.data
    if value is None:
        return
    if not value.is_finite() or value < 0 or value > Decimal("99999999.99"):
        raise ValidationError("Enter an amount from ₱0.00 to ₱99,999,999.99.")
    if value != value.quantize(Decimal("0.01")):
        raise ValidationError("Use no more than two decimal places.")


class ShopForm(FlaskForm):
    name = StringField("Shop name", filters=[strip_text], validators=[DataRequired(), Length(max=120)])
    description = TextAreaField("Description", filters=[strip_text], validators=[Length(max=2000)])
    address = StringField("Address", filters=[strip_text], validators=[DataRequired(), Length(max=255)])
    opening_time = TimeField("Opening time", format="%H:%M", validators=[InputRequired()])
    closing_time = TimeField("Closing time", format="%H:%M", validators=[InputRequired()])
    is_active = BooleanField("Active", default=True)
    is_demo = BooleanField("Demo shop information")
    submit = SubmitField("Save shop")

    def validate_closing_time(self, field) -> None:
        if self.opening_time.data and field.data == self.opening_time.data:
            raise ValidationError("Opening and closing times must differ.")


class ServiceForm(FlaskForm):
    service_type = SelectField(
        "Service",
        choices=[(item.value, item.label) for item in ServiceType],
        validators=[DataRequired()],
    )
    enabled = BooleanField("Enabled", default=True)
    submit = SubmitField("Save service")


class PriceForm(FlaskForm):
    paper_size = SelectField(
        "Paper size",
        choices=[(item.value, item.label) for item in PaperSize],
        validators=[DataRequired()],
    )
    color_mode = SelectField(
        "Output",
        choices=[(item.value, item.label) for item in ColorMode],
        validators=[DataRequired()],
    )
    price = DecimalField(
        "Price per page (₱)",
        places=None,
        validators=[InputRequired(), validate_money],
    )
    submit = SubmitField("Save price")


class FeeForm(FlaskForm):
    fee_type = SelectField(
        "Fee",
        choices=[(item.value, item.label) for item in FeeType],
        validators=[DataRequired()],
    )
    amount = DecimalField(
        "Amount (₱)",
        places=None,
        validators=[InputRequired(), validate_money],
    )
    submit = SubmitField("Save fee")


class StaffAssignmentForm(FlaskForm):
    staff_id = SelectField("Shop Staff account", coerce=int, validators=[DataRequired()])
    submit = SubmitField("Assign staff")
