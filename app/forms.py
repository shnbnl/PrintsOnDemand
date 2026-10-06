"""Authentication forms with server-side validation and CSRF tokens."""

from flask_wtf import FlaskForm
from wtforms import BooleanField, EmailField, PasswordField, RadioField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError

from app.models import Faculty


def strip_text(value: str | None) -> str | None:
    return value.strip() if value else value


class RegistrationForm(FlaskForm):
    account_type = RadioField("Account Type", choices=[("STUDENT", "Student"), ("PROFESSOR", "Professor")], validators=[DataRequired()])
    name = StringField("Name", filters=[strip_text], validators=[DataRequired(), Length(min=2, max=120)])
    email = EmailField("Email", filters=[strip_text], validators=[DataRequired(), Email(), Length(max=254)])
    professor_department = SelectField(
        "Department (Professor accounts)",
        choices=[("", "Select department")] + [(department.value, department.value) for department in Faculty],
        validate_choice=False,
    )
    password = PasswordField("Password", validators=[DataRequired(), Length(min=10, max=128)])
    confirm_password = PasswordField(
        "Confirm password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )
    submit = SubmitField("Create account")

    def validate_professor_department(self, field):
        if self.account_type.data == "PROFESSOR" and not field.data:
            raise ValidationError("Select your department for a Professor account.")
        if field.data and field.data not in {department.value for department in Faculty}:
            raise ValidationError("Select a valid department.")


class LoginForm(FlaskForm):
    email = EmailField("Email", filters=[strip_text], validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])
    remember_me = BooleanField("Remember me")
    submit = SubmitField("Log in")


class PasswordResetRequestForm(FlaskForm):
    email = EmailField("Account email", filters=[strip_text], validators=[DataRequired(), Email(), Length(max=254)])
    submit = SubmitField("Send reset link")


class PasswordResetForm(FlaskForm):
    password = PasswordField("New password", validators=[DataRequired(), Length(min=10, max=128)])
    confirm_password = PasswordField("Confirm new password", validators=[DataRequired(), EqualTo("password")])
    submit = SubmitField("Set new password")


class BlueStaffLoginForm(FlaskForm):
    name = StringField("Name", filters=[strip_text], validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Log in")


class ShopStaffLoginForm(FlaskForm):
    identifier = StringField(
        "Staff email or name", filters=[strip_text],
        validators=[DataRequired(), Length(max=254)],
    )
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Log in to shop")
