"""CSRF-protected professor and staff-assignment forms."""

from flask_wtf import FlaskForm
from wtforms import BooleanField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, Length, ValidationError

from app.professor_faculties import ALL_FACULTIES, LEGACY_FACULTIES, faculty_for_account


class ProfessorForm(FlaskForm):
    is_active = BooleanField("Active", default=True)
    direct_send_approved = BooleanField("Approved for Direct-to-Professor")
    accepts_student_deliveries = BooleanField("Accept student print deliveries")
    submit = SubmitField("Save professor")


class StaffProfessorForm(ProfessorForm):
    name = StringField("Professor name", validators=[DataRequired(), Length(max=120)])
    email = StringField("Professor email", validators=[DataRequired(), Email(), Length(max=254)])
    department = SelectField("Department", choices=[("", "Select a department")] + [
        (value, value) for value in sorted(LEGACY_FACULTIES)
    ], validators=[DataRequired()])
    faculty = SelectField("Faculty / program", choices=[("", "Select a Faculty / program")] + [
        (value, value) for value in sorted(ALL_FACULTIES)
    ])
    office = StringField("Delivery location", validators=[DataRequired(), Length(max=120)])
    direct_send_approved = BooleanField("Approved for Direct-to-Professor", default=True)
    accepts_student_deliveries = BooleanField("Accept student print deliveries", default=True)

    def validate_faculty(self, field):
        if faculty_for_account(self.department.data, field.data) is None:
            raise ValidationError("Select a Faculty / program belonging to this department.")


class StaffShopForm(FlaskForm):
    shop_id = SelectField("Assigned shop", coerce=int)
    submit = SubmitField("Save assignment")
