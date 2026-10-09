"""Only Blue and Silver verifies Professor accounts; eligibility is server-side."""

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import Professor, ProfessorVerificationStatus, User, UserRole
from app.services.professors import ProfessorSelectionError, professor_can_self_deliver, selectable_professors, validate_professor_selection
from test_auth import register
from test_orders import approved_professor, file, offer_professor_service, professor_review, shop, sign_in, student, token


def blue_team(app):
    blue = shop(app, name="Blue and Silver Bookstore")
    staff = student(app, "blue.staff@example.edu", UserRole.SHOP_STAFF)
    with app.app_context():
        db.session.get(User, staff).shop_id = blue
        db.session.commit()
    return blue, staff


def test_registration_starts_pending_and_only_blue_can_verify_or_reject(client, test_app):
    blue, blue_staff = blue_team(test_app)
    assert register(client, account_type="STUDENT").status_code == 302
    assert register(client, account_type="PROFESSOR", name="Juan Dela Cruz",
                    email="juan@example.edu", professor_department="CCIS").status_code == 302
    with test_app.app_context():
        account = db.session.scalar(select(User).where(User.email == "juan@example.edu"))
        account_id = account.id
        assert account.professor_verification_status == ProfessorVerificationStatus.PENDING
        assert account.professor_id is None
    index = "/admin/professors"
    verify = f"{index}/accounts/{account_id}/verify"
    reject = f"{index}/accounts/{account_id}/reject"
    assert client.get(index).status_code == 302
    for role, name in ((UserRole.STUDENT, "student"), (UserRole.PROFESSOR, "professor")):
        actor = student(test_app, f"{name}.other@example.edu", role)
        sign_in(client, actor)
        assert client.get(index).status_code == 403
        assert client.get(index + "/new").status_code == 403
        assert client.post(verify, data={"csrf_token": token(client.get("/student" if role == UserRole.STUDENT else "/professor"))}).status_code == 403
        assert client.post(reject, data={"csrf_token": token(client.get("/student" if role == UserRole.STUDENT else "/professor"))}).status_code == 403
    admin = student(test_app, "admin@example.edu", UserRole.ADMIN)
    sign_in(client, admin)
    assert client.get(index).status_code == 403
    for shop_name in ("CHALECOSPOT", "Iced Design and Prints", "Pixels Print and Press"):
        other = shop(test_app, name=shop_name)
        staff = student(test_app, shop_name.split()[0].lower() + "@example.edu", UserRole.SHOP_STAFF)
        with test_app.app_context():
            db.session.get(User, staff).shop_id = other
            db.session.commit()
        sign_in(client, staff)
        assert client.get(index).status_code == 403
        assert client.get(index + "/new").status_code == 403
        assert client.post(verify, data={"csrf_token": token(client.get("/shop")), "shop_id": str(blue)}).status_code == 403
    sign_in(client, blue_staff)
    page = client.get(index)
    assert page.status_code == 200 and b"Pending Verification" in page.data
    assert b"Juan Dela Cruz" in page.data and b"CCIS" in page.data
    assert client.post(verify).status_code == 400
    assert client.post(verify, data={"csrf_token": token(page), "account_id": "999", "shop_id": "999", "role": "ADMIN"}).status_code == 302
    with test_app.app_context():
        account = db.session.get(User, account_id)
        assert account.professor_verification_status == ProfessorVerificationStatus.VERIFIED
        assert account.professor_id is not None
        assert account.professor.department == "CCIS"
        assert account.professor.faculty == "Information Technology"
    assert client.post(reject, data={"csrf_token": token(client.get(index))}).status_code == 400
    assert client.post(f"{index}/accounts/999999/verify", data={"csrf_token": token(client.get(index))}).status_code == 404


def test_rejection_and_automatic_profile_creation_are_trusted_actions(client, test_app):
    blue, staff = blue_team(test_app)
    assert register(client, account_type="PROFESSOR", name="Rejected Professor",
                    email="rejected@example.edu", professor_department="CAS").status_code == 302
    with test_app.app_context():
        rejected_id = db.session.scalar(select(User.id).where(User.email == "rejected@example.edu"))
    sign_in(client, staff)
    page = client.get("/admin/professors")
    reject = f"/admin/professors/accounts/{rejected_id}/reject"
    assert client.post(reject, data={"csrf_token": token(page)}).status_code == 302
    with test_app.app_context():
        assert db.session.get(User, rejected_id).professor_verification_status == ProfessorVerificationStatus.REJECTED
    assert b"Rejected requests" in client.get("/admin/professors").data
    assert client.post(f"/admin/professors/accounts/{rejected_id}/verify", data={
        "csrf_token": token(client.get("/admin/professors")),
    }).status_code == 400

    pending_id = student(test_app, "verified@example.edu", UserRole.PROFESSOR)
    with test_app.app_context():
        pending = db.session.get(User, pending_id)
        pending.name = "Verified Professor"
        pending.professor_department = "MITL"
        db.session.commit()
    page = client.get("/admin/professors")
    assert client.post(f"/admin/professors/accounts/{pending_id}/verify", data={
        "csrf_token": token(page),
    }).status_code == 302
    assert client.get(f"/admin/professors/new?account_id={pending_id}").status_code == 404
    with test_app.app_context():
        account = db.session.get(User, pending_id)
        profile = account.professor
        assert profile.account.id == pending_id
        assert profile.is_active and not profile.direct_send_approved
        assert profile.account.professor_department == "MITL"
        assert selectable_professors() == []
        profile_id = profile.id
    edit = f"/admin/professors/{profile_id}/edit"
    assert client.post(edit, data={
        "csrf_token": token(client.get(edit)), "name": "Forged Name",
        "email": "forged@example.edu", "department": "CAS", "faculty": "Psychology",
        "account_id": "999", "is_active": "y", "direct_send_approved": "y",
        "accepts_student_deliveries": "y",
    }).status_code == 302
    with test_app.app_context():
        account = db.session.get(User, pending_id)
        assert account.professor_department == "MITL"
        assert account.professor.name == "Verified Professor"
        assert account.professor.email == "verified@example.edu"
        assert account.professor.faculty == "MITL"
        assert [item.id for item in selectable_professors()] == [profile_id]
    assert client.post(edit, data={
        "csrf_token": token(client.get(edit)),
    }).status_code == 302
    with test_app.app_context():
        assert not db.session.get(Professor, profile_id).is_active
        assert selectable_professors() == []


@pytest.mark.parametrize("change", ["pending", "rejected", "inactive", "unlinked", "declined", "no_faculty"])
def test_student_selection_requires_every_verification_condition(test_app, change):
    blue, _ = blue_team(test_app)
    offer_professor_service(test_app, blue)
    profile_id = approved_professor(test_app)
    student_id = student(test_app, "student.other@example.edu")
    with test_app.app_context():
        profile = db.session.get(Professor, profile_id)
        account = profile.account
        if change == "pending":
            account.professor_verification_status = ProfessorVerificationStatus.PENDING
        elif change == "rejected":
            account.professor_verification_status = ProfessorVerificationStatus.REJECTED
        elif change == "inactive":
            profile.is_active = False
        elif change == "unlinked":
            account.professor = None
        elif change == "declined":
            profile.accepts_student_deliveries = False
        else:
            profile.faculty = None
        db.session.commit()
        assert selectable_professors() == []
        with pytest.raises(ProfessorSelectionError):
            validate_professor_selection(
                shop_id=blue, destination="PROFESSOR", professor_id=profile_id,
                actor=db.session.get(User, student_id),
            )


def test_self_delivery_requires_verification_and_active_approval(client, test_app):
    blue, _ = blue_team(test_app)
    offer_professor_service(test_app, blue)
    professor_id = approved_professor(test_app, accepts=False)
    with test_app.app_context():
        account_id = db.session.get(Professor, professor_id).account.id
    document_id = file(test_app, account_id)
    sign_in(client, account_id)
    assert b"Deliver to Faculty" in client.get("/orders/new", query_string={"shop_id": blue}).data
    assert professor_review(client, document_id, blue, None).status_code == 200
    for status in (ProfessorVerificationStatus.PENDING, ProfessorVerificationStatus.REJECTED):
        with test_app.app_context():
            db.session.get(User, account_id).professor_verification_status = status
            db.session.commit()
            assert not professor_can_self_deliver(db.session.get(User, account_id))
        db.session.expire_all()
        page = client.get("/orders/new", query_string={"shop_id": blue}).data
        assert b'hidden' in page.split(b'data-method-choice="PROFESSOR"', 1)[1].split(b">", 1)[0]
        assert professor_review(client, document_id, blue, None).status_code == 400
    with test_app.app_context():
        db.session.get(User, account_id).professor_verification_status = ProfessorVerificationStatus.VERIFIED
        db.session.get(Professor, professor_id).is_active = False
        db.session.commit()
    assert professor_review(client, document_id, blue, None).status_code == 400
