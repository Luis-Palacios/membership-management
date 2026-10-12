from datetime import datetime
from typing import NamedTuple


class PersonFirstAssistanceResult(NamedTuple):
    person_id: int
    assistance_date: datetime
    assistance_type_id: int

 