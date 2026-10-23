from membership_management.api.schemas.base import CamelModel
from membership_management.data.small_groups.models import SmallGroupRole


class MeMemberSchema(CamelModel):
    id: int
    name: str


class MeLeadSchema(CamelModel):
    small_group_id: int
    name: str
    role: SmallGroupRole


class MeFeaturesSchema(CamelModel):
    guest_groups: bool


class MeSchema(CamelModel):
    user_id: str
    role: str
    member: MeMemberSchema | None
    leads: list[MeLeadSchema]
    features: MeFeaturesSchema
