"""CSRF-protected professor and staff-assignment forms."""

from flask_wtf import FlaskForm
from wtforms import BooleanField, SelectField, SubmitField


class ProfessorForm(FlaskForm):
    is_active = BooleanField("Active", default=True)
    direct_send_approved = BooleanField("Approved for Direct-to-Professor")
    accepts_student_deliveries = BooleanField("Accept student print deliveries")
    submit = SubmitField("Save professor")


class StaffShopForm(FlaskForm):
    shop_id = SelectField("Assigned shop", coerce=int)
    submit = SubmitField("Save assignment")
