"""Student-owned private file uploads and print configuration."""

import hashlib
from io import BytesIO

from flask import Blueprint, abort, current_app, flash, redirect, render_template, send_file, url_for
from flask_login import current_user
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import RequestEntityTooLarge

from app.authorization import roles_required
from app.extensions import db
from app.file_forms import PrintConfigurationForm, UploadForm
from app.models import ColorMode, PaperSize, PrintConfiguration, UploadedFile, UserRole
from app.storage import StorageError, get_storage
from app.storage.validation import ALLOWED_EXTENSIONS, UploadValidationError, validate_upload


files_bp = Blueprint("files", __name__, url_prefix="/files")
FILE_ACCEPT_TYPES = ",".join(f".{extension}" for extension in sorted(ALLOWED_EXTENSIONS))


def owned_file(file_id: int) -> UploadedFile:
    record = db.session.scalar(
        select(UploadedFile).where(
            UploadedFile.id == file_id, UploadedFile.user_id == current_user.id
        )
    )
    if record is None:
        abort(404)
    return record


def private_storage():
    try:
        return get_storage()
    except StorageError:
        current_app.logger.error("Private file storage is unavailable")
        abort(503, description="Private file storage is unavailable.")


@files_bp.get("")
@roles_required(UserRole.STUDENT)
def index():
    records = db.session.scalars(
        select(UploadedFile).where(UploadedFile.user_id == current_user.id)
        .order_by(UploadedFile.created_at.desc(), UploadedFile.id.desc())
    ).all()
    return render_template("files/index.html", records=records)


@files_bp.route("/upload", methods=["GET", "POST"])
@roles_required(UserRole.STUDENT)
def upload():
    form = UploadForm()
    if form.validate_on_submit():
        try:
            validated = validate_upload(form.file.data, current_app.config["UPLOAD_MAX_SIZE"])
        except UploadValidationError as error:
            form.file.errors.append(str(error))
            return render_template(
                "files/upload.html", form=form, extensions=ALLOWED_EXTENSIONS,
                accept_types=FILE_ACCEPT_TYPES,
            ), error.status_code

        storage = private_storage()
        try:
            key = storage.save(validated.data, validated.extension)
        except (OSError, StorageError):
            current_app.logger.exception("Could not save private upload")
            abort(503, description="Private file storage is unavailable.")
        record = UploadedFile(
            user_id=current_user.id,
            original_filename=validated.original_filename,
            stored_filename=key,
            storage_key=key,
            mime_type=validated.mime_type,
            file_extension=validated.extension,
            file_size=validated.size,
            sha256=validated.sha256,
        )
        db.session.add(record)
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            storage.delete(key)
            current_app.logger.exception("Could not record private upload")
            abort(500)
        flash("File uploaded successfully. No order has been submitted.", "success")
        return redirect(url_for("files.detail", file_id=record.id))
    return render_template(
        "files/upload.html", form=form, extensions=ALLOWED_EXTENSIONS,
        accept_types=FILE_ACCEPT_TYPES,
    )


@files_bp.get("/<int:file_id>")
@roles_required(UserRole.STUDENT)
def detail(file_id: int):
    return render_template("files/detail.html", record=owned_file(file_id))


@files_bp.get("/<int:file_id>/download")
@roles_required(UserRole.STUDENT)
def download(file_id: int):
    record = owned_file(file_id)
    try:
        data = private_storage().read(record.storage_key)
    except StorageError:
        abort(404)
    if len(data) != record.file_size or hashlib.sha256(data).hexdigest() != record.sha256:
        current_app.logger.warning("Stored upload failed integrity check for file %s", file_id)
        abort(404)
    return send_file(
        BytesIO(data), mimetype=record.mime_type, as_attachment=True,
        download_name=record.original_filename,
    )


@files_bp.route("/<int:file_id>/configure", methods=["GET", "POST"])
@roles_required(UserRole.STUDENT)
def configure(file_id: int):
    record = owned_file(file_id)
    form = PrintConfigurationForm(obj=record.configuration)
    if form.validate_on_submit():
        configuration = record.configuration or PrintConfiguration(uploaded_file=record)
        configuration.paper_size = PaperSize(form.paper_size.data)
        configuration.color_mode = ColorMode(form.color_mode.data)
        configuration.quantity = form.quantity.data
        configuration.is_rush = form.is_rush.data
        db.session.add(configuration)
        db.session.commit()
        flash("Print configuration saved. No order has been submitted.", "success")
        return redirect(url_for("files.detail", file_id=record.id))
    return render_template(
        "files/configure.html", record=record, form=form,
        max_quantity=current_app.config["UPLOAD_MAX_QUANTITY"],
    )


@files_bp.post("/<int:file_id>/delete")
@roles_required(UserRole.STUDENT)
def delete(file_id: int):
    record = owned_file(file_id)
    # Stage 4 has no orders. Add an order-attachment guard when orders are introduced.
    try:
        private_storage().delete(record.storage_key)
    except (OSError, StorageError):
        current_app.logger.warning("Could not delete private upload for file %s", file_id)
        abort(404)
    db.session.delete(record)
    db.session.commit()
    flash("File deleted.", "success")
    return redirect(url_for("files.index"))


@files_bp.errorhandler(RequestEntityTooLarge)
def too_large(error):
    return render_template("files/too_large.html"), 413
