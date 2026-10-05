"""Controlled account provisioning for staff and administrators."""

import click
from uuid import uuid4
from email_validator import EmailNotValidError, validate_email
from flask import Flask, current_app
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.extensions import db
from app.models import PrintingShop, Professor, UploadedFile, User, UserRole
from app.models.user import BLUE_STAFF_EMAIL_DOMAIN
from app.storage import StorageError, get_account_deletion_storage
from app.services.professors import PROFESSOR_DELIVERY_SHOP


def register_commands(app: Flask) -> None:
    @app.cli.command("cleanup-staged-uploads")
    def cleanup_checkout_uploads() -> None:
        """Remove expired, unattached checkout files without touching legacy or order files."""
        from app.services.staged_uploads import cleanup_staged_uploads

        try:
            count = cleanup_staged_uploads(
                retention_hours=current_app.config["CHECKOUT_STAGED_RETENTION_HOURS"]
            )
        except (OSError, StorageError, SQLAlchemyError, ValueError) as error:
            raise click.ClickException("Checkout upload cleanup failed. Check private storage and retry.") from error
        click.echo(f"Removed {count} expired staged checkout files.")

    @app.cli.command("recover-account-deletions")
    def recover_account_deletions() -> None:
        """Resolve interrupted private-file cleanup while the app is offline."""
        try:
            storage = get_account_deletion_storage()
            restored, purged = storage.recover_staged_deletions(
                lambda key: db.session.scalar(
                    select(UploadedFile.id).where(UploadedFile.storage_key == key)
                ) is not None
            )
        except (OSError, StorageError) as error:
            raise click.ClickException("Private-file recovery could not finish. Check server logs and storage permissions.") from error
        click.echo(f"Restored {restored} referenced uploads; removed {purged} unreferenced uploads.")

    @app.cli.command("create-privileged-user")
    @click.option(
        "--role",
        type=click.Choice([UserRole.SHOP_STAFF.value, UserRole.ADMIN.value, UserRole.PROFESSOR.value]),
        required=True,
    )
    @click.option("--professor-id", type=int)
    @click.option("--shop-id", type=int)
    @click.option("--name", prompt=True)
    @click.option("--email", prompt=True)
    @click.password_option(confirmation_prompt=True)
    def create_privileged_user(role: str, professor_id: int | None, shop_id: int | None, name: str, email: str, password: str) -> None:
        """Create a staff/admin/professor account from a trusted server shell."""
        name = name.strip()
        if len(name) < 2 or len(name) > 120:
            raise click.ClickException("Name must be between 2 and 120 characters.")
        if len(password) < 10 or len(password) > 128:
            raise click.ClickException("Password must be between 10 and 128 characters.")
        try:
            email = validate_email(email, check_deliverability=False).normalized
        except EmailNotValidError as error:
            raise click.ClickException("Enter a valid email address.") from error
        if len(email) > 254:
            raise click.ClickException("Email address is too long.")

        professor = None
        if role == UserRole.PROFESSOR:
            professor = db.session.get(Professor, professor_id) if professor_id else None
            if (professor is None or not professor.is_active or professor.account is not None
                    or professor.email != email.casefold()):
                raise click.ClickException("Select an active, unlinked professor with a matching email.")
        elif professor_id is not None:
            raise click.ClickException("--professor-id is only valid for a professor account.")
        shop = None
        if role == UserRole.SHOP_STAFF and shop_id is not None:
            shop = db.session.get(PrintingShop, shop_id)
            if shop is None:
                raise click.ClickException("Select an existing printing shop.")
        elif shop_id is not None:
            raise click.ClickException("--shop-id is only valid for a shop staff account.")
        user = User(name=name, email=email, role=UserRole(role), professor=professor, shop=shop)
        user.set_password(password)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError as error:
            db.session.rollback()
            raise click.ClickException("Account could not be created.") from error
        click.echo(f"Created {role} account for {user.email}.")

    @app.cli.command("create-blue-staff")
    @click.option("--name", prompt=True)
    @click.password_option(confirmation_prompt=True)
    def create_blue_staff(name: str, password: str) -> None:
        """Create a local Blue and Silver staff account using a name and password."""
        if current_app.config["ENV_NAME"] not in {"development", "testing"}:
            raise click.ClickException("Short-password Blue and Silver accounts are for local development only.")
        name = name.strip()
        if not 2 <= len(name) <= 120:
            raise click.ClickException("Name must be between 2 and 120 characters.")
        if not (5 <= len(password) <= 8 and password.isascii() and password.isalpha()):
            raise click.ClickException("Password must contain 5 to 8 letters.")
        shop = db.session.scalar(select(PrintingShop).where(PrintingShop.name == PROFESSOR_DELIVERY_SHOP))
        if shop is None:
            raise click.ClickException("Create Blue and Silver Bookstore before its staff account.")
        staff = db.session.scalars(select(User).where(
            User.role == UserRole.SHOP_STAFF, User.shop_id == shop.id,
        )).all()
        if any(user.name.casefold() == name.casefold() for user in staff):
            raise click.ClickException("This Blue and Silver staff name is already in use.")
        user = User(
            name=name, email=f"{uuid4().hex}@{BLUE_STAFF_EMAIL_DOMAIN}",
            role=UserRole.SHOP_STAFF, shop=shop,
        )
        user.set_password(password)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError as error:
            db.session.rollback()
            raise click.ClickException("Account could not be created.") from error
        click.echo(f"Created Blue and Silver staff account for {user.name}.")

    @app.cli.command("seed-sample-shops")
    def seed_sample_shops_command() -> None:
        """Insert sample shops/prices only when intentionally run locally."""
        if current_app.config["ENV_NAME"] not in {"development", "testing"}:
            raise click.ClickException("Sample data seeding is disabled in production.")
        from app.seed import seed_demo_shops

        added, coordinates_updated = seed_demo_shops()
        click.echo(
            f"Added {added} sample shops; refreshed verified coordinates on "
            f"{coordinates_updated} existing sample shops."
        )
    app.cli.add_command(click.Command(
        "seed-demo-shops", callback=seed_sample_shops_command.callback, hidden=True,
    ))

    @app.cli.command("seed-sample-professors")
    def seed_sample_professors_command() -> None:
        """Insert fictional professors only when intentionally run locally."""
        if current_app.config["ENV_NAME"] not in {"development", "testing"}:
            raise click.ClickException("Sample data seeding is disabled in production.")
        from app.seed import seed_demo_professors

        count = seed_demo_professors()
        click.echo(f"Added {count} sample professors. Existing professors were left unchanged.")
    app.cli.add_command(click.Command(
        "seed-demo-professors", callback=seed_sample_professors_command.callback, hidden=True,
    ))
