"""CSRF-protected final order placement form."""

from flask_wtf import FlaskForm
from wtforms import HiddenField, SelectField, SubmitField
from wtforms.validators import DataRequired


class PlaceOrderForm(FlaskForm):
    file_id = HiddenField()
    shop_id = HiddenField(validators=[DataRequired()])
    destination = HiddenField()
    professor_id = HiddenField()
    professor_faculty = HiddenField()
    pickup_date = HiddenField()
    pickup_slot = HiddenField()
    delivery_recipient_name = HiddenField()
    delivery_recipient_phone = HiddenField()
    delivery_address = HiddenField()
    delivery_date = HiddenField()
    delivery_slot = HiddenField()
    submit = SubmitField("Place Order")


class SelectProfessorForm(FlaskForm):
    professor_id = SelectField("Approved professor", validators=[DataRequired()])
    submit = SubmitField("Save professor")
