from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from membership_management.api.access import OptionalSmallGroupScopeDep, ensure_watch_audience
from membership_management.api.coded_errors import CodedHTTPError
from membership_management.api.config import api_settings
from membership_management.api.current_member import CurrentMemberDep
from membership_management.api.dependencies import MembersSessionDep
from membership_management.api.jwt_auth import CurrentClaimsDep, get_current_claims, require_permission
from membership_management.api.rate_limit import default_user_rate_limit, rate_limit
from membership_management.api.routers.members import member_detail
from membership_management.api.schemas.me import MeFeaturesSchema, MeLeadSchema, MeMemberSchema, MeSchema
from membership_management.api.schemas.members import MemberDetailSchema, MyMemberUpdateSchema
from membership_management.api.schemas.notifications import (
    EmailSwitchesSchema,
    NotificationOpenedSchema,
    NotificationPreferencesSchema,
    NotificationPreferencesUpdateSchema,
    NotificationSchema,
    NotificationsMarkedSchema,
    NotificationsPageSchema,
    PushSwitchesSchema,
    UnreadCountSchema,
    WatchedGroupSchema,
    WatchedGroupsSchema,
)
from membership_management.data.members.services import get_member_leads, update_member
from membership_management.data.small_groups.conversation_notifications import (
    CATEGORY as CONVERSATION_CATEGORY,
)
from membership_management.data.small_groups.report_reminder_notifications import (
    CATEGORY as REMINDER_CATEGORY,
)
from membership_management.data.small_groups.report_submitted_notifications import (
    CATEGORY as SUBMITTED_CATEGORY,
)
from membership_management.data.small_groups.watch_services import watched_groups
from membership_management.notifications.config import notification_settings
from membership_management.notifications.entries import (
    list_entries,
    mark_all_entries_read,
    mark_entry_read,
    unread_count,
)
from membership_management.notifications.preferences import is_enabled, set_enabled

router = APIRouter(
    prefix="/me",
    tags=["me"],
    dependencies=[Depends(get_current_claims), Depends(default_user_rate_limit)],
)


@router.get("", name="get_me", description="Signed-in user, their member (if linked) and groups led")
def get_me(claims: CurrentClaimsDep, member: CurrentMemberDep, db: MembersSessionDep) -> MeSchema:
    features = MeFeaturesSchema(guest_groups=api_settings.guest_groups_enabled)
    if member is None:
        return MeSchema(user_id=claims.sub, role=claims.role, member=None, leads=[], features=features)
    return MeSchema(
        user_id=claims.sub,
        role=claims.role,
        member=MeMemberSchema(id=member.id, name=member.name),
        leads=[
            MeLeadSchema(small_group_id=lead.small_group_id, name=lead.small_group_name, role=lead.role)
            for lead in get_member_leads(db, member.id)
        ],
        features=features,
    )


@router.patch(
    "/member",
    name="update_my_member",
    description="Update the given fields of the caller's own member (name, phone, address, birthDate, sex)",
    dependencies=[
        Depends(require_permission("ownProfile", "update")),
        Depends(rate_limit("30/minute", scope="update_my_member")),
    ],
)
def patch_my_member(
    body: MyMemberUpdateSchema, member: CurrentMemberDep, db: MembersSessionDep, claims: CurrentClaimsDep
) -> MemberDetailSchema:
    # Only the member linked to the JWT `sub`, never an id from the request, so no members scope (rule 2).
    if member is None:
        raise HTTPException(status_code=404, detail="Your account isn't linked to a member.")
    # No email field, so no duplicate-email case to handle.
    return member_detail(db, update_member(db, member, body.model_dump(exclude_unset=True)), claims)


# The schema's keys → the notifications/ categories (one switch per kind, for each channel).
_KIND_CATEGORIES = {
    "report_conversation": CONVERSATION_CATEGORY,
    "report_submitted": SUBMITTED_CATEGORY,
    "report_reminder": REMINDER_CATEGORY,
}


def _preferences(db: MembersSessionDep, user_id: str) -> NotificationPreferencesSchema:
    s = notification_settings
    return NotificationPreferencesSchema(
        email=EmailSwitchesSchema(
            **{key: is_enabled(db, user_id, category, "email") for key, category in _KIND_CATEGORIES.items()}
        ),
        available=EmailSwitchesSchema(
            report_conversation=s.conversation_emails_enabled,
            report_submitted=s.report_submitted_emails_enabled,
            report_reminder=s.report_reminder_emails_enabled,
        ),
        push=PushSwitchesSchema(
            **{key: is_enabled(db, user_id, category, "push") for key, category in _KIND_CATEGORIES.items()}
        ),
        # Rule 3: a kind sends push only while its own flag and the push flag are both on.
        available_push=PushSwitchesSchema(
            report_conversation=s.push_enabled_for(s.conversation_emails_enabled),
            report_submitted=s.push_enabled_for(s.report_submitted_emails_enabled),
            report_reminder=s.push_enabled_for(s.report_reminder_emails_enabled),
        ),
    )


@router.get(
    "/notification-preferences",
    name="get_my_notification_preferences",
    description="The caller's email and push switch per kind, and which kinds the server sends at all "
    "(available, availablePush)",
)
def get_my_notification_preferences(
    claims: CurrentClaimsDep, db: MembersSessionDep
) -> NotificationPreferencesSchema:
    return _preferences(db, claims.sub)


@router.put(
    "/notification-preferences",
    name="set_my_notification_preferences",
    description="Turn any of the caller's email or push switches on or off (also stops ones already queued); "
    "keys left out keep their value",
    dependencies=[Depends(rate_limit("20/minute", scope="set_my_notification_preferences"))],
)
def put_my_notification_preferences(
    body: NotificationPreferencesUpdateSchema, claims: CurrentClaimsDep, db: MembersSessionDep
) -> NotificationPreferencesSchema:
    # Any signed-in user, for every kind: it only concerns their own inbox (staff-app shows Submitted
    # reports only to the watch audience, Weekly report reminders only to leaders). Works while a kill
    # switch is off too (staff-app hides the switch then), so a choice made earlier is kept.
    # One transaction for every key sent: every switch changes, or none does.
    for channel, switches in (("email", body.email), ("push", body.push)):
        if switches is None:
            continue
        for key, enabled in switches.model_dump(exclude_unset=True).items():
            set_enabled(db, claims.sub, _KIND_CATEGORIES[key], channel, enabled=enabled)
    db.commit()
    return _preferences(db, claims.sub)


def _ensure_in_app_enabled() -> None:
    """The list's routes (all but the count) answer 404 while the in-app flag is off."""
    if not notification_settings.in_app_notifications_enabled:
        raise CodedHTTPError(404, "In-app notifications are turned off.", "notifications_disabled")


# "unread-count" and "read-all" are declared before "{notification_id}/read" (different methods and a
# typed id, so they can't clash, but the order keeps that obvious).
@router.get(
    "/notifications",
    name="list_my_notifications",
    description="The caller's in-app notifications, newest first; page with `before` (an id) and the "
    "returned `nextBefore`. 404 notifications_disabled while the flag is off",
    dependencies=[Depends(_ensure_in_app_enabled)],
)
def get_my_notifications(
    claims: CurrentClaimsDep,
    db: MembersSessionDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    before: Annotated[int | None, Query(ge=1)] = None,
) -> NotificationsPageSchema:
    page = list_entries(db, claims.sub, limit=limit, before=before)
    return NotificationsPageSchema(
        items=[NotificationSchema.model_validate(entry, from_attributes=True) for entry in page.items],
        next_before=page.next_before,
    )


@router.get(
    "/notifications/unread-count",
    name="get_my_unread_notification_count",
    description="The bell's number: how many kept notifications are unread. {enabled: false, unread: 0} "
    "while the flag is off (never a 404)",
)
def get_my_unread_notification_count(claims: CurrentClaimsDep, db: MembersSessionDep) -> UnreadCountSchema:
    if not notification_settings.in_app_notifications_enabled:
        return UnreadCountSchema(enabled=False, unread=0)
    return UnreadCountSchema(enabled=True, unread=unread_count(db, claims.sub))


@router.post(
    "/notifications/read-all",
    name="mark_all_my_notifications_read",
    description="Mark every unread notification of the caller read; returns how many. 404 "
    "notifications_disabled while the flag is off",
    dependencies=[
        Depends(_ensure_in_app_enabled),
        Depends(rate_limit("30/minute", scope="mark_all_my_notifications_read")),
    ],
)
def post_my_notifications_read_all(
    claims: CurrentClaimsDep, db: MembersSessionDep
) -> NotificationsMarkedSchema:
    return NotificationsMarkedSchema(marked=mark_all_entries_read(db, claims.sub))


@router.post(
    "/notifications/{notification_id}/read",
    name="mark_my_notification_read",
    description="Mark one notification read (idempotent) and return where it opens. 404 when it isn't the "
    "caller's or is gone, and notifications_disabled while the flag is off",
    dependencies=[
        Depends(_ensure_in_app_enabled),
        Depends(rate_limit("120/minute", scope="mark_my_notification_read")),
    ],
)
def post_my_notification_read(
    notification_id: Annotated[int, Path(ge=1)], claims: CurrentClaimsDep, db: MembersSessionDep
) -> NotificationOpenedSchema:
    path = mark_entry_read(db, claims.sub, notification_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Notification not found.")
    return NotificationOpenedSchema(path=path)


@router.get(
    "/watched-groups",
    name="get_my_watched_groups",
    description="Every small group with whether the caller watches it (full-scope observation audience only)",
)
def get_my_watched_groups(
    claims: CurrentClaimsDep, scope: OptionalSmallGroupScopeDep, db: MembersSessionDep
) -> WatchedGroupsSchema:
    ensure_watch_audience(claims, scope)
    return WatchedGroupsSchema(
        items=[
            WatchedGroupSchema(
                small_group_id=g.small_group_id, name=g.name, closed=g.closed, watching=g.watching
            )
            for g in watched_groups(db, claims.sub)
        ]
    )
