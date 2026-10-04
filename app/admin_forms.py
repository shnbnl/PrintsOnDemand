"""CSRF-protected professor, staff-assignment, and public payment forms."""

from flask_wtf import FlaskForm
from wtforms import BooleanField, EmailField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, ValidationError

from app.forms import strip_text
from app.models import Faculty


class ProfessorForm(FlaskForm):
    name = StringField("Professor name", filters=[strip_text], validators=[DataRequired(), Length(max=120)])
    email = EmailField("Email", filters=[strip_text], validators=[DataRequired(), Email(), Length(max=254)])
    department = StringField("Department", filters=[strip_text], validators=[Length(max=120)])
    faculty = SelectField("Faculty", choices=[("", "Select Faculty")] + [(item.value, item.value) for item in Faculty], validators=[DataRequired()])
    office = StringField("Office", filters=[strip_text], validators=[Length(max=120)])
    account_id = SelectField("Linked professor account", coerce=int)
    is_active = BooleanField("Active", default=True)
    direct_send_approved = BooleanField("Approved for Direct-to-Professor")
    accepts_student_deliveries = BooleanField("Accept student print deliveries")
    submit = SubmitField("Save professor")


class StaffShopForm(FlaskForm):
    shop_id = SelectField("Assigned shop", coerce=int)
    submit = SubmitField("Save assignment")


class PaymentSettingsForm(FlaskForm):
    online_enabled = BooleanField("Enable manual online payment")
    online_instructions = TextAreaField(
        "Online payment instructions", filters=[strip_text], validators=[Length(max=2000)]
    )
    online_account_name = StringField(
        "Public account name", filters=[strip_text], validators=[Length(max=120)]
    )
    online_destination = StringField(
        "Public payment destination", filters=[strip_text], validators=[Length(max=255)]
    )
    onsite_instructions = TextAreaField(
        "Onsite payment instructions", filters=[strip_text],
        validators=[DataRequired(), Length(max=2000)],
    )
    submit = SubmitField("Save payment information")

    def validate_online_enabled(self, field):
        if field.data and not all((
            self.online_instructions.data,
            self.online_account_name.data,
            self.online_destination.data,
        )):
            raise ValidationError("Complete all public online payment fields before enabling it.")
