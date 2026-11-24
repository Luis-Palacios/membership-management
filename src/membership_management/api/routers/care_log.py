from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from membership_management.api.care_access import CareContext, CareContextDep
from membership_management.api.care_log import entry_schemas, meeting_mode_from_api, source_visible
from membership_management.api.church_time import church_today
from membership_management.api.coded_errors import CodedHTTPError
from membership_management.api.current_member import CurrentMemberDep
from membership_management.api.dependencies import MembersSessionDep
from membership_management.api.jwt_auth import get_current_claims, require_permission
from membership_management.api.rate_limit import default_user_rate_limit
from membership_management.api.schemas.care_log import (
    CareLogCancelSchema,
    CareLogCompleteSchema,
    CareLogCreateSchema,
    CareLogEntrySchema,
    CareLogSourceInputSchema,
    CareLogUpdateSchema,
    CarePersonRefSchema,
    CarePersonSearchRowSchema,
)
from membership_management.api.schemas.person import PersonSchema
from membership_management.api.schemas.small_group_reports import TagSearchGroupSchema
from membership_management.data.care.models import CareLogEntry, CareLogSourceKind
from membership_management.data.care.results import CareLogFields, SourceInput
from membership_management.data.care.services import (
    CareLogChanges,
    CareLogInvalidError,
    NotPlannedError,
    PersonNotFoundError,
    SourceNotFoundError,
    cancel_entry,
    complete_entry,
    create_entry,
    delete_entry,
    entry_visible,
    get_entry,
    is_participant,
    resolve_source,
    search_people,
    update_entry,
)
from membership_management.data.members.models import Member
from membership_management.data.small_groups.results import PersonKey

# Everyone with a `careLog` permission gets in; the permission of each route and `care_log_visible_condition`
# (rule 8) decide what they see. Outside what they see, every route answers 404.
router = APIRouter(
    prefix="/care-log",
    tags=["care-log"],
    dependencies=[Depends(get_current_claims), Depends(default_user_rate_limit)],
)

_can_create = Depends(require_permission("careLog", "create"))
_can_view = Depends(require_permission("careLog", "view"))

_NOT_FOUND = "Care log entry not found."


def _linked_member(member: Member | None) -> Member:
    """Rule 7: logging needs a linked member (reading doesn't)."""
    if member is None:
        raise CodedHTTPError(409, "Link your account to a member to log care.", "link")
    return member


def _http_error(exc: Exception) -> HTTPException:
    """Map a care log domain error to its HTTP error."""
    if isinstance(exc, CareLogInvalidError):
        return CodedHTTPError(422, exc.message, exc.code)
    if isinstance(exc, PersonNotFoundError):
        return HTTPException(status_code=404, detail="Person not found.")
    if isinstance(exc, SourceNotFoundError):
        return HTTPException(status_code=404, detail="Source not found.")
    if isinstance(exc, NotPlannedError):
        return CodedHTTPError(409, "Only a planned entry can be completed or cancelled.", "not_planned")
    raise exc


def _people(refs: list[CarePersonRefSchema]) -> list[PersonKey]:
    people: list[PersonKey] = []
    for ref in refs:
        if (ref.member_id is None) == (ref.guest_id is None):
            raise CareLogInvalidError("people", "Each person is a member or a guest, not both.")
        people.append(
            ("member", ref.member_id) if ref.member_id is not None else ("guest", ref.guest_id or 0)
        )
    return people


def _source_input(source: CareLogSourceInputSchema) -> SourceInput:
    if source.kind == CareLogSourceKind.ATTENDANCE:
        if source.report_id is None or (source.member_id is None) == (source.guest_id is None):
            raise CareLogInvalidError("source", "An attendance source needs a report and one person.")
        person: PersonKey = (
            ("member", source.member_id) if source.member_id is not None else ("guest", source.guest_id or 0)
        )
        return SourceInput(CareLogSourceKind.ATTENDANCE, report_id=source.report_id, person=person)
    if source.kind == CareLogSourceKind.ITEM:
        return SourceInput(CareLogSourceKind.ITEM, item_id=source.item_id)
    return SourceInput(CareLogSourceKind.CONVERSATION, conversation_id=source.conversation_id)


def _entry_or_404(db: MembersSessionDep, entry_id: int, ctx: CareContext) -> CareLogEntry:
    """The entry when the caller sees it (rule 8): 404 for a missing, deleted or hidden one."""
    entry = get_entry(db, entry_id)
    if entry is None or not entry_visible(db, ctx.viewer, entry_id):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return entry


def _author_only(entry: CareLogEntry, ctx: CareContext) -> None:
    if entry.author_user_id != ctx.claims.sub:
        raise CodedHTTPError(403, "Only the author can do this.", "author")


def _author_or_participant(entry: CareLogEntry, ctx: CareContext) -> None:
    if entry.author_user_id != ctx.claims.sub and not is_participant(
        entry, ctx.member.id if ctx.member is not None else None
    ):
        raise CodedHTTPError(403, "Only the author or someone it was planned with can do this.", "author")


def _schema(db: MembersSessionDep, ctx: CareContext, entry: CareLogEntry) -> CareLogEntrySchema:
    return entry_schemas(db, ctx, [entry], today=church_today())[0]


@router.get(
    "/people-search",
    name="search_care_log_people",
    description="Active members and guests the caller may log care about, matching a name (at most 10)",
    dependencies=[_can_create],
)
def get_people_search(
    db: MembersSessionDep, ctx: CareContextDep, q: Annotated[str, Query(max_length=100)] = ""
) -> list[CarePersonSearchRowSchema]:
    return [
        CarePersonSearchRowSchema(
            person=PersonSchema(type=row.person[0], id=row.person[1], name=row.name),
            groups=[
                TagSearchGroupSchema(id=g.id, name=g.name, audience=g.audience, role=g.role)
                for g in row.groups
            ],
            phone_last4=row.phone_last4,
        )
        for row in search_people(db, ctx.viewer, q)
    ]


@router.post(
    "",
    name="create_care_log_entry",
    description="Log a call, messages, a meeting, a visit, something we heard or a note, done or planned",
    status_code=status.HTTP_201_CREATED,
    dependencies=[_can_create],
)
def post_entry(
    body: CareLogCreateSchema, db: MembersSessionDep, ctx: CareContextDep, member: CurrentMemberDep
) -> CareLogEntrySchema:
    author = _linked_member(member)
    try:
        source = _source_input(body.source) if body.source is not None else None
        if source is not None:
            ref = resolve_source(db, source)
            if not source_visible(ref, ctx):
                raise SourceNotFoundError
        entry = create_entry(
            db,
            ctx.viewer,
            CareLogFields(
                kind=body.kind,
                status=body.status,
                meeting_mode=meeting_mode_from_api(body.meeting_mode),
                occurred_on=body.occurred_on,
                occurred_at_time=body.occurred_at_time,
                text=body.text,
                heard_from=body.heard_from,
                others=body.others,
                visibility=body.visibility,
                people=_people(body.people),
                participants=body.participants,
            ),
            author_user_id=ctx.claims.sub,
            author_member_id=author.id,
            source=source,
            today=church_today(),
        )
    except (CareLogInvalidError, PersonNotFoundError, SourceNotFoundError) as exc:
        raise _http_error(exc) from exc
    return _schema(db, ctx, entry)


@router.get(
    "/{entry_id}",
    name="get_care_log_entry",
    description="One entry, when the caller may see it (404 otherwise)",
    dependencies=[_can_view],
)
def get_entry_route(entry_id: int, db: MembersSessionDep, ctx: CareContextDep) -> CareLogEntrySchema:
    return _schema(db, ctx, _entry_or_404(db, entry_id, ctx))


@router.patch(
    "/{entry_id}",
    name="update_care_log_entry",
    description="Edit your own entry, any time; a changed text keeps the old one out of sight",
    dependencies=[_can_create],
)
def patch_entry(
    entry_id: int, body: CareLogUpdateSchema, db: MembersSessionDep, ctx: CareContextDep
) -> CareLogEntrySchema:
    entry = _entry_or_404(db, entry_id, ctx)
    _author_only(entry, ctx)
    sent = body.model_fields_set
    changes = CareLogChanges()
    try:
        if "status" in sent and body.status != entry.status:
            raise CareLogInvalidError("status", "Complete or cancel a plan instead of changing its status.")
        if "source" in sent:
            raise CareLogInvalidError("source", "The source of an entry doesn't change.")
        if "kind" in sent:
            if body.kind is None:
                raise CareLogInvalidError("kind", "The kind can't be empty.")
            changes["kind"] = body.kind
        if "occurred_on" in sent:
            if body.occurred_on is None:
                raise CareLogInvalidError("date", "The date can't be empty.")
            changes["occurred_on"] = body.occurred_on
        if "visibility" in sent:
            if body.visibility is None:
                raise CareLogInvalidError("visibility", "The visibility can't be empty.")
            changes["visibility"] = body.visibility
        if "meeting_mode" in sent:
            changes["meeting_mode"] = meeting_mode_from_api(body.meeting_mode)
        if "occurred_at_time" in sent:
            changes["occurred_at_time"] = body.occurred_at_time
        if "text" in sent:
            changes["text"] = body.text
        if "heard_from" in sent:
            changes["heard_from"] = body.heard_from
        if "others" in sent:
            changes["others"] = body.others
        if "people" in sent:
            changes["people"] = _people(body.people or [])
        if "participants" in sent:
            changes["participants"] = body.participants or []
        entry = update_entry(db, ctx.viewer, entry, changes, today=church_today())
    except (CareLogInvalidError, PersonNotFoundError) as exc:
        raise _http_error(exc) from exc
    return _schema(db, ctx, entry)


@router.delete(
    "/{entry_id}",
    name="delete_care_log_entry",
    description="Delete your own entry (it disappears from the timelines and the lists)",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_can_create],
)
def delete_entry_route(entry_id: int, db: MembersSessionDep, ctx: CareContextDep) -> Response:
    entry = _entry_or_404(db, entry_id, ctx)
    _author_only(entry, ctx)
    delete_entry(db, entry)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{entry_id}/complete",
    name="complete_care_log_entry",
    description="Record how a planned entry went: it becomes done (the author or someone planned with)",
    dependencies=[_can_create],
)
def post_complete(
    entry_id: int, body: CareLogCompleteSchema, db: MembersSessionDep, ctx: CareContextDep
) -> CareLogEntrySchema:
    entry = _entry_or_404(db, entry_id, ctx)
    _author_or_participant(entry, ctx)
    try:
        entry = complete_entry(db, entry, text=body.text, occurred_on=body.occurred_on, today=church_today())
    except (CareLogInvalidError, NotPlannedError) as exc:
        raise _http_error(exc) from exc
    return _schema(db, ctx, entry)


@router.post(
    "/{entry_id}/cancel",
    name="cancel_care_log_entry",
    description="Cancel a planned entry; it stays visible as cancelled (the author or someone planned with)",
    dependencies=[_can_create],
)
def post_cancel(
    entry_id: int, db: MembersSessionDep, ctx: CareContextDep, body: CareLogCancelSchema | None = None
) -> CareLogEntrySchema:
    entry = _entry_or_404(db, entry_id, ctx)
    _author_or_participant(entry, ctx)
    try:
        entry = cancel_entry(db, entry, reason=body.reason if body is not None else None)
    except (CareLogInvalidError, NotPlannedError) as exc:
        raise _http_error(exc) from exc
    return _schema(db, ctx, entry)
