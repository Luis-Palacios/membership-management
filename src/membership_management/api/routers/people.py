from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from membership_management.api.dependencies import SessionDep
from membership_management.api.jwt_auth import get_current_claims, require_permission
from membership_management.api.rate_limit import default_user_rate_limit
from membership_management.api.schemas.people import PersonEventSchema, PersonFirstAssistanceSchema
from membership_management.data.assimilation.models.assistance.results import PersonFirstAssistanceResult
from membership_management.data.assimilation.models.assistance.services import get_person_first_assistance
from membership_management.data.assimilation.models.person.services import get_person_events

if TYPE_CHECKING:
    from collections.abc import Sequence

    from membership_management.data.assimilation.models.assistance.results import (
        PersonFirstAssistanceResult,
    )
    from membership_management.data.assimilation.models.person.results import PersonEventResult

# People are the assimilation DB's records behind membership applications, so they share its
# permission.
router = APIRouter(
    prefix="/people",
    tags=["people"],
    dependencies=[
        Depends(get_current_claims),
        Depends(default_user_rate_limit),
        Depends(require_permission("membershipApplications", "view")),
    ],
)


@router.get("/{person_id}/events", description="Retrieve all events associated with a given person.")
def get_events(person_id: int, db: SessionDep) -> list[PersonEventSchema]:
    person_events: Sequence[PersonEventResult] = get_person_events(session=db, person_id=person_id)
    mapped_person_events = [
        PersonEventSchema(
            event_id=event.event_id,
            person_id=event.person_id,
            event_name=event.event_name,
            event_date=event.event_date,
            event_type_name=event.event_type_name,
        )
        for event in person_events
    ]
    return mapped_person_events


@router.get(
    "/{person_id}/first-assistance",
    description="Retrieve the first assistance record associated with a given person.",
)
def get_person_first_assistance_get(person_id: int, db: SessionDep) -> PersonFirstAssistanceSchema | None:
    person_first_assistance: PersonFirstAssistanceResult | None = get_person_first_assistance(
        session=db, person_id=person_id
    )
    if person_first_assistance is None:
        return None
    return PersonFirstAssistanceSchema(
        person_id=person_first_assistance.person_id,
        assistance_date=person_first_assistance.assistance_date,
        assistance_type_id=person_first_assistance.assistance_type_id,
    )
