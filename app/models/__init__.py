"""Import models so Flask-Migrate can discover their metadata."""

from app.models.user import User, UserRole

__all__ = ["User", "UserRole"]
