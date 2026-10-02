"""CSRF-protected upload and print-setting forms."""

from flask import current_app
from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import BooleanField, IntegerField, SelectField, SubmitField
from wtforms.validators import DataRequired, InputRequired, NumberRange, ValidationError

from app.models import ColorMode, PaperSize


class UploadForm(FlaskForm):
    file = FileField("Select file to print")
    submit = SubmitField("Upload file")


class PrintConfigurationForm(FlaskForm):
    paper_size = SelectField(
        "Paper size", choices=[(size.value, size.label) for size in PaperSize],
        validators=[DataRequired()],
    )
    color_mode = SelectField(
        "Print color output", choices=[(mode.value, mode.label) for mode in ColorMode],
        validators=[DataRequired()],
    )
    quantity = IntegerField("Print count", validators=[InputRequired(), NumberRange(min=1)])
    is_rush = BooleanField("Rush printing")
    submit = SubmitField("Save configuration")

    def validate_quantity(self, field):
        if field.data is not None and field.data > current_app.config["UPLOAD_MAX_QUANTITY"]:
            raise ValidationError(
                f"Print count cannot exceed {current_app.config['UPLOAD_MAX_QUANTITY']}."
            )
