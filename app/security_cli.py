"""Operator checks and backup commands. No web access or secrets in output."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import click
from sqlalchemy import select, text

from app.extensions import db
from app.models import User
from app.services.backups import BackupError, create_backup, gpg_filename, verify_archive


def register_security_commands(app):
    @app.cli.command("backup-data")
    def backup_data():
        """Create a public-key encrypted database + private upload backup."""
        try:
            target = create_backup()
        except Exception as error:
            # Tool stderr and connection strings can contain secrets.
            raise click.ClickException(str(error) if isinstance(error, BackupError)
                                       else "Backup failed; no completed backup was published.") from error
        click.echo(f"Encrypted backup created: {target}")

    @app.cli.command("verify-backup")
    @click.argument("backup", type=click.Path(exists=True, dir_okay=False, path_type=Path))
    def verify_backup(backup):
        """Decrypt with the recovery key and verify integrity without restoring."""
        if not shutil.which("gpg"):
            raise click.ClickException("Install gpg and import the recovery private key on the recovery machine.")
        try:
            with tempfile.TemporaryDirectory(prefix="prints-verify-") as temporary:
                directory = Path(temporary)
                directory.chmod(0o700)
                decrypted = directory / "snapshot.tar.gz"
                with decrypted.open("xb"):
                    pass
                decrypted.chmod(0o600)
                result = subprocess.run([
                    "gpg", "--batch", "--no-tty", "--yes", "--output", gpg_filename(decrypted),
                    "--decrypt", gpg_filename(backup),
                ], capture_output=True, timeout=1800)
                if result.returncode:
                    raise BackupError("Backup decryption failed. Check the recovery key.")
                count = verify_archive(decrypted)
        except Exception as error:
            raise click.ClickException(str(error) if isinstance(error, BackupError)
                                       else "Backup verification failed.") from error
        click.echo(f"Backup verified: database and {count} private documents. No data restored.")

    @app.cli.command("security-check")
    def security_check():
        """Check deployment configuration and DB privileges, without changing them."""
        checks = {
            "Debug disabled": not app.debug,
            "HTTPS enforced": app.config["FORCE_HTTPS"],
            "Trusted hosts configured": bool(app.config.get("TRUSTED_HOSTS")),
            "Secure authentication cookies": app.config["SESSION_COOKIE_SECURE"] and app.config["REMEMBER_COOKIE_SECURE"],
            "CSRF enabled": app.config.get("WTF_CSRF_ENABLED", True),
            "Strong signing key configured": len(str(app.secret_key)) >= 32 and bool(os.getenv("SECRET_KEY")),
            "Password hashes use supported algorithms": all(
                value.startswith(("scrypt:", "pbkdf2:sha256:"))
                for value in db.session.scalars(select(User.password_hash))
            ),
        }
        if db.engine.dialect.name == "postgresql":
            role = db.session.execute(text(
                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls FROM pg_roles WHERE rolname = current_user"
            )).one()
            checks["Database role has no administrative capabilities"] = not any(role)
            owns = db.session.execute(text(
                "SELECT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tableowner = current_user)"
            )).scalar_one()
            checks["Runtime DB account is separate from schema owner"] = not owns
        else:
            click.echo("REVIEW SQLite: restrict DB, instance directory, and private upload access to the app OS account.")
        backup_root = os.getenv("BACKUP_DIRECTORY", "")
        recent = list(Path(backup_root).glob("prints-backup-*.tar.gz.gpg")) if backup_root else []
        from time import time
        checks["Encrypted backup created within 36 hours"] = any(time() - path.stat().st_mtime < 36 * 3600 for path in recent)
        for label, passed in checks.items():
            click.echo(f"{'PASS' if passed else 'FAIL'} {label}")
        click.echo("REVIEW Verify host HTTPS/proxy settings, off-site backup copies, scheduled tasks, and a recovery drill separately.")
        if not all(checks.values()):
            raise click.ClickException("One or more deployment checks need attention.")
