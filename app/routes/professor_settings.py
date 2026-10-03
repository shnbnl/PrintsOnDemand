"""Professor-controlled student delivery setting."""

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user
from flask_wtf import FlaskForm
from wtforms import BooleanField, SubmitField

from app.authorization import roles_required
from app.extensions import db
from app.models import UserRole


professor_settings_bp = Blueprint("professor_settings", __name__, url_prefix="/professor")


class DeliverySettingsForm(FlaskForm):
    accepts_student_deliveries = BooleanField("Accept student print deliveries")
    submit = SubmitField("Save setting")


@professor_settings_bp.route("/settings", methods=["GET", "POST"])
@roles_required(UserRole.PROFESSOR)
def settings():
    profile = current_user.professor
    if profile is None:
        abort(403)
    form = DeliverySettingsForm()
    if form.validate_on_submit():
        profile.accepts_student_deliveries = bool(form.accepts_student_deliveries.data)
        db.session.commit()
        flash("Student delivery setting updated.", "success")
        return redirect(url_for("professor_settings.settings"))
    if not form.is_submitted():
        form.accepts_student_deliveries.data = profile.accepts_student_deliveries
    return render_template("professors/settings.html", form=form, profile=profile)
