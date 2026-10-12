from datetime import datetime

from membership_management.api.schemas.base import CamelModel


class PersonEventSchema(CamelModel):
    event_id: int
    person_id: int
    event_name: str
    event_date: datetime
    event_type_name: str
    
class PersonFirstAssistanceSchema(CamelModel):
    person_id: int
    assistance_date: datetime
    assistance_type_id: int