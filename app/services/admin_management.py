"""Validated admin mutations that preserve role and order boundaries."""

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.extensions import db
from app.models import Order, PrintingShop, Professor, ProfessorVerificationStatus, User, UserRole
from app.services.professors import PROFESSOR_DELIVERY_SHOP
from app.professor_faculties import faculty_for_account


class ManagementError(ValueError):
    pass


def verify_professor_with_profile(account: User) -> Professor:
    """Verify the login and create its managed profile in one transaction."""
    if account.role != UserRole.PROFESSOR or account.professor_verification_status != ProfessorVerificationStatus.PENDING:
        raise ManagementError("This professor account is not awaiting verification.")
    profile = account.professor or db.session.scalar(select(Professor).where(Professor.email == account.email))
    if profile is not None and profile.account is not None and profile.account.id != account.id:
        raise ManagementError("This email already belongs to another managed professor.")
    if profile is None:
        profile = Professor(name=account.name, email=account.email, is_active=True,
                            direct_send_approved=False, accepts_student_deliveries=False)
    profile.name = account.name
    profile.email = account.email
    profile.department = account.professor_department or profile.department
    profile.faculty = (faculty_for_account(account.professor_department, account.professor_faculty)
                       if account.professor_department else profile.faculty)
    account.professor = profile
    account.professor_verification_status = ProfessorVerificationStatus.VERIFIED
    db.session.add(profile)
    try:
        db.session.commit()
    except IntegrityError as error:
        db.session.rollback()
        raise ManagementError("The professor profile could not be created. Try again.") from error
    return profile


def save_professor_approvals(record: Professor, *, is_active: bool,
                             direct_send_approved: bool, accepts_student_deliveries: bool) -> None:
    """Staff controls eligibility; identity and faculty remain account owned."""
    account = record.account
    if account is None or account.professor_verification_status != ProfessorVerificationStatus.VERIFIED:
        raise ManagementError("Only verified professor accounts can be managed.")
    record.name = account.name
    record.email = account.email
    record.department = account.professor_department or record.department
    record.faculty = (faculty_for_account(account.professor_department, account.professor_faculty)
                      if account.professor_department else record.faculty)
    record.is_active = is_active
    record.direct_send_approved = direct_send_approved
    record.accepts_student_deliveries = accepts_student_deliveries
    db.session.commit()


def delete_managed_professor(professor_id: int) -> None:
    """Remove a directory entry while preserving historical order snapshots."""
    record = db.session.get(Professor, professor_id)
    if record is None:
        raise ManagementError("Professor profile not found.")
    try:
        db.session.execute(update(User).where(User.professor_id == professor_id).values(professor_id=None))
        db.session.execute(update(Order).where(Order.professor_id == professor_id).values(professor_id=None))
        db.session.delete(record)
        db.session.commit()
    except SQLAlchemyError as error:
        db.session.rollback()
        raise ManagementError("Professor profile could not be deleted.") from error


def assign_staff_to_shop(staff_id: int, shop_id: int | None) -> User:
    user = db.session.get(User, staff_id)
    if user is None or user.role != UserRole.SHOP_STAFF:
        raise ManagementError("Select a Shop Staff account.")
    shop = db.session.get(PrintingShop, shop_id) if shop_id is not None else None
    if shop_id is not None and shop is None:
        raise ManagementError("Select an existing printing shop.")
    if user.uses_name_login and (shop is None or shop.name != PROFESSOR_DELIVERY_SHOP):
        raise ManagementError("This name-only account must stay assigned to Blue and Silver Bookstore.")
    if shop is not None and shop.name == PROFESSOR_DELIVERY_SHOP:
        blue_staff = db.session.scalars(select(User).where(
            User.role == UserRole.SHOP_STAFF, User.shop_id == shop.id, User.id != user.id,
        )).all()
        if any(other.name.casefold() == user.name.casefold() for other in blue_staff):
            raise ManagementError("A Blue and Silver staff account already uses this name.")
    user.shop = shop
    db.session.commit()
    return user
