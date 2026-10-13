from sqlalchemy import select
from sqlalchemy.sql import Select

from membership_management.data.assimilation.models.assistance.assistance import Assistance


def get_person_first_assistance_query(person_id: int) -> Select:
    """Returns the first assistance date for the given person."""
    return (
        select(Assistance.assistance_date, Assistance.assistance_type_id, Assistance.person_id)
        .where(Assistance.person_id == person_id, Assistance.assistance_type_id == 1)
        .order_by(Assistance.assistance_date.asc())
        .limit(1)
    )
