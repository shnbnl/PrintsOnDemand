"""Controlled account provisioning for staff and administrators."""

import click
from email_validator import EmailNotValidError, validate_email
from flask import Flask, current_app
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Professor, User, UserRole


def register_commands(app: Flask) -> None:
    @app.cli.command("create-privileged-user")
    @click.option(
        "--role",
        type=click.Choice([UserRole.SHOP_STAFF.value, UserRole.ADMIN.value, UserRole.PROFESSOR.value]),
        required=True,
    )
    @click.option("--professor-id", type=int)
    @click.option("--name", prompt=True)
    @click.option("--email", prompt=True)
    @click.password_option(confirmation_prompt=True)
    def create_privileged_user(role: str, professor_id: int | None, name: str, email: str, password: str) -> None:
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
        user = User(name=name, email=email, role=UserRole(role), professor=professor)
        user.set_password(password)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError as error:
            db.session.rollback()
            raise click.ClickException("Account could not be created.") from error
        click.echo(f"Created {role} account for {user.email}.")

    @app.cli.command("seed-demo-shops")
    def seed_demo_shops_command() -> None:
        """Insert sample shops/prices only when intentionally run locally."""
        if current_app.config["ENV_NAME"] not in {"development", "testing"}:
            raise click.ClickException("Demo seeding is disabled in production.")
        from app.seed import seed_demo_shops

        added, coordinates_updated = seed_demo_shops()
        click.echo(
            f"Added {added} demo shops; refreshed verified coordinates on "
            f"{coordinates_updated} existing demo shops."
        )

    @app.cli.command("seed-demo-professors")
    def seed_demo_professors_command() -> None:
        """Insert fictional professors only when intentionally run locally."""
        if current_app.config["ENV_NAME"] not in {"development", "testing"}:
            raise click.ClickException("Demo seeding is disabled in production.")
        from app.seed import seed_demo_professors

        count = seed_demo_professors()
        click.echo(f"Added {count} demo professors. Existing professors were left unchanged.")
