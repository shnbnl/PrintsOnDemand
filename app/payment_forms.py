"""CSRF-protected student payment selection and reference submission."""

from flask_wtf import FlaskForm
from wtforms import SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Length


class PaymentMethodForm(FlaskForm):
    payment_method = SelectField("Payment method", validators=[DataRequired()])
    submit = SubmitField("Select payment method")


class PaymentReferenceForm(FlaskForm):
    payment_reference = StringField(
        "Payment reference", validators=[DataRequired(), Length(min=4, max=120)]
    )
    submit = SubmitField("Submit for verification")
