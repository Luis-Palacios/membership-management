from datetime import datetime

from sqlalchemy import Select, func, select

from ..person.person import Person
from .membership_application import MembershipApplication


def get_recently_generated_membership_applications_query(
    start_date: datetime, end_date: datetime
) -> Select[tuple[int, int, datetime, datetime | None, str, str]]:
    """
    Get all membership applications generated between the specified start and end dates.
    """
    return (
        select(
            MembershipApplication.id,
            MembershipApplication.person_id,
            MembershipApplication.generated_date,
            MembershipApplication.fulfilment_date,
            Person.first_name,
            Person.last_name,
        )
        .join(Person.membership_applications)
        .where(MembershipApplication.generated_date.between(start_date, end_date))
        .order_by(MembershipApplication.generated_date.desc())
    )

def get_recently_generated_membership_applications_count_query(
    start_date: datetime, end_date: datetime
) -> Select[tuple[int]]:
    """
    Get the count of membership applications generated between the specified start and end dates.
    """
    return (
        select(func.count(MembershipApplication.id))
        .where(MembershipApplication.generated_date.between(start_date, end_date))
    )
    
def get_detailed_membership_application_query(
    membership_application_id: int
) -> Select:
    """
    Get detailed information for a specific membership application by its ID.
    """
    return (
        select(
            MembershipApplication.id,
            MembershipApplication.person_id,
            MembershipApplication.generated_date,
            MembershipApplication.fulfilment_date,
            MembershipApplication.life_before,
            MembershipApplication.conversion,
            MembershipApplication.life_after,
            Person.first_name,
            Person.last_name,
        )
        .join(Person.membership_applications)
        .where(MembershipApplication.id == membership_application_id)
    )


most_recent_membership_application_query: Select[tuple[datetime, int]] = (
    select(MembershipApplication.generated_date, MembershipApplication.id)
    .order_by(MembershipApplication.generated_date.desc())
    .limit(limit=1)
)


