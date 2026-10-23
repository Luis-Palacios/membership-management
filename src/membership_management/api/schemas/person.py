from typing import Literal

from membership_management.api.schemas.base import CamelModel


class PersonSchema(CamelModel):
    """Who a participant, attendance row or conversation is about: a member or a guest."""

    type: Literal["member", "guest"]
    id: int
    name: str
