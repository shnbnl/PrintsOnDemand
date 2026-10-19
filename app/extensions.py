"""Extension instances shared by the application factory."""

from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect


db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()


@login_manager.user_loader
def load_user(user_id: str):
    """Accept only live, server-issued authentication credentials."""
    from app.services.sessions import load_session_user

    return load_session_user(user_id)
