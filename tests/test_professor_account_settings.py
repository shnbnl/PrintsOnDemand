"""Professor registration details and delivery setting before/after shop linking."""

from sqlalchemy import select

from app.extensions import db
from app.models import Professor, User, UserRole
from app.services.admin_management import save_professor
from app.services.professors import selectable_professors
from test_auth import csrf_token, login, register
from test_orders import approved_professor, sign_in, student


def test_professor_registration_requires_department_without_claiming_managed_profile(client, test_app):
    page = client.get("/auth/register?account_type=PROFESSOR")
    assert b"Department (Professor accounts)" in page.data
    missing = register(client, account_type="PROFESSOR", name="Maria Santos",
                       email="maria.santos@example.edu")
    assert missing.status_code == 200
    assert b"Enter your department" in missing.data
    with test_app.app_context():
        assert db.session.scalar(select(User)) is None

    created = register(client, account_type="PROFESSOR", name="Maria Santos",
                       email="maria.santos@example.edu", professor_department="Computer Science")
    assert created.status_code == 302
    with test_app.app_context():
        account = db.session.scalar(select(User))
        assert account.role == UserRole.PROFESSOR
        assert account.professor_department == "Computer Science"
        assert account.professor_id is None
        assert account.student_delivery_preference is False
        assert db.session.scalar(select(Professor)) is None


def test_pending_professor_can_save_preference_without_becoming_student_selectable(client, test_app):
    profile_id = approved_professor(test_app, accepts=False)
    assert register(client, account_type="PROFESSOR", name="Maria Santos",
                    email="maria.santos@example.edu", professor_department="Computer Science").status_code == 302
    assert login(client, email="maria.santos@example.edu").status_code == 302
    page = client.get("/professor/settings")
    assert page.status_code == 200
    assert b"has not linked" in page.data
    assert b"Computer Science" in page.data
    assert client.post("/professor/settings", data={
        "department": "Mathematics", "accepts_student_deliveries": "y",
    }).status_code == 400
    assert client.post("/professor/settings", data={
        "csrf_token": csrf_token(page), "department": "Mathematics",
        "accepts_student_deliveries": "y", "profile_id": str(profile_id),
    }).status_code == 302
    with test_app.app_context():
        account = db.session.scalar(select(User))
        assert account.professor_department == "Mathematics"
        assert account.student_delivery_preference is True
        assert account.professor_id is None
        profile = db.session.get(Professor, profile_id)
        assert profile.accepts_student_deliveries is False
        assert selectable_professors() == []

        save_professor(
            profile, name=profile.name, email=profile.email,
            department=profile.department, office=profile.office,
            faculty=profile.faculty, account_id=account.id,
            is_active=True, direct_send_approved=True,
            accepts_student_deliveries=False,
        )
    linked = client.get("/professor/settings")
    assert linked.status_code == 200
    assert b"has not linked" not in linked.data
    assert client.post("/professor/settings", data={
        "csrf_token": csrf_token(linked), "department": "Mathematics",
        "accepts_student_deliveries": "y",
    }).status_code == 302
    with test_app.app_context():
        assert db.session.get(Professor, profile_id).accepts_student_deliveries is True
        assert [record.id for record in selectable_professors()] == [profile_id]


def test_student_cannot_open_professor_setting(client, test_app):
    student_id = student(test_app)
    sign_in(client, student_id)
    assert client.get("/professor/settings").status_code == 403

