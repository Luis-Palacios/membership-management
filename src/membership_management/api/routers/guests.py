import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from membership_management.api.access import (
    GuestScope,
    GuestScopeDep,
    OptionalSmallGroupScopeDep,
    ensure_guest_groups_enabled,
    sees_all_observations,
)
from membership_management.api.church_time import church_today
from membership_management.api.current_member import CurrentMemberDep
from membership_management.api.dependencies import MembersSessionDep
from membership_management.api.jwt_auth import (
    CurrentClaimsDep,
    get_current_claims,
    has_permission,
    require_permission,
)
from membership_management.api.rate_limit import default_user_rate_limit, rate_limit
from membership_management.api.routers.small_groups import GUEST_JOIN_ERRORS, guest_join_http_error
from membership_management.api.schemas.guests import (
    GuestAttendanceSchema,
    GuestCreateSchema,
    GuestCurrentGroupSchema,
    GuestDetailSchema,
    GuestLastGroupSchema,
    GuestListCountsSchema,
    GuestListItemSchema,
    GuestListSchema,
    GuestPeriodSchema,
    GuestRefSchema,
    GuestSearchItemSchema,
    GuestSearchLastGroupSchema,
    GuestUpdateSchema,
)
from membership_management.data.guests.lookup_services import (
    GuestStatus,
    get_guest,
    get_guest_detail,
    list_guests,
    search_guests,
)
from membership_management.data.guests.models import Guest
from membership_management.data.guests.results import GuestRow
from membership_management.data.guests.services import (
    InvitedByNotFoundError,
    NewGuest,
    create_guest,
    update_guest,
)
from membership_management.data.small_groups.services import add_guest_to_group, get_small_group

router = APIRouter(
    prefix="/guests",
    tags=["guests"],
    dependencies=[Depends(get_current_claims), Depends(default_user_rate_limit)],
)

# Only the digits of a phone number count for "the last 4 digits".
_NON_DIGITS = re.compile(r"\D")


def _current_group(row: GuestRow) -> GuestCurrentGroupSchema | None:
    if row.current_group_id is None or row.current_group_name is None or row.current_joined_at is None:
        return None
    return GuestCurrentGroupSchema(
        id=row.current_group_id, name=row.current_group_name, joined_at=row.current_joined_at
    )


def _last_group(row: GuestRow) -> GuestLastGroupSchema | None:
    """The group they left last, only for a guest in no group now."""
    if row.current_group_id is not None:
        return None
    if row.last_group_id is None or row.last_group_name is None or row.last_left_at is None:
        return None
    return GuestLastGroupSchema(
        id=row.last_group_id,
        name=row.last_group_name,
        left_at=row.last_left_at,
        left_reason=row.last_left_reason,
    )


def _get_or_404(db: MembersSessionDep, guest_id: int, scope: GuestScope | None = None) -> Guest:
    """404 when the guest doesn't exist or is outside the scope, with the same message for both."""
    guest = get_guest(db, guest_id) if scope is None or scope.includes(db, guest_id) else None
    if guest is None:
        raise HTTPException(status_code=404, detail=f"Guest with ID {guest_id} not found.")
    return guest


def _detail(
    db: MembersSessionDep, guest: Guest, claims: CurrentClaimsDep, scope: GuestScope
) -> GuestDetailSchema:
    detail = get_guest_detail(
        db,
        guest,
        only_group_ids=None if scope.full else scope.group_ids,
        sees_all_observations=sees_all_observations(claims),
        led_group_ids=scope.group_ids,
    )
    return GuestDetailSchema(
        id=guest.id,
        name=guest.name,
        phone=detail.phone,
        email=detail.email,
        sex=guest.sex,
        address=detail.address,
        first_visit_date=guest.first_visit_date,
        invited_by=GuestRefSchema(id=detail.invited_by[0], name=detail.invited_by[1])
        if detail.invited_by
        else None,
        created_by=GuestRefSchema(id=detail.created_by[0], name=detail.created_by[1])
        if detail.created_by
        else None,
        created_at=detail.created_at,
        current_group=_current_group(detail.row),
        last_attended_date=detail.row.last_attended_date,
        group_history=[
            GuestPeriodSchema(
                small_group_id=p.small_group_id,
                small_group_name=p.small_group_name,
                role=p.role,
                joined_at=p.joined_at,
                left_at=p.left_at,
                left_reason=p.left_reason,
            )
            for p in detail.periods
        ],
        recent_attendance=[
            GuestAttendanceSchema(
                report_id=a.report_id,
                meeting_date=a.meeting_date,
                small_group=GuestRefSchema(id=a.small_group_id, name=a.small_group_name),
                attended_group=a.attended_group,
                attended_church=a.attended_church,
                observation=a.observation if a.report_id in detail.observations_visible_in else None,
            )
            for a in detail.attendance
        ],
    )


@router.get(
    "",
    name="list_guests",
    description="List guests (all of them): in a guest group or not, with search, paged, with tab counts",
    dependencies=[Depends(require_permission("guests", "view", "all"))],
)
def get_guests(
    db: MembersSessionDep,
    status_filter: Annotated[GuestStatus, Query(alias="status")] = "all",
    q: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 25,
) -> GuestListSchema:
    text = q.strip() if q is not None else None
    result = list_guests(
        db, status=status_filter, q=text or None, page=page, page_size=page_size, today=church_today()
    )
    return GuestListSchema(
        items=[
            GuestListItemSchema(
                id=row.id,
                name=row.name,
                phone=row.phone,
                first_visit_date=row.first_visit_date,
                current_group=_current_group(row),
                last_group=_last_group(row),
                last_attended_date=row.last_attended_date,
                missed_streak=result.missed_streaks.get(row.id),
            )
            for row in result.rows
        ],
        counts=GuestListCountsSchema(
            all=result.counts.all, active=result.counts.active, inactive=result.counts.inactive
        ),
        total=result.total,
        page=page,
        page_size=page_size,
    )


# Declared before `/{guest_id}` so "search" is never read as a guest id.
@router.get(
    "/search",
    name="search_guests",
    description="Find guests church-wide by name or phone, with just enough to recognise them (top 10)",
    dependencies=[Depends(require_permission("guests", "search"))],
)
def get_guest_search(
    db: MembersSessionDep, scope: GuestScopeDep, q: Annotated[str, Query(max_length=100)]
) -> list[GuestSearchItemSchema]:
    text = q.strip()
    # Search is church-wide, so it is only for who has `all` or leads an open guest group (rule 17);
    # anyone else gets nothing, not a 403.
    if len(text) < 2 or not scope.can_search:
        return []
    items: list[GuestSearchItemSchema] = []
    for row in search_guests(db, text):
        digits = _NON_DIGITS.sub("", row.phone or "")
        last = _last_group(row)
        items.append(
            GuestSearchItemSchema(
                id=row.id,
                name=row.name,
                phone_last4=digits[-4:] or None,
                current_group=_current_group(row),
                last_group=GuestSearchLastGroupSchema(id=last.id, name=last.name, left_at=last.left_at)
                if last is not None
                else None,
                last_attended_date=row.last_attended_date,
            )
        )
    return items


@router.get(
    "/{guest_id}",
    name="get_guest",
    description="A guest's details, group history and recent attendance (within your guests scope)",
    dependencies=[Depends(require_permission("guests", "view"))],
)
def get_guest_detail_route(
    guest_id: int, db: MembersSessionDep, claims: CurrentClaimsDep, scope: GuestScopeDep
) -> GuestDetailSchema:
    return _detail(db, _get_or_404(db, guest_id, scope), claims, scope)


@router.post(
    "",
    name="create_guest",
    description="Create a guest, in no group or straight into a guest group (they join today)",
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(require_permission("guests", "create")),
        Depends(rate_limit("20/minute", scope="create_guest")),
    ],
)
def post_guest(
    body: GuestCreateSchema,
    db: MembersSessionDep,
    claims: CurrentClaimsDep,
    member: CurrentMemberDep,
    scope: GuestScopeDep,
    group_scope: OptionalSmallGroupScopeDep,
) -> GuestDetailSchema:
    ensure_guest_groups_enabled()
    new_guest = NewGuest(**body.model_dump(exclude={"small_group_id"}))
    created_by = member.id if member is not None else None
    today = church_today()
    try:
        if body.small_group_id is None:
            # A guest in no group isn't in anyone's scope, so it takes `all`.
            if not has_permission(claims, "guests", "all"):
                raise HTTPException(status_code=403, detail="You don't have permission to do this.")
            guest = create_guest(db, new_guest, created_by_member_id=created_by, today=today)
        else:
            if not has_permission(claims, "smallGroups", "manageMembers") or group_scope is None:
                raise HTTPException(status_code=403, detail="You don't have permission to do this.")
            group_id = body.small_group_id
            small_group = get_small_group(db, group_id) if group_scope.includes(group_id) else None
            if small_group is None:
                raise HTTPException(status_code=404, detail=f"Small group with ID {group_id} not found.")
            guest_id = add_guest_to_group(
                db,
                small_group,
                guest_id=None,
                new_guest=new_guest,
                joined_at=None,
                move_from_other_group=False,
                created_by_member_id=created_by,
                today=today,
            )
            guest = _get_or_404(db, guest_id)
    except InvitedByNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Inviting member not found.") from exc
    except GUEST_JOIN_ERRORS as exc:
        raise guest_join_http_error(exc) from exc
    return _detail(db, guest, claims, scope)


@router.patch(
    "/{guest_id}",
    name="update_guest",
    description="Update the given fields of a guest (contact, first visit, invited by), within your scope",
    dependencies=[
        Depends(require_permission("guests", "update")),
        Depends(rate_limit("30/minute", scope="update_guest")),
    ],
)
def patch_guest(
    guest_id: int,
    body: GuestUpdateSchema,
    db: MembersSessionDep,
    claims: CurrentClaimsDep,
    scope: GuestScopeDep,
) -> GuestDetailSchema:
    guest = _get_or_404(db, guest_id, scope)
    changes = body.model_dump(exclude_unset=True)
    # name is NOT NULL: an explicit null would otherwise surface as a DB error (500).
    if "name" in changes and changes["name"] is None:
        raise HTTPException(status_code=422, detail="name cannot be null.")
    try:
        guest = update_guest(db, guest, changes)
    except InvitedByNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Inviting member not found.") from exc
    return _detail(db, guest, claims, scope)
