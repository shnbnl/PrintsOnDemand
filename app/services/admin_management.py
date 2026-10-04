"""Validated admin mutations that preserve role and order boundaries."""

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Faculty, PaymentSettings, PrintingShop, Professor, ProfessorVerificationStatus, User, UserRole
from app.services.professors import PROFESSOR_DELIVERY_SHOP


class ManagementError(ValueError):
    pass


def save_professor(record: Professor | None, *, name: str, email: str,
                   department: str | None, office: str | None,
                   is_active: bool, direct_send_approved: bool,
                   accepts_student_deliveries: bool = False,
                   faculty: str | None = None, account_id: int | None = None) -> Professor:
    try:
        normalized = validate_email(email, check_deliverability=False).normalized.casefold()
    except (EmailNotValidError, TypeError, ValueError) as error:
        raise ManagementError("Enter a valid professor email.") from error
    existing = db.session.scalar(select(Professor).where(Professor.email == normalized))
    if existing is not None and (record is None or existing.id != record.id):
        raise ManagementError("A professor with this email already exists.")
    try:
        parsed_faculty = Faculty(faculty) if faculty else None
    except ValueError as error:
        raise ManagementError("Select a valid Faculty.") from error
    account = db.session.get(User, account_id) if account_id else None
    if account_id and (account is None or account.role != UserRole.PROFESSOR
                       or account.professor_verification_status != ProfessorVerificationStatus.VERIFIED
                       or (account.email != normalized
                           and (record is None or account.professor_id != record.id))
                       or (record is None and account.name.casefold() != name.strip().casefold())
                       or (account.professor_id is not None
                           and (record is None or account.professor_id != record.id))):
        raise ManagementError("Select an unlinked professor account with the same email.")
    if account is not None and db.session.scalar(select(User.id).where(
        User.email == normalized, User.id != account.id,
    )) is not None:
        raise ManagementError("Another account already uses this email.")
    previous_department = record.department if record is not None else None
    editing_linked_department = record is not None and previous_department != (department or None)
    record = record or Professor()
    try:
        record.name = name
        record.email = normalized
    except ValueError as error:
        raise ManagementError(str(error)) from error
    record.department = department or None
    record.faculty = parsed_faculty.value if parsed_faculty else None
    record.office = office or None
    record.is_active = is_active
    record.direct_send_approved = direct_send_approved
    record.accepts_student_deliveries = accepts_student_deliveries
    record.account = account
    if account is not None:
        account.name = record.name
        account.email = normalized
        if editing_linked_department:
            account.professor_department = record.department
    db.session.add(record)
    try:
        db.session.commit()
    except IntegrityError as error:
        db.session.rollback()
        raise ManagementError("A professor with this email already exists.") from error
    return record


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


def save_payment_settings(*, online_enabled: bool, online_instructions: str,
                          online_account_name: str, online_destination: str,
                          onsite_instructions: str) -> PaymentSettings:
    record = db.session.get(PaymentSettings, 1)
    if record is None:
        record = PaymentSettings(id=1)
        db.session.add(record)
    record.online_enabled = online_enabled
    record.online_instructions = online_instructions
    record.online_account_name = online_account_name
    record.online_destination = online_destination
    record.onsite_instructions = onsite_instructions
    db.session.commit()
    return record
