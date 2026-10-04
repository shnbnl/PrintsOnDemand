"""Authentication forms with server-side validation and CSRF tokens."""

from flask_wtf import FlaskForm
from wtforms import BooleanField, EmailField, PasswordField, RadioField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError


def strip_text(value: str | None) -> str | None:
    return value.strip() if value else value


class RegistrationForm(FlaskForm):
    account_type = RadioField("Account Type", choices=[("STUDENT", "Student"), ("PROFESSOR", "Professor")], validators=[DataRequired()])
    name = StringField("Name", filters=[strip_text], validators=[DataRequired(), Length(min=2, max=120)])
    email = EmailField("Email", filters=[strip_text], validators=[DataRequired(), Email(), Length(max=254)])
    professor_department = StringField("Department (Professor accounts)", filters=[strip_text], validators=[Length(max=120)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=10, max=128)])
    confirm_password = PasswordField(
        "Confirm password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )
    submit = SubmitField("Create account")

    def validate_professor_department(self, field):
        if self.account_type.data == "PROFESSOR" and not field.data:
            raise ValidationError("Enter your department for a Professor account.")


class LoginForm(FlaskForm):
    email = EmailField("Email", filters=[strip_text], validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])
    remember_me = BooleanField("Remember me")
    submit = SubmitField("Log-in")
