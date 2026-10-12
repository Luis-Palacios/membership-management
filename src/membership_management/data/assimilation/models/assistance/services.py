from sqlalchemy.orm import Session

from membership_management.data.assimilation.models.assistance.queries import (
    get_person_first_assistance_query,
)
from membership_management.data.assimilation.models.assistance.results import PersonFirstAssistanceResult
from membership_management.data.query_helpers import first_as


def get_person_first_assistance(session: Session, person_id: int) -> PersonFirstAssistanceResult | None:
    person_assistance: PersonFirstAssistanceResult | None = first_as(
        session, get_person_first_assistance_query(person_id), cls=PersonFirstAssistanceResult
    )
    return person_assistance
