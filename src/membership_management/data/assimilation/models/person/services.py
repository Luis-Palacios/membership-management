from collections.abc import Sequence

from sqlalchemy.orm import Session

from membership_management.data.query_helpers import all_as

from .queries import get_person_events_query
from .results import PersonEventResult


def get_person_events(session: Session, person_id: int) -> Sequence["PersonEventResult"]:
    """Retrieve all events associated with a given person."""
    person_events: Sequence[PersonEventResult] = all_as(
        session, get_person_events_query(person_id), PersonEventResult
    )
    return person_events
