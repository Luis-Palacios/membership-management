from datetime import datetime
from typing import NamedTuple


class PersonEventResult(NamedTuple):
    event_id: int
    person_id: int
    event_name: str
    event_date: datetime
    event_type_name: str