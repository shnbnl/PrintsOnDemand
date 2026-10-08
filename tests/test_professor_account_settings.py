"""Controlled Professor department and simple, role-guarded delivery setting."""

import re

from sqlalchemy import select

from app.extensions import db
from app.models import Faculty, Professor, ProfessorVerificationStatus, User, UserRole
from app.services.admin_management import save_professor
from app.services.professors import selectable_professors
from test_auth import csrf_token, login, register
from test_orders import approved_professor, sign_in, student


def department_options(response):
    field = re.search(rb'<select[^>]*id="professor_department"[^>]*>.*?</select>', response.data, re.S)
    assert field is not None
    return re.findall(rb'<option[^>]*value="([^"]*)"', field.group())


def test_registration_uses_exact_department_choices_and_rejects_arbitrary_values(client, test_app):
    page = client.get("/auth/register?account_type=PROFESSOR")
    assert department_options(page) == [b""] + [faculty.value.encode() for faculty in Faculty]
    missing = register(client, account_type="PROFESSOR", name="Maria Santos",
                       email="maria.santos@example.edu")
    assert missing.status_code == 200 and b"Select your department" in missing.data
    arbitrary = register(client, account_type="PROFESSOR", name="Maria Santos",
                         email="maria.santos@example.edu", professor_department="Computer Science")
    assert arbitrary.status_code == 200
    with test_app.app_context():
        assert db.session.scalar(select(User)) is None
    created = register(client, account_type="PROFESSOR", name="Maria Santos",
                       email="maria.santos@example.edu", professor_department="CCIS")
    assert created.status_code == 302
    with test_app.app_context():
        account = db.session.scalar(select(User))
        assert account.role == UserRole.PROFESSOR
        assert account.professor_department == "CCIS"
        assert account.professor_id is None
        assert db.session.scalar(select(Professor)) is None


def test_professor_settings_show_information_without_delivery_control(client, test_app):
    profile_id = approved_professor(test_app, accepts=False, linked=False)
    assert register(client, account_type="PROFESSOR", name="Maria Santos",
                    email="maria.santos@example.edu", professor_department="CCIS").status_code == 302
    assert login(client, email="maria.santos@example.edu").status_code == 302
    page = client.get("/account")
    assert page.status_code == 200
    assert b"Maria Santos" in page.data and b"CCIS" in page.data
    assert b"Your account is ready" not in page.data
    assert b"has not linked" not in page.data
    assert b'id="department"' not in page.data
    assert b"Student print deliveries" not in page.data
    assert b'role="switch"' not in page.data
    assert client.post("/account/professor-preference", data={
        "csrf_token": csrf_token(page), "accepts_student_deliveries": "y",
    }).status_code == 302
    with test_app.app_context():
        account = db.session.scalar(select(User))
        assert account.professor_department == "CCIS"
        assert account.student_delivery_preference is True
        assert account.professor_id is None
        assert db.session.get(Professor, profile_id).accepts_student_deliveries is False
        assert selectable_professors() == []
        profile = db.session.get(Professor, profile_id)
        account.professor_verification_status = ProfessorVerificationStatus.VERIFIED
        db.session.commit()
        save_professor(
            profile, name=profile.name, email=profile.email,
            department=profile.department, office=profile.office,
            faculty=profile.faculty, account_id=account.id,
            is_active=True, direct_send_approved=True, accepts_student_deliveries=False,
        )
    linked = client.get("/account")
    assert linked.status_code == 200 and b"Your profile is linked" not in linked.data
    assert b'id="department"' not in linked.data
    assert client.post("/account/professor-preference", data={
        "csrf_token": csrf_token(linked), "accepts_student_deliveries": "y",
        "department": "GE",  # The account's saved department cannot be changed here.
    }).status_code == 302
    with test_app.app_context():
        account = db.session.scalar(select(User))
        assert account.professor_department == "CCIS"
        assert db.session.get(Professor, profile_id).accepts_student_deliveries is True
        assert [record.id for record in selectable_professors()] == [profile_id]


def test_existing_account_without_department_can_select_one_once(client, test_app):
    account_id = student(test_app, "legacy@example.edu", role=UserRole.PROFESSOR)
    sign_in(client, account_id)
    page = client.get("/account")
    assert page.status_code == 200 and b'id="department"' not in page.data
    assert client.post("/account/professor-preference", data={
        "csrf_token": csrf_token(page), "accepts_student_deliveries": "y",
    }).status_code == 400
    invalid = client.post("/account/professor-preference", data={
        "csrf_token": csrf_token(client.get("/account")),
        "department": "Computer Science", "accepts_student_deliveries": "y",
    })
    assert invalid.status_code == 400
    with test_app.app_context():
        assert db.session.get(User, account_id).professor_department is None
        assert db.session.get(User, account_id).student_delivery_preference is False
    assert client.post("/account/professor-preference", data={
        "csrf_token": csrf_token(client.get("/account")),
        "department": "MITL", "accepts_student_deliveries": "y",
    }).status_code == 302
    saved = client.get("/account")
    assert b"MITL" in saved.data and b'id="department"' not in saved.data
    with test_app.app_context():
        assert db.session.get(User, account_id).student_delivery_preference is True


def test_existing_managed_department_is_displayed_when_account_has_none(client, test_app):
    profile_id = approved_professor(test_app, accepts=False, linked=False)
    account_id = student(test_app, "maria.santos@example.edu", role=UserRole.PROFESSOR)
    with test_app.app_context():
        db.session.get(User, account_id).professor_id = profile_id
        db.session.get(User, account_id).professor_verification_status = ProfessorVerificationStatus.VERIFIED
        db.session.commit()
    sign_in(client, account_id)
    page = client.get("/account")
    assert b"Computer Engineering" in page.data
    assert b'id="department"' not in page.data
    assert client.post("/account/professor-preference", data={
        "csrf_token": csrf_token(page), "accepts_student_deliveries": "y",
    }).status_code == 302
    with test_app.app_context():
        assert db.session.get(Professor, profile_id).accepts_student_deliveries is True


def test_student_cannot_open_professor_setting(client, test_app):
    student_id = student(test_app)
    sign_in(client, student_id)
    assert client.get("/professor/settings").status_code == 403
    assert client.post("/account/professor-preference", data={
        "csrf_token": csrf_token(client.get("/account")),
    }).status_code == 403
