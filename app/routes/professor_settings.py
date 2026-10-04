"""Professor-controlled student delivery setting."""

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user
from flask_wtf import FlaskForm
from wtforms import BooleanField, SelectField, SubmitField
from wtforms.validators import ValidationError

from app.authorization import roles_required
from app.extensions import db
from app.models import Faculty, UserRole


professor_settings_bp = Blueprint("professor_settings", __name__, url_prefix="/professor")


class DeliverySettingsForm(FlaskForm):
    department = SelectField(
        "Department", choices=[("", "Select department")] + [(item.value, item.value) for item in Faculty],
        validate_choice=False,
    )
    accepts_student_deliveries = BooleanField("Accept student print deliveries")
    submit = SubmitField("Save setting")

    def validate_department(self, field):
        if field.data and field.data not in {item.value for item in Faculty}:
            raise ValidationError("Select a valid department.")


@professor_settings_bp.route("/settings", methods=["GET", "POST"])
@roles_required(UserRole.PROFESSOR)
def settings():
    profile = current_user.professor
    department = current_user.professor_department or (profile.department if profile else None)
    needs_department = not department
    form = DeliverySettingsForm()
    if form.validate_on_submit():
        if needs_department and not form.department.data:
            form.department.errors.append("Select your department.")
        else:
            if needs_department:
                current_user.professor_department = form.department.data
            current_user.student_delivery_preference = bool(form.accepts_student_deliveries.data)
            if profile is not None:
                profile.accepts_student_deliveries = current_user.student_delivery_preference
            db.session.commit()
            flash("Student delivery setting updated.", "success")
            return redirect(url_for("professor_settings.settings"))
    if not form.is_submitted():
        form.accepts_student_deliveries.data = (
            profile.accepts_student_deliveries if profile is not None
            else current_user.student_delivery_preference
        )
    return render_template(
        "professors/settings.html", form=form, department=department,
        needs_department=needs_department,
    )
