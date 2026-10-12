from datetime import datetime
from enum import Enum

from membership_management.api.schemas.base import CamelModel


class ApplicationStatus(str, Enum):
    pending = "Pending"
    ready_to_review = "Ready to Review"
    approved = "Approved"


class MembershipApplicationBase(CamelModel):
    application_id: int
    person_id: int
    person_full_name: str
    generated_date: datetime
    fulfilment_date: datetime | None = None
    is_fulfilled: bool


class MembershipApplicationDetailSchema(MembershipApplicationBase):
    first_name: str
    last_name: str
    life_before: str
    conversion: str
    life_after: str


class BaseApplicationManagement(CamelModel):
    application_id: int
    user_id: int


class ApplicationApproval(BaseApplicationManagement):
    approval_comments: str = ""


class ApplicationRejection(BaseApplicationManagement):
    rejected_reason: str = ""
