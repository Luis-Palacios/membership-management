from pydantic import EmailStr

from membership_management.api.schemas.base import CamelModel
from membership_management.api.schemas.members import UserId


class AcceptedInviteSchema(CamelModel):
    user_id: UserId
    email: EmailStr


class AcceptedInviteResultSchema(CamelModel):
    linked: bool
    member_id: int | None
