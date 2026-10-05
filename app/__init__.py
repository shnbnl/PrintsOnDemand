"""Flask application factory for Prints On Demand."""

import sqlite3

from flask import Flask, render_template, request
from dotenv import load_dotenv
from sqlalchemy import event
from sqlalchemy.engine import Engine
from werkzeug.routing import IntegerConverter

from app.config import configure_runtime, select_config
from app.extensions import csrf, db, login_manager, migrate


class DatabaseIdConverter(IntegerConverter):
    """Reject path IDs that cannot fit in the database's signed 64-bit key type."""

    def __init__(self, url_map):
        super().__init__(url_map, min=1, max=2**63 - 1)


@event.listens_for(Engine, "connect")
def enforce_sqlite_foreign_keys(connection, record):
    """SQLite needs this opt-in to enforce the same FK rules as PostgreSQL."""
    if isinstance(connection, sqlite3.Connection):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def create_app(config_object: object | None = None) -> Flask:
    """Create an application with configuration and extensions initialized."""
    load_dotenv()

    app = Flask(__name__, instance_relative_config=True)
    app.url_map.converters["int"] = DatabaseIdConverter
    app.config.from_object(config_object or select_config())
    configure_runtime(app)

    db.init_app(app)
    from . import models  # Import future model definitions for migration discovery.

    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    from app.routes.access import access_bp
    from app.routes.account import account_bp
    from app.routes.admin_management import admin_management_bp
    from app.routes.auth import auth_bp
    from app.routes.files import files_bp
    from app.routes.main import main_bp
    from app.routes.orders import orders_bp
    from app.routes.payment_verification import payment_verification_bp
    from app.routes.professor_settings import professor_settings_bp
    from app.routes.shop_admin import shop_admin_bp
    from app.routes.shop_staff import shop_staff_bp
    from app.routes.shops import shops_bp
    from app.routes.staff_orders import staff_orders_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(payment_verification_bp)
    app.register_blueprint(professor_settings_bp)
    app.register_blueprint(access_bp)
    app.register_blueprint(admin_management_bp)
    app.register_blueprint(shops_bp)
    app.register_blueprint(shop_admin_bp)
    app.register_blueprint(shop_staff_bp)
    app.register_blueprint(staff_orders_bp)
    login_manager.login_view = "auth.login"

    @app.after_request
    def add_security_headers(response):
        """Apply low-risk browser protections to every application response."""
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        # Google Maps website-restricted browser keys require the site's origin
        # on cross-origin API requests; keep the stricter default elsewhere.
        response.headers["Referrer-Policy"] = (
            "strict-origin-when-cross-origin"
            if request.endpoint == "shops.map_view" else "same-origin"
        )
        return response

    from app.cli import register_commands

    register_commands(app)

    @app.errorhandler(404)
    def page_not_found(error):
        return render_template("main/error.html", message="Page not found."), 404

    @app.errorhandler(403)
    def forbidden(error):
        return render_template("main/error.html", message="Access denied."), 403

    @app.errorhandler(500)
    def internal_error(error):
        return render_template("main/error.html", message="Something went wrong."), 500

    @app.cli.command("check-db")
    def check_db() -> None:
        """Confirm the configured database accepts a simple query."""
        from sqlalchemy import text

        with db.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        print("Database connection OK.")

    return app
