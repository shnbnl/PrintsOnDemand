"""One eligibility rule for professor choices and order assignment."""

from sqlalchemy import select

from app.extensions import db
from app.models import OrderDestination, PrintingShop, Professor, ProfessorVerificationStatus, ServiceType, ShopService, User, UserRole
from app.professor_faculties import ALL_FACULTIES

PROFESSOR_DELIVERY_SHOP = "Blue and Silver Bookstore"


def shop_supports_professor_delivery(shop: PrintingShop) -> bool:
    return shop.name == PROFESSOR_DELIVERY_SHOP and shop.is_active and any(
        item.service_type == ServiceType.DIRECT_TO_PROFESSOR and item.enabled
        for item in shop.services
    )


class ProfessorSelectionError(ValueError):
    pass


def professor_can_self_deliver(account: User) -> bool:
    profile = account.professor
    return bool(
        account.role == UserRole.PROFESSOR and account.is_active
        and account.professor_verification_status == ProfessorVerificationStatus.VERIFIED
        and profile is not None and profile.is_active and profile.direct_send_approved
        and profile.faculty in ALL_FACULTIES
    )


def selectable_professors() -> list[Professor]:
    return db.session.scalars(
        select(Professor).join(User, User.professor_id == Professor.id).where(
            User.role == UserRole.PROFESSOR,
            User.is_active.is_(True),
            User.professor_verification_status == ProfessorVerificationStatus.VERIFIED,
            Professor.is_active.is_(True),
            Professor.direct_send_approved.is_(True),
            Professor.accepts_student_deliveries.is_(True),
            Professor.faculty.is_not(None),
        ).order_by(Professor.name, Professor.id)
    ).all()


def selectable_professor(professor_id: int) -> Professor | None:
    return db.session.scalar(
        select(Professor).join(User, User.professor_id == Professor.id).where(
            Professor.id == professor_id,
            User.role == UserRole.PROFESSOR,
            User.is_active.is_(True),
            User.professor_verification_status == ProfessorVerificationStatus.VERIFIED,
            Professor.is_active.is_(True),
            Professor.direct_send_approved.is_(True),
            Professor.accepts_student_deliveries.is_(True),
            Professor.faculty.is_not(None),
        ).execution_options(populate_existing=True)
    )


def professor_service_available(shop_id: int) -> bool:
    return db.session.scalar(
        select(ShopService.id).join(PrintingShop, PrintingShop.id == ShopService.shop_id).where(
            ShopService.shop_id == shop_id,
            ShopService.service_type == ServiceType.DIRECT_TO_PROFESSOR,
            ShopService.enabled.is_(True),
            PrintingShop.is_active.is_(True),
            PrintingShop.name == PROFESSOR_DELIVERY_SHOP,
        )
    ) is not None


def validate_professor_selection(
    *, shop_id: int, destination: str | None, professor_id: str | int | None,
    actor: User | None = None,
) -> Professor | None:
    """Reject unsupported destinations and recheck approval and shop service."""
    if not destination and professor_id in (None, ""):
        return None  # Existing Stage 5 orders remain valid.
    if destination != OrderDestination.PROFESSOR:
        raise ProfessorSelectionError("Select a valid order destination.")
    if not professor_service_available(shop_id):
        raise ProfessorSelectionError("This shop does not offer Professor Delivery.")
    if actor is not None and actor.role == UserRole.PROFESSOR:
        if professor_id not in (None, ""):
            raise ProfessorSelectionError("Your professor delivery recipient is set by your account.")
        professor = db.session.get(Professor, actor.professor_id, populate_existing=True) if actor.professor_id else None
        if not professor_can_self_deliver(actor):
            raise ProfessorSelectionError("Your professor account needs a verified, active profile.")
        return professor
    if actor is not None and actor.role != UserRole.STUDENT:
        raise ProfessorSelectionError("This account cannot request professor delivery.")
    try:
        parsed_id = int(professor_id)
    except (TypeError, ValueError) as error:
        raise ProfessorSelectionError("Select an approved professor.") from error
    if (isinstance(professor_id, bool) or not 0 < parsed_id <= 2**63 - 1
            or str(parsed_id) != str(professor_id)):
        raise ProfessorSelectionError("Select an approved professor.")
    professor = selectable_professor(parsed_id)
    if professor is None:
        raise ProfessorSelectionError("Select an active, approved professor.")
    return professor


def professor_snapshot(professor: Professor | None, *, faculty: str | None = None) -> dict | None:
    if professor is None:
        return None
    department = (professor.account.professor_department if professor.account and professor.account.professor_department
                  else professor.department)
    return {
        "id": professor.id,
        "name": professor.name,
        "email": professor.email,
        "department": department,
        "faculty": faculty or professor.faculty,
        "office": professor.delivery_location,
    }


def assign_professor(order, professor: Professor, *, faculty: str | None = None) -> None:
    details = professor_snapshot(professor, faculty=faculty)
    order.destination = OrderDestination.PROFESSOR
    order.professor = professor
    order.professor_name = details["name"]
    order.professor_email = details["email"]
    order.professor_department = details["department"]
    order.professor_faculty = details["faculty"]
    order.professor_office = details["office"]
