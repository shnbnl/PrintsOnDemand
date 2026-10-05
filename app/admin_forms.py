"""CSRF-protected professor and staff-assignment forms."""

from flask_wtf import FlaskForm
from wtforms import BooleanField, EmailField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, Length

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
