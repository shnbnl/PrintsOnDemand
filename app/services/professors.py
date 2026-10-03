"""One eligibility rule for professor choices and order assignment."""

from sqlalchemy import select

from app.extensions import db
from app.models import OrderDestination, PrintingShop, Professor, ServiceType, ShopService


class ProfessorSelectionError(ValueError):
    pass


def selectable_professors() -> list[Professor]:
    return db.session.scalars(
        select(Professor).where(
            Professor.is_active.is_(True),
            Professor.direct_send_approved.is_(True),
        ).order_by(Professor.name, Professor.id)
    ).all()


def selectable_professor(professor_id: int) -> Professor | None:
    return db.session.scalar(
        select(Professor).where(
            Professor.id == professor_id,
            Professor.is_active.is_(True),
            Professor.direct_send_approved.is_(True),
        ).execution_options(populate_existing=True)
    )


def professor_service_available(shop_id: int) -> bool:
    return db.session.scalar(
        select(ShopService.id).join(PrintingShop, PrintingShop.id == ShopService.shop_id).where(
            ShopService.shop_id == shop_id,
            ShopService.service_type == ServiceType.DIRECT_TO_PROFESSOR,
            ShopService.enabled.is_(True),
            PrintingShop.is_active.is_(True),
        )
    ) is not None


def validate_professor_selection(
    *, shop_id: int, destination: str | None, professor_id: str | int | None
) -> Professor | None:
    """Reject unsupported destinations and recheck approval and shop service."""
    if not destination and professor_id in (None, ""):
        return None  # Existing Stage 5 orders remain valid.
    if destination != OrderDestination.PROFESSOR:
        raise ProfessorSelectionError("Select a valid order destination.")
    try:
        parsed_id = int(professor_id)
    except (TypeError, ValueError) as error:
        raise ProfessorSelectionError("Select an approved professor.") from error
    if (isinstance(professor_id, bool) or not 0 < parsed_id <= 2**63 - 1
            or str(parsed_id) != str(professor_id)):
        raise ProfessorSelectionError("Select an approved professor.")
    if not professor_service_available(shop_id):
        raise ProfessorSelectionError("This shop does not offer Direct-to-Professor.")
    professor = selectable_professor(parsed_id)
    if professor is None:
        raise ProfessorSelectionError("Select an active, approved professor.")
    return professor


def professor_snapshot(professor: Professor | None) -> dict | None:
    if professor is None:
        return None
    return {
        "id": professor.id,
        "name": professor.name,
        "email": professor.email,
        "department": professor.department,
        "office": professor.office,
    }


def assign_professor(order, professor: Professor) -> None:
    order.destination = OrderDestination.PROFESSOR
    order.professor = professor
    order.professor_name = professor.name
    order.professor_email = professor.email
    order.professor_department = professor.department
    order.professor_office = professor.office
