"""Professor-controlled student delivery setting."""

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user
from flask_wtf import FlaskForm
from wtforms import BooleanField, StringField, SubmitField
from wtforms.validators import Length

from app.authorization import roles_required
from app.extensions import db
from app.forms import strip_text
from app.models import UserRole


professor_settings_bp = Blueprint("professor_settings", __name__, url_prefix="/professor")


class DeliverySettingsForm(FlaskForm):
    department = StringField("Your department", filters=[strip_text], validators=[Length(max=120)])
    accepts_student_deliveries = BooleanField("Accept student print deliveries")
    submit = SubmitField("Save setting")


@professor_settings_bp.route("/settings", methods=["GET", "POST"])
@roles_required(UserRole.PROFESSOR)
def settings():
    profile = current_user.professor
    form = DeliverySettingsForm()
    if form.validate_on_submit():
        if form.department.data:
            current_user.professor_department = form.department.data
        current_user.student_delivery_preference = bool(form.accepts_student_deliveries.data)
        if profile is not None:
            profile.accepts_student_deliveries = current_user.student_delivery_preference
        db.session.commit()
        flash(
            "Student delivery setting updated." if profile is not None
            else "Preference saved. Blue and Silver must link your professor profile before it takes effect.",
            "success",
        )
        return redirect(url_for("professor_settings.settings"))
    if not form.is_submitted():
        form.department.data = current_user.professor_department or (profile.department if profile else None)
        form.accepts_student_deliveries.data = (
            profile.accepts_student_deliveries if profile is not None
            else current_user.student_delivery_preference
        )
    return render_template("professors/settings.html", form=form, profile=profile)
