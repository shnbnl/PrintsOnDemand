"""Public foundation routes."""

from flask import Blueprint, jsonify, render_template, session


main_bp = Blueprint("main", __name__)


@main_bp.get("/")
def index():
    return render_template("main/index.html", play_account_delete_transition=session.pop("play_account_delete_transition", False))


@main_bp.get("/health")
def health():
    return jsonify(status="ok")
