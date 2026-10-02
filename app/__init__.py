"""Flask application factory for Prints On Demand."""

from flask import Flask, render_template
from dotenv import load_dotenv

from app.config import configure_runtime, select_config
from app.extensions import csrf, db, login_manager, migrate


def create_app(config_object: object | None = None) -> Flask:
    """Create an application with configuration and extensions initialized."""
    load_dotenv()

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object or select_config())
    configure_runtime(app)

    db.init_app(app)
    from . import models  # Import future model definitions for migration discovery.

    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    from app.routes.main import main_bp

    app.register_blueprint(main_bp)

    @app.errorhandler(404)
    def page_not_found(error):
        return render_template("main/error.html", message="Page not found."), 404

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
