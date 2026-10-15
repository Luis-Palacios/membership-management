import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from membership_management.api.config import api_settings
from membership_management.api.dependencies import MembersSessionDep
from membership_management.api.schemas.internal import AcceptedInviteResultSchema, AcceptedInviteSchema
from membership_management.data.members.services import link_member_by_accepted_invite


def require_internal_token(x_internal_token: Annotated[str | None, Header()] = None) -> None:
    """Service-to-service auth: the shared INTERNAL_API_TOKEN, not a user JWT."""
    expected = api_settings.internal_api_token.get_secret_value() if api_settings.internal_api_token else ""
    if not expected:
        # Disabled (local only; config requires the token elsewhere).
        raise HTTPException(status_code=404, detail="Not Found")
    if x_internal_token is None or not secrets.compare_digest(x_internal_token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid internal token")


# Outside the JWT-protected routers and hidden from OpenAPI. Per-IP rate limiting is the edge's job;
# the shared secret is the control here.
router = APIRouter(
    prefix="/internal",
    include_in_schema=False,
    dependencies=[Depends(require_internal_token)],
)


@router.post("/member-links/accepted-invite", name="accepted_invite")
def post_accepted_invite(body: AcceptedInviteSchema, db: MembersSessionDep) -> AcceptedInviteResultSchema:
    member_id = link_member_by_accepted_invite(db, body.user_id, body.email)
    return AcceptedInviteResultSchema(linked=member_id is not None, member_id=member_id)
