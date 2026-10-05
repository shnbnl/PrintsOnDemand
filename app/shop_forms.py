"""Forms for administrator-managed shop settings."""

from decimal import Decimal

from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import BooleanField, DecimalField, SelectField, StringField, SubmitField, TextAreaField, TimeField
from wtforms.validators import DataRequired, InputRequired, Length, Optional, ValidationError

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
    latitude = DecimalField("Latitude", places=None, validators=[Optional()])
    longitude = DecimalField("Longitude", places=None, validators=[Optional()])
    opening_time = TimeField("Opening time", format="%H:%M", validators=[InputRequired()])
    closing_time = TimeField("Closing time", format="%H:%M", validators=[InputRequired()])
    is_active = BooleanField("Active", default=True)
    is_demo = BooleanField("Sample shop information")
    submit = SubmitField("Save shop")

    def validate(self, extra_validators=None) -> bool:
        valid = super().validate(extra_validators=extra_validators)
        if (self.latitude.data is None) != (self.longitude.data is None):
            self.latitude.errors.append("Enter both latitude and longitude, or leave both blank.")
            return False
        return valid

    @staticmethod
    def _validate_coordinate(field, limit: int) -> None:
        value = field.data
        if value is None:
            return
        if not value.is_finite() or not -limit <= value <= limit:
            raise ValidationError(f"Enter a value from -{limit} to {limit}.")
        if value != value.quantize(Decimal("0.000000000000001")):
            raise ValidationError("Use no more than fifteen decimal places.")

    def validate_latitude(self, field) -> None:
        self._validate_coordinate(field, 90)

    def validate_longitude(self, field) -> None:
        self._validate_coordinate(field, 180)

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


class ShopStaffDetailsForm(FlaskForm):
    description = TextAreaField("Shop description", filters=[strip_text], validators=[Length(max=2000)])
    address = StringField("Address", filters=[strip_text], validators=[DataRequired(), Length(max=255)])
    opening_time = TimeField("Opening time", format="%H:%M", validators=[InputRequired()])
    closing_time = TimeField("Closing time", format="%H:%M", validators=[InputRequired()])
    submit = SubmitField("Save details")

    def validate_closing_time(self, field) -> None:
        if self.opening_time.data and field.data == self.opening_time.data:
            raise ValidationError("Opening and closing times must differ.")


class ShopPhotoForm(FlaskForm):
    photo = FileField("Shop photo", validators=[DataRequired()])
    submit = SubmitField("Upload photo")
