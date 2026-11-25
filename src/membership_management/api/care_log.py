"""Care log entries as the API sends them: the response schema, shared by the care log routes and the
person timeline."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy.orm import Session

from membership_management.api.access import viewable_people
from membership_management.api.care_access import CareContext
from membership_management.api.jwt_auth import has_permission
from membership_management.api.schemas.care_log import (
    CareLogAuthorSchema,
    CareLogEntrySchema,
    CareLogNoteSchema,
    CareLogParticipantSchema,
    CareLogPersonSchema,
    CareLogSourceGroupSchema,
    CareLogSourceSchema,
    MeetingModeValue,
)
from membership_management.data.care.models import (
    CareLogEntry,
    CareLogEntryPerson,
    CareLogStatus,
    MeetingMode,
)
from membership_management.data.care.results import SourceRef
from membership_management.data.care.services import (
    can_add_note,
    is_participant,
    notes_for_entries,
    plan_past_due,
    source_refs,
)
from membership_management.data.small_groups.models import ReportStatus
from membership_management.data.small_groups.results import PersonKey, person_key

_MODE_TO_API: dict[MeetingMode, MeetingModeValue] = {
    MeetingMode.IN_PERSON: "inPerson",
    MeetingMode.ONLINE: "online",
}
_MODE_FROM_API: dict[str, MeetingMode] = {value: mode for mode, value in _MODE_TO_API.items()}


def meeting_mode_from_api(value: str | None) -> MeetingMode | None:
    return _MODE_FROM_API[value] if value is not None else None


def source_visible(ref: SourceRef, ctx: CareContext) -> bool:
    """Whether the caller may open what an entry was logged from (rule 12). A report that is still a draft
    is never offered. Attendance rows, follow-up and threads follow the observation audience (reports
    rule 9); prayer and praise sections only need the report's group in the caller's scope."""
    if not ref.exists or ref.group_id is None or ref.report_status != ReportStatus.SUBMITTED:
        return False
    if ref.needs_observation_audience:
        return ctx.observation_groups is None or ref.group_id in ctx.observation_groups
    return ctx.group_scope is not None and ctx.group_scope.includes(ref.group_id)


def _source_schema(ref: SourceRef, ctx: CareContext) -> CareLogSourceSchema:
    if not ref.exists:
        return CareLogSourceSchema(
            kind=ref.kind,
            report_id=None,
            meeting_date=None,
            small_group=None,
            visible=False,
            section=None,
            gone=True,
        )
    if not source_visible(ref, ctx) or ref.group_id is None or ref.group_name is None:
        return CareLogSourceSchema(
            kind=ref.kind,
            report_id=None,
            meeting_date=None,
            small_group=None,
            visible=False,
            section=None,
            gone=False,
        )
    return CareLogSourceSchema(
        kind=ref.kind,
        section=ref.section,
        report_id=ref.report_id,
        meeting_date=ref.meeting_date,
        small_group=CareLogSourceGroupSchema(id=ref.group_id, name=ref.group_name),
        visible=True,
        gone=False,
    )


def _person_name(person: CareLogEntryPerson) -> str:
    owner = person.member if person.member is not None else person.guest
    return owner.name if owner is not None else ""


def entry_schemas(
    db: Session, ctx: CareContext, entries: Sequence[CareLogEntry], *, now: datetime
) -> list[CareLogEntrySchema]:
    """The entries as the caller sees them: names, which people link (tags rule 12), the source's state
    for this caller. Everyone on the response is looked up once, not per entry."""
    people: set[PersonKey] = {person_key(p.member_id, p.guest_id) for entry in entries for p in entry.people}
    viewable = viewable_people(db, ctx.claims, people, ctx.member_scope, ctx.guest_scope)
    refs = source_refs(db, entries)
    can_write = has_permission(ctx.claims, "careLog", "create")
    notes = notes_for_entries(db, [entry.id for entry in entries])
    member_id = ctx.member.id if ctx.member is not None else None
    schemas: list[CareLogEntrySchema] = []
    for entry in entries:
        mine = entry.author_user_id == ctx.claims.sub
        ref = refs.get(entry.id)
        entry_notes = notes.get(entry.id, [])
        schemas.append(
            CareLogEntrySchema(
                id=entry.id,
                kind=entry.kind,
                status=entry.status,
                meeting_mode=_MODE_TO_API[entry.meeting_mode] if entry.meeting_mode is not None else None,
                occurred_on=entry.occurred_on,
                occurred_at_time=entry.occurred_at_time,
                people=[
                    CareLogPersonSchema(
                        member_id=p.member_id,
                        guest_id=p.guest_id,
                        name=_person_name(p),
                        viewable=person_key(p.member_id, p.guest_id) in viewable,
                    )
                    for p in entry.people
                ],
                others=entry.others,
                participants=[
                    CareLogParticipantSchema(member_id=p.member_id, name=p.member.name)
                    for p in entry.participants
                ],
                heard_from=entry.heard_from,
                text=entry.text,
                visibility=entry.visibility,
                cancel_reason=entry.cancel_reason,
                author=CareLogAuthorSchema(member_id=entry.author_member_id, name=entry.author.name),
                source=_source_schema(ref, ctx) if ref is not None else None,
                past_due=entry.status == CareLogStatus.PLANNED
                and plan_past_due(entry.occurred_on, entry.occurred_at_time, now),
                can_edit=can_write and mine,
                can_complete=can_write
                and entry.status == CareLogStatus.PLANNED
                and (mine or is_participant(entry, member_id)),
                notes=[
                    CareLogNoteSchema(
                        id=note.id,
                        author=CareLogAuthorSchema(member_id=note.author_member_id, name=note.author.name),
                        text=note.text,
                        created_at=note.created_at,
                        edited_at=note.edited_at,
                        can_edit=can_write and note.author_user_id == ctx.claims.sub,
                    )
                    for note in entry_notes
                ],
                can_add_note=can_add_note(
                    entry, entry_notes, user_id=ctx.claims.sub, member_id=member_id, can_write=can_write
                ),
                edited_at=entry.edited_at,
                created_at=entry.created_at,
            )
        )
    return schemas
