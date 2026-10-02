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
    """Reload active users from the database for each authenticated request."""
    from app.models import User

    try:
        user = db.session.get(User, int(user_id))
    except ValueError:
        return None
    return user if user and user.is_active else None
