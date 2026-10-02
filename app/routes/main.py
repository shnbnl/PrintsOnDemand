"""Public foundation routes."""

from flask import Blueprint, jsonify, render_template


main_bp = Blueprint("main", __name__)


@main_bp.get("/")
def index():
    return render_template("main/index.html")


@main_bp.get("/health")
def health():
    return jsonify(status="ok")
