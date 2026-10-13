from sqlalchemy import Select, select

from membership_management.data.assimilation.models import Event, EventType

from ..events.event_person import EventPerson


def get_person_events_query(person_id: int) -> Select:
    """
    Get all events associated with a specific person by their ID.
    """
    return (
        select(
            EventPerson.event_id.label("event_id"),
            EventPerson.person_id.label("person_id"),
            Event.name.label("event_name"),
            Event.date.label("event_date"),
            EventType.name.label("event_type_name"),
        )
        .join(EventPerson.event)
        .join(Event.event_type)
        .where(EventPerson.person_id == person_id)
    )
