"""CSRF-protected final order placement form."""

from flask_wtf import FlaskForm
from wtforms import HiddenField, SubmitField
from wtforms.validators import DataRequired


class PlaceOrderForm(FlaskForm):
    file_id = HiddenField(validators=[DataRequired()])
    shop_id = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Place Order")
