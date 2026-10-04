"""Professor model, eligibility, and explicit demo seeding."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Professor, ProfessorVerificationStatus, User, UserRole
from app.seed import seed_demo_professors
from app.services.professors import selectable_professors


def test_professor_fields_defaults_and_normalized_unique_email(test_app):
    with test_app.app_context():
        professor = Professor(name="  Maria Santos  ", email="  MARIA.SANTOS@EXAMPLE.EDU  ")
        db.session.add(professor)
        db.session.commit()
        assert professor.name == "Maria Santos"
        assert professor.email == "maria.santos@example.edu"
        assert professor.department is None and professor.office is None
        assert professor.is_active is True
        assert professor.direct_send_approved is False
        assert professor.accepts_student_deliveries is False
        assert professor.created_at is not None and professor.updated_at is not None
        db.session.add(Professor(name="Other", email="maria.santos@example.edu"))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


@pytest.mark.parametrize("field,value", [
    ("name", ""), ("name", "   "), ("name", None),
    ("email", ""), ("email", None),
    ("email", "invalid"), ("email", "bad@"),
])
def test_professor_rejects_invalid_required_fields(test_app, field, value):
    with test_app.app_context():
        values = {"name": "Demo Professor", "email": "demo@example.edu"}
        values[field] = value
        with pytest.raises(ValueError):
            Professor(**values)


@pytest.mark.parametrize("missing", ["name", "email"])
def test_professor_database_requires_name_and_email(test_app, missing):
    with test_app.app_context():
        values = {"name": "Demo Professor", "email": "demo@example.edu"}
        del values[missing]
        db.session.add(Professor(**values))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_selectable_filter_all_four_states(test_app):
    with test_app.app_context():
        for active, approved in ((True, True), (True, False), (False, True), (False, False)):
            db.session.add(Professor(
                name=f"Demo {active} {approved}",
                email=f"demo-{active}-{approved}@example.edu",
                is_active=active, direct_send_approved=approved,
                accepts_student_deliveries=True,
                faculty="MITL",
            ))
        db.session.commit()
        eligible = db.session.scalar(select(Professor).where(Professor.is_active.is_(True), Professor.direct_send_approved.is_(True)))
        account = User(name=eligible.name, email=eligible.email, role=UserRole.PROFESSOR,
                       professor=eligible, professor_verification_status=ProfessorVerificationStatus.VERIFIED)
        account.set_password("A-strong-password-123")
        db.session.add(account)
        db.session.commit()
        assert [p.email for p in selectable_professors()] == ["demo-True-True@example.edu".casefold()]


def test_demo_seed_is_explicit_idempotent_and_does_not_overwrite(test_app):
    with test_app.app_context():
        assert seed_demo_professors() == 4
        maria = db.session.scalar(select(Professor).where(Professor.email == "maria.santos@example.edu"))
        maria.direct_send_approved = False
        db.session.commit()
        assert seed_demo_professors() == 0
        assert maria.direct_send_approved is False
        assert len(db.session.scalars(select(Professor)).all()) == 4
    runner = test_app.test_cli_runner()
    result = runner.invoke(args=["seed-demo-professors"])
    assert result.exit_code == 0
    assert "Added 0 demo professors" in result.output
    test_app.config["ENV_NAME"] = "production"
    result = runner.invoke(args=["seed-demo-professors"])
    assert result.exit_code != 0
