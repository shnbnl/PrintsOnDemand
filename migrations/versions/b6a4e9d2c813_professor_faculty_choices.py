"""Store professor faculty choices and expand delivery snapshots.

Revision ID: b6a4e9d2c813
Revises: a91c5d07e3b2
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "b6a4e9d2c813"
down_revision = "a91c5d07e3b2"
branch_labels = None
depends_on = None


def _foreign_keys(enabled):
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.get_context().autocommit_block():
            bind.exec_driver_sql(f"PRAGMA foreign_keys={'ON' if enabled else 'OFF'}")


def upgrade():
    op.add_column("users", sa.Column("professor_faculty", sa.String(120), nullable=True))
    _foreign_keys(False)
    try:
        with op.batch_alter_table("professors") as batch:
            batch.drop_constraint("professor_faculty_valid", type_="check")
            batch.alter_column("faculty", existing_type=sa.String(16), type_=sa.String(120), existing_nullable=True)
            batch.create_check_constraint("professor_faculty_valid", "faculty IS NULL OR length(faculty) <= 120")
        with op.batch_alter_table("orders") as batch:
            batch.drop_constraint("order_professor_faculty_valid", type_="check")
            batch.alter_column("professor_faculty", existing_type=sa.String(16), type_=sa.String(120), existing_nullable=True)
            batch.create_check_constraint("order_professor_faculty_valid", "professor_faculty IS NULL OR length(professor_faculty) <= 120")
    finally:
        _foreign_keys(True)

    bind = op.get_bind()
    users = bind.execute(sa.text("""
        SELECT id, name, email, professor_department, professor_id, student_delivery_preference
        FROM users WHERE role = 'PROFESSOR' AND professor_verification_status = 'VERIFIED'
    """)).mappings().all()
    for account in users:
        profile = bind.execute(sa.text(
            "SELECT id, faculty FROM professors WHERE id = :id OR email = :email ORDER BY id LIMIT 1"
        ), {"id": account["professor_id"] or -1, "email": account["email"]}).mappings().first()
        if profile is None:
            faculty = account["professor_department"] if account["professor_department"] in {
                "MITL", "ETYCB", "CHS", "CCIS", "CAS", "GE", "SHS", "IECELL", "CMET"
            } else None
            result = bind.execute(sa.text("""
                INSERT INTO professors (name, email, department, faculty, is_active,
                                        direct_send_approved, accepts_student_deliveries, created_at, updated_at)
                VALUES (:name, :email, :department, :faculty, :active, :approved, :accepts, :now, :now)
                RETURNING id
            """), dict(name=account["name"], email=account["email"], department=account["professor_department"],
                       faculty=faculty, active=True, approved=False,
                       accepts=bool(account["student_delivery_preference"]), now=datetime.now(timezone.utc)))
            profile_id = result.scalar_one()
        else:
            profile_id = profile["id"]
            faculty = profile["faculty"]
            bind.execute(sa.text("UPDATE professors SET name = :name, email = :email, department = :department WHERE id = :id"),
                         dict(name=account["name"], email=account["email"],
                              department=account["professor_department"], id=profile_id))
        bind.execute(sa.text("UPDATE users SET professor_id = :profile_id, professor_faculty = :faculty WHERE id = :id"),
                     dict(profile_id=profile_id, faculty=faculty, id=account["id"]))


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("""
        SELECT 1 FROM professors WHERE faculty IS NOT NULL AND faculty NOT IN
            ('MITL', 'CAS', 'ETYCB', 'CCIS', 'CHS', 'GE', 'IECELL', 'SHS')
        UNION SELECT 1 FROM orders WHERE professor_faculty IS NOT NULL AND professor_faculty NOT IN
            ('MITL', 'CAS', 'ETYCB', 'CCIS', 'CHS', 'GE', 'IECELL', 'SHS')
        LIMIT 1
    """)).first():
        raise RuntimeError("Cannot downgrade while expanded faculty names exist.")
    _foreign_keys(False)
    try:
        with op.batch_alter_table("orders") as batch:
            batch.drop_constraint("order_professor_faculty_valid", type_="check")
            batch.alter_column("professor_faculty", existing_type=sa.String(120), type_=sa.String(16), existing_nullable=True)
            batch.create_check_constraint("order_professor_faculty_valid", "professor_faculty IS NULL OR professor_faculty IN ('MITL', 'CAS', 'ETYCB', 'CCIS', 'CHS', 'GE', 'IECELL', 'SHS')")
        with op.batch_alter_table("professors") as batch:
            batch.drop_constraint("professor_faculty_valid", type_="check")
            batch.alter_column("faculty", existing_type=sa.String(120), type_=sa.String(16), existing_nullable=True)
            batch.create_check_constraint("professor_faculty_valid", "faculty IS NULL OR faculty IN ('MITL', 'CAS', 'ETYCB', 'CCIS', 'CHS', 'GE', 'IECELL', 'SHS')")
    finally:
        _foreign_keys(True)
    op.drop_column("users", "professor_faculty")
