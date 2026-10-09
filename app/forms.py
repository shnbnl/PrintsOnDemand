"""Authentication forms with server-side validation and CSRF tokens."""

from flask_wtf import FlaskForm
from wtforms import BooleanField, EmailField, PasswordField, RadioField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError

from app.professor_faculties import FACULTIES_BY_DEPARTMENT


def strip_text(value: str | None) -> str | None:
    return value.strip() if value else value


class RegistrationForm(FlaskForm):
    account_type = RadioField("Account Type", choices=[("STUDENT", "Student"), ("PROFESSOR", "Professor")], validators=[DataRequired()])
    name = StringField("Name", filters=[strip_text], validators=[DataRequired(), Length(min=2, max=120)])
    email = EmailField("Email", filters=[strip_text], validators=[DataRequired(), Email(), Length(max=254)])
    professor_department = SelectField(
        "Department",
        choices=[("", "Select department")] + [(department, department) for department in FACULTIES_BY_DEPARTMENT],
        validate_choice=False,
    )
    professor_faculty = SelectField("Faculty", choices=[("", "Select faculty")], validate_choice=False)
    password = PasswordField("Password", validators=[DataRequired(), Length(min=10, max=128)])
    confirm_password = PasswordField(
        "Confirm password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )
    submit = SubmitField("Create account")

    def validate_professor_department(self, field):
        if self.account_type.data == "PROFESSOR" and not field.data:
            raise ValidationError("Select your department for a Professor account.")
        if field.data and field.data not in FACULTIES_BY_DEPARTMENT:
            raise ValidationError("Select a valid department.")

    def validate_professor_faculty(self, field):
        if self.account_type.data != "PROFESSOR":
            if field.data:
                raise ValidationError("Faculty is only for Professor accounts.")
            return
        choices = FACULTIES_BY_DEPARTMENT.get(self.professor_department.data)
        if choices is None:
            return
        if choices and field.data not in choices:
            raise ValidationError("Select a faculty for your department.")
        if not choices and field.data:
            raise ValidationError("This department does not have a faculty selection.")


class LoginForm(FlaskForm):
    email = EmailField("Email", filters=[strip_text], validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])
    remember_me = BooleanField("Remember me")
    submit = SubmitField("Log-in")


class BlueStaffLoginForm(FlaskForm):
    name = StringField("Name", filters=[strip_text], validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Log-in")


class ShopStaffLoginForm(FlaskForm):
    identifier = StringField(
        "Staff email or name", filters=[strip_text],
        validators=[DataRequired(), Length(max=254)],
    )
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Log in to shop")
