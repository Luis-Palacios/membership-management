from datetime import date

from pydantic import EmailStr

from membership_management.api.schemas.base import CamelModel
from membership_management.api.schemas.members import Address, Name, Phone
from membership_management.data.members.models import MemberSex


class NewGuestSchema(CamelModel):
    """The fields for a new guest; everything but the name is optional (rule 3)."""

    name: Name
    phone: Phone | None = None
    email: EmailStr | None = None
    sex: MemberSex | None = None
    address: Address | None = None
    # Defaults to the day they join a group, or today.
    first_visit_date: date | None = None
    invited_by_member_id: int | None = None
