"""Authentication forms with server-side validation and CSRF tokens."""

from flask_wtf import FlaskForm
from wtforms import BooleanField, EmailField, PasswordField, RadioField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length


def strip_text(value: str | None) -> str | None:
    return value.strip() if value else value


class RegistrationForm(FlaskForm):
    account_type = RadioField("Account Type", choices=[("STUDENT", "Student"), ("PROFESSOR", "Professor")], validators=[DataRequired()])
    name = StringField("Name", filters=[strip_text], validators=[DataRequired(), Length(min=2, max=120)])
    email = EmailField("Email", filters=[strip_text], validators=[DataRequired(), Email(), Length(max=254)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=10, max=128)])
    confirm_password = PasswordField(
        "Confirm password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )
    submit = SubmitField("Create account")


class LoginForm(FlaskForm):
    email = EmailField("Email", filters=[strip_text], validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])
    remember_me = BooleanField("Remember me")
    submit = SubmitField("Log-in")
