from collections.abc import Collection, Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime, time
from typing import TypedDict

from sqlalchemy import Row, Select, func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from membership_management.data.care.access_rules import (
    CareLogViewer,
    participant_needs_scope,
    participant_sees,
)
from membership_management.data.care.models import (
    PLANNABLE_KINDS,
    CareLogEntry,
    CareLogEntryParticipant,
    CareLogEntryPerson,
    CareLogEntryRevision,
    CareLogKind,
    CareLogSourceKind,
    CareLogStatus,
    CareLogVisibility,
    MeetingMode,
)
from membership_management.data.care.queries import (
    care_log_entry_visible_query,
    care_people_search_query,
    coming_up_query,
    existing_members_query,
    loggable_guests_query,
    loggable_members_query,
    source_conversations_query,
    source_reports_query,
)
from membership_management.data.care.results import (
    CareLogFields,
    CarePerson,
    CarePersonRow,
    SourceInput,
    SourceRef,
)
from membership_management.data.guests.lookup_services import get_led_open_guest_group_ids
from membership_management.data.members.models import Member
from membership_management.data.query_helpers import all_as
from membership_management.data.small_groups.access_rules import Perms, holds, small_group_scope_for
from membership_management.data.small_groups.models import (
    ReportSection,
    SmallGroupReportAttendance,
)
from membership_management.data.small_groups.queries import people_current_groups_query, people_query
from membership_management.data.small_groups.results import (
    PersonGroup,
    PersonGroupRow,
    PersonKey,
    TaggedPersonRow,
    person_key,
)
from membership_management.data.small_groups.services import (
    TAG_SEARCH_LIMIT,
    TAG_SEARCH_MIN_LENGTH,
    get_led_small_group_ids,
    phone_last4,
)

# Care spec rules 2, 3 and 4.
MAX_PEOPLE = 10
MAX_PARTICIPANTS = 10
MAX_TEXT = 4000
MAX_SHORT_TEXT = 200
MAX_CANCEL_REASON = 500
# Rule 11: how far ahead *Coming up* looks.
COMING_UP_DAYS = 7


class CareLogInvalidError(Exception):
    """A field is wrong: `code` is the name staff-app tells apart, `message` the 422 `detail`."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PersonNotFoundError(Exception):
    """Someone the entry is about doesn't exist or is outside the caller's scope: a 404, as for other
    scoped lookups."""


class SourceNotFoundError(Exception):
    """The report row, item or thread an entry is logged from doesn't exist."""


class EntryGoneError(Exception):
    """The entry was deleted while the caller was working on it: a 404."""


class NotPlannedError(Exception):
    """Only a planned entry can be completed or cancelled."""


class CareLogChanges(TypedDict, total=False):
    """What an edit may change (rule 10): only the keys present are touched."""

    kind: CareLogKind
    meeting_mode: MeetingMode | None
    occurred_on: date
    occurred_at_time: time | None
    text: str | None
    heard_from: str | None
    others: str | None
    visibility: CareLogVisibility
    people: list[PersonKey]
    participants: list[int]


def _clean(value: str | None) -> str | None:
    """Trimmed, and None when nothing is left."""
    if value is None:
        return None
    return value.strip() or None


def _db_now(session: Session) -> datetime:
    """The database clock, so the times written here compare on one clock."""
    return session.execute(select(func.clock_timestamp())).scalar_one()


def _entries_query() -> Select[tuple[CareLogEntry]]:
    return select(CareLogEntry).options(
        selectinload(CareLogEntry.people).options(
            joinedload(CareLogEntryPerson.member), joinedload(CareLogEntryPerson.guest)
        ),
        selectinload(CareLogEntry.participants).joinedload(CareLogEntryParticipant.member),
        joinedload(CareLogEntry.author),
    )


def get_entry(session: Session, entry_id: int) -> CareLogEntry | None:
    """The entry unless it was deleted (soft delete, rule 10): with its people, participants and author."""
    return session.scalars(
        _entries_query().where(CareLogEntry.id == entry_id, CareLogEntry.deleted_at.is_(None))
    ).one_or_none()


def load_entries(session: Session, entry_ids: Sequence[int]) -> list[CareLogEntry]:
    """These entries (not deleted) in the order of `entry_ids`."""
    if not entry_ids:
        return []
    rows = session.scalars(
        _entries_query().where(CareLogEntry.id.in_(entry_ids), CareLogEntry.deleted_at.is_(None))
    ).all()
    by_id = {entry.id: entry for entry in rows}
    return [by_id[i] for i in entry_ids if i in by_id]


def _reloaded(session: Session, entry_id: int) -> CareLogEntry:
    """The entry just written, loaded again with its people (a commit expires everything)."""
    entry = get_entry(session, entry_id)
    if entry is None:  # pragma: no cover - just committed
        raise RuntimeError("the entry just written is gone")
    return entry


def entry_visible(session: Session, viewer: CareLogViewer, entry_id: int) -> bool:
    """Rule 8 for one entry, by the same condition the lists use (`care_log_visible_condition`)."""
    return session.scalar(care_log_entry_visible_query(viewer, entry_id)) is not None


def participant_user_ids(session: Session, member_ids: Sequence[int]) -> dict[int, str | None]:
    """The auth-server user linked to each member (None: no user). `participants` 422 for an unknown id."""
    members = {m.id: m.user_id for m in session.scalars(select(Member).where(Member.id.in_(member_ids)))}
    if set(members) != set(member_ids):
        raise CareLogInvalidError("participants", "Someone you added doesn't exist.")
    return members


def participants_audience(
    session: Session,
    *,
    participants: Sequence[int],
    user_ids: Mapping[int, str | None],
    people: Sequence[PersonKey],
    visibility: CareLogVisibility,
    perms_by_user: Mapping[str, Perms] | None,
) -> dict[int, bool | None]:
    """For each participant (a member id): would they see an entry of the caller's, not yet saved, about
    `people` with this `visibility`? Participants get no access from being named (rule 3), so this tells
    the author who in "with whom" is outside the audience. It follows rule 8 with the participant's own
    permissions (`perms_by_user`, auth-server's answer by user id; a user missing from it is banned or
    unknown) and the members / guests scope of the groups they lead today. `perms_by_user` None means the
    permissions couldn't be had: nothing is known, so every answer is None. Scope queries only run for the
    participants whose answer depends on them."""
    if perms_by_user is None:
        return dict.fromkeys(participants, None)
    answers: dict[int, bool | None] = {}
    member_ids = [i for kind, i in people if kind == "member"]
    guest_ids = [i for kind, i in people if kind == "guest"]
    for member_id in dict.fromkeys(participants):
        user_id = user_ids.get(member_id)
        perms = perms_by_user.get(user_id) if user_id is not None else None
        if perms is None:
            answers[member_id] = False
            continue
        in_scope = False
        if participant_needs_scope(perms, visibility, is_one_of_the_people=member_id in member_ids):
            led = get_led_small_group_ids(session, member_id)
            group_scope = small_group_scope_for(perms, led, member_id)
            viewer = CareLogViewer(
                user_id=user_id or "",
                sees_all=False,
                can_view=True,
                members_full=holds(perms, "members", "all"),
                member_group_ids=(
                    frozenset()
                    if group_scope is None
                    else None
                    if group_scope.full
                    else group_scope.group_ids
                ),
                guests_full=holds(perms, "guests", "all"),
                guest_group_ids=get_led_open_guest_group_ids(session, member_id),
                member_id=member_id,
            )
            in_scope = bool(
                (
                    member_ids
                    and session.scalars(loggable_members_query(viewer, member_ids)).first() is not None
                )
                or (
                    guest_ids
                    and session.scalars(loggable_guests_query(viewer, guest_ids)).first() is not None
                )
            )
        answers[member_id] = participant_sees(
            perms, visibility, is_one_of_the_people=member_id in member_ids, person_in_scope=in_scope
        )
    return answers


def search_people(session: Session, viewer: CareLogViewer, text: str) -> list[CarePerson]:
    """Members and guests the caller may log about matching `text` by name (rule 2), at most
    TAG_SEARCH_LIMIT. Inactive members and guests are never found."""
    text = text.strip()
    if len(text) < TAG_SEARCH_MIN_LENGTH:
        return []
    rows = all_as(session, care_people_search_query(viewer, text, limit=TAG_SEARCH_LIMIT), CarePersonRow)
    if not rows:
        return []
    groups: dict[PersonKey, list[PersonGroup]] = {}
    member_ids = frozenset(r.id for r in rows if r.kind == "member")
    guest_ids = frozenset(r.id for r in rows if r.kind == "guest")
    for g in all_as(session, people_current_groups_query(member_ids, guest_ids), PersonGroupRow):
        groups.setdefault(person_key(g.member_id, g.guest_id), []).append(
            PersonGroup(g.id, g.name, g.audience, g.role)
        )
    return [
        CarePerson(
            person=(row.kind, row.id),
            name=row.name,
            groups=groups.get((row.kind, row.id), []),
            phone_last4=phone_last4(row.phone) if row.kind == "guest" else None,
        )
        for row in rows
    ]


# --- Validation ---------------------------------------------------------------------------------


def validate_fields(fields: CareLogFields, *, today: date, previous: CareLogEntry | None) -> CareLogFields:
    """Rules 1 to 6 for an entry about to be written: returns the fields cleaned (trimmed, people and
    participants without repeats) or raises `CareLogInvalidError`. `previous` is the entry being edited:
    an existing plan may keep a date in the past (it is waiting for *Record how it went*)."""
    text = _clean(fields.text)
    heard_from = _clean(fields.heard_from)
    others = _clean(fields.others)
    people = list(dict.fromkeys(fields.people))
    participants = list(dict.fromkeys(fields.participants))

    cancelled_ok = previous is not None and previous.status == CareLogStatus.CANCELLED
    if fields.status == CareLogStatus.CANCELLED and not cancelled_ok:
        raise CareLogInvalidError(
            "kind_status", "An entry is created as done or planned; cancel a plan instead."
        )
    # Planned and cancelled entries alike (CHECK ck_care_log_entries_plan_kinds): a cancelled plan's kind
    # can't be edited into one that is never planned.
    if fields.status != CareLogStatus.DONE and fields.kind not in PLANNABLE_KINDS:
        raise CareLogInvalidError("kind_status", "Only a call, meeting or visit can be planned.")

    if fields.status == CareLogStatus.DONE and fields.occurred_on > today:
        raise CareLogInvalidError("date", "Something that happened can't be in the future.")
    keeps_date = previous is not None and previous.occurred_on == fields.occurred_on
    if fields.status == CareLogStatus.PLANNED and fields.occurred_on < today and not keeps_date:
        raise CareLogInvalidError("date", "A plan can't be in the past.")

    if fields.status == CareLogStatus.DONE and text is None:
        raise CareLogInvalidError("text", "Write what happened.")
    if text is not None and len(text) > MAX_TEXT:
        raise CareLogInvalidError("text", f"The text can't be longer than {MAX_TEXT} characters.")
    if others is not None and len(others) > MAX_SHORT_TEXT:
        raise CareLogInvalidError("others", f"Others can't be longer than {MAX_SHORT_TEXT} characters.")
    if fields.kind == CareLogKind.HEARD and heard_from is None:
        raise CareLogInvalidError("heard_from", "Say who told us.")
    if heard_from is not None and fields.kind != CareLogKind.HEARD:
        raise CareLogInvalidError("heard_from", "Only something we heard says who told us.")
    if heard_from is not None and len(heard_from) > MAX_SHORT_TEXT:
        raise CareLogInvalidError(
            "heard_from", f"Who told us can't be longer than {MAX_SHORT_TEXT} characters."
        )
    if fields.kind == CareLogKind.MEETING and fields.meeting_mode is None:
        raise CareLogInvalidError("meeting_mode", "Say whether the meeting was in person or online.")
    if fields.kind != CareLogKind.MEETING and fields.meeting_mode is not None:
        raise CareLogInvalidError("meeting_mode", "Only a meeting has a mode.")

    if not people:
        raise CareLogInvalidError("people", "Pick at least one person.")
    if len(people) > MAX_PEOPLE:
        raise CareLogInvalidError("people", f"An entry can be about at most {MAX_PEOPLE} people.")
    if len(participants) > MAX_PARTICIPANTS:
        raise CareLogInvalidError(
            "participants", f"At most {MAX_PARTICIPANTS} other staff can be added to an entry."
        )
    return replace(
        fields, text=text, heard_from=heard_from, others=others, people=people, participants=participants
    )


def check_people(session: Session, viewer: CareLogViewer, people: Collection[PersonKey]) -> None:
    """Everyone must be in the caller's scope (`careLog: all` has no limit): `PersonNotFoundError` (404)
    for anyone who isn't, or doesn't exist; then 422 `people` for anyone inactive (rule 2)."""
    member_ids = frozenset(i for kind, i in people if kind == "member")
    guest_ids = frozenset(i for kind, i in people if kind == "guest")
    reachable: set[PersonKey] = set()
    if member_ids:
        reachable |= {("member", i) for i in session.scalars(loggable_members_query(viewer, member_ids))}
    if guest_ids:
        reachable |= {("guest", i) for i in session.scalars(loggable_guests_query(viewer, guest_ids))}
    if any(person not in reachable for person in people):
        raise PersonNotFoundError
    rows = all_as(session, people_query(member_ids, guest_ids), TaggedPersonRow)
    if any(row.inactive for row in rows):
        raise CareLogInvalidError("people", "An inactive member or guest can't be added to a care log entry.")


def check_participants(session: Session, participants: Collection[int]) -> None:
    if not participants:
        return
    found = set(session.scalars(existing_members_query(participants)))
    if found != set(participants):
        raise CareLogInvalidError("participants", "Someone you added doesn't exist.")


# --- Sources ------------------------------------------------------------------------------------


def _source_ref(
    kind: CareLogSourceKind,
    report: Row | None,
    *,
    observation: bool,
    section: ReportSection | None = None,
) -> SourceRef:
    """A SourceRef for a row of `source_reports_query` (None: the source is gone)."""
    if report is None:
        return SourceRef(kind, False, None, None, None, None, None, None, observation, section)
    return SourceRef(
        kind,
        True,
        report.report_id,
        report.meeting_date,
        report.group_id,
        report.group_name,
        report.group_audience,
        report.report_status,
        observation,
        section,
        report.held,
    )


def resolve_source(session: Session, source: SourceInput) -> SourceRef:
    """What the caller names as the source, if it exists (`SourceNotFoundError` otherwise). Whether the
    caller may see it is the API's to say (it knows the observation audience)."""
    if source.kind == CareLogSourceKind.ATTENDANCE:
        if source.report_id is None or source.person is None:
            raise SourceNotFoundError
        kind, person_id = source.person
        on_list = session.scalar(
            select(SmallGroupReportAttendance.id).where(
                SmallGroupReportAttendance.report_id == source.report_id,
                (
                    SmallGroupReportAttendance.member_id
                    if kind == "member"
                    else SmallGroupReportAttendance.guest_id
                )
                == person_id,
            )
        )
        if on_list is None:
            raise SourceNotFoundError
        report = session.execute(source_reports_query([source.report_id])).one_or_none()
        return _source_ref(CareLogSourceKind.ATTENDANCE, report, observation=True)
    if source.kind == CareLogSourceKind.SECTION:
        if source.report_id is None or source.section is None:
            raise SourceNotFoundError
        report = session.execute(source_reports_query([source.report_id])).one_or_none()
        if report is None:
            raise SourceNotFoundError
        return _source_ref(
            CareLogSourceKind.SECTION,
            report,
            observation=source.section == ReportSection.FOLLOW_UP,
            section=source.section,
        )
    if source.conversation_id is None:
        raise SourceNotFoundError
    conversation = session.execute(source_conversations_query([source.conversation_id])).one_or_none()
    if conversation is None:
        raise SourceNotFoundError
    report = session.execute(source_reports_query([conversation.report_id])).one_or_none()
    return _source_ref(CareLogSourceKind.CONVERSATION, report, observation=True)


def source_refs(session: Session, entries: Sequence[CareLogEntry]) -> dict[int, SourceRef]:
    """The source of each entry that has one, by entry id: two queries at most. A source that was
    deleted (its ids went null) is `exists=False`."""
    wanted = [e for e in entries if e.source_kind is not None]
    if not wanted:
        return {}
    conversation_ids = {e.source_conversation_id for e in wanted if e.source_conversation_id is not None}
    conversations = (
        {c.id: c for c in session.execute(source_conversations_query(conversation_ids))}
        if conversation_ids
        else {}
    )
    report_ids = {e.source_report_id for e in wanted if e.source_report_id is not None}
    report_ids |= {c.report_id for c in conversations.values()}
    reports = (
        {r.report_id: r for r in session.execute(source_reports_query(report_ids))} if report_ids else {}
    )
    refs: dict[int, SourceRef] = {}
    for entry in wanted:
        kind = entry.source_kind
        if kind is None:
            continue
        if kind == CareLogSourceKind.ATTENDANCE:
            refs[entry.id] = _source_ref(kind, reports.get(entry.source_report_id or 0), observation=True)
        elif kind == CareLogSourceKind.SECTION:
            refs[entry.id] = _source_ref(
                kind,
                reports.get(entry.source_report_id or 0),
                observation=entry.source_section == ReportSection.FOLLOW_UP,
                section=entry.source_section,
            )
        else:
            conversation = conversations.get(entry.source_conversation_id or 0)
            refs[entry.id] = _source_ref(
                kind,
                reports.get(conversation.report_id) if conversation is not None else None,
                observation=True,
            )
    return refs


def _apply_source(entry: CareLogEntry, source: SourceInput) -> None:
    entry.source_kind = source.kind
    if source.kind == CareLogSourceKind.ATTENDANCE and source.person is not None:
        entry.source_report_id = source.report_id
        entry.source_member_id = source.person[1] if source.person[0] == "member" else None
        entry.source_guest_id = source.person[1] if source.person[0] == "guest" else None
    elif source.kind == CareLogSourceKind.SECTION:
        entry.source_report_id = source.report_id
        entry.source_section = source.section
    else:
        entry.source_conversation_id = source.conversation_id


# --- Writes -------------------------------------------------------------------------------------


def _person_rows(people: Collection[PersonKey]) -> list[CareLogEntryPerson]:
    return [
        CareLogEntryPerson(
            member_id=person_id if kind == "member" else None,
            guest_id=person_id if kind == "guest" else None,
        )
        for kind, person_id in people
    ]


def create_entry(
    session: Session,
    viewer: CareLogViewer,
    fields: CareLogFields,
    *,
    author_user_id: str,
    author_member_id: int,
    source: SourceInput | None,
    today: date,
) -> CareLogEntry:
    """Rules 1 to 7 and 12: validates, checks the people are in the caller's scope and writes the entry
    with its people and participants."""
    fields = validate_fields(fields, today=today, previous=None)
    check_people(session, viewer, fields.people)
    check_participants(session, fields.participants)
    entry = CareLogEntry(
        kind=fields.kind,
        status=fields.status,
        meeting_mode=fields.meeting_mode,
        occurred_on=fields.occurred_on,
        occurred_at_time=fields.occurred_at_time,
        text=fields.text,
        heard_from=fields.heard_from,
        others=fields.others,
        visibility=fields.visibility,
        author_user_id=author_user_id,
        author_member_id=author_member_id,
        people=_person_rows(fields.people),
        participants=[CareLogEntryParticipant(member_id=m) for m in fields.participants],
    )
    if source is not None:
        _apply_source(entry, source)
    session.add(entry)
    session.commit()
    return _reloaded(session, entry.id)


def fields_of(entry: CareLogEntry) -> CareLogFields:
    return CareLogFields(
        kind=entry.kind,
        status=entry.status,
        meeting_mode=entry.meeting_mode,
        occurred_on=entry.occurred_on,
        occurred_at_time=entry.occurred_at_time,
        text=entry.text,
        heard_from=entry.heard_from,
        others=entry.others,
        visibility=entry.visibility,
        people=[person_key(p.member_id, p.guest_id) for p in entry.people],
        participants=[p.member_id for p in entry.participants],
    )


def update_entry(
    session: Session,
    viewer: CareLogViewer,
    entry: CareLogEntry,
    changes: CareLogChanges,
    *,
    today: date,
) -> CareLogEntry:
    """Rule 10: the author edits any field but the status, any time. A changed text keeps the old one in
    `care_log_entry_revisions` (never returned). Only people added now are checked against the scope. The
    row is locked first and the rules run against what it holds then, so an edit can't overwrite the
    outcome of a concurrent complete or write a revision of the wrong text."""
    _lock_entry(session, entry)
    current = fields_of(entry)
    merged = replace(current, **changes)
    merged = validate_fields(merged, today=today, previous=entry)
    added = [p for p in merged.people if p not in current.people]
    check_people(session, viewer, added)
    check_participants(session, [m for m in merged.participants if m not in current.participants])
    if merged == current:
        return entry
    now = _db_now(session)
    if merged.text != current.text:
        entry.revisions.append(CareLogEntryRevision(text=current.text, created_at=now))
    entry.kind = merged.kind
    entry.meeting_mode = merged.meeting_mode
    entry.occurred_on = merged.occurred_on
    entry.occurred_at_time = merged.occurred_at_time
    entry.text = merged.text
    entry.heard_from = merged.heard_from
    entry.others = merged.others
    entry.visibility = merged.visibility
    if merged.people != current.people:
        for row in list(entry.people):
            if person_key(row.member_id, row.guest_id) not in merged.people:
                entry.people.remove(row)
        entry.people.extend(_person_rows(added))
    if merged.participants != current.participants:
        for participant in list(entry.participants):
            if participant.member_id not in merged.participants:
                entry.participants.remove(participant)
        entry.participants.extend(
            CareLogEntryParticipant(member_id=m) for m in merged.participants if m not in current.participants
        )
    entry.edited_at = now
    session.commit()
    return _reloaded(session, entry.id)


def delete_entry(session: Session, entry: CareLogEntry) -> None:
    """Soft delete (rule 10): the row and its texts stay, the API never returns them again."""
    entry.deleted_at = _db_now(session)
    session.commit()


def _lock_entry(session: Session, entry: CareLogEntry) -> None:
    """Lock the entry's row (if it isn't deleted) and read it again, so whatever is decided next sees what
    a concurrent write left. `EntryGoneError` (404) when it was deleted meanwhile."""
    locked = session.scalar(
        select(CareLogEntry.id)
        .where(CareLogEntry.id == entry.id, CareLogEntry.deleted_at.is_(None))
        .with_for_update()
    )
    if locked is None:
        raise EntryGoneError
    session.refresh(entry)


def _lock_planned(session: Session, entry: CareLogEntry) -> None:
    """Lock the entry and require it is still planned: a complete and a cancel (or two completes) racing
    each other can't both win, and no outcome is lost."""
    _lock_entry(session, entry)
    if entry.status != CareLogStatus.PLANNED:
        raise NotPlannedError


def complete_entry(
    session: Session, entry: CareLogEntry, *, text: str | None, occurred_on: date | None, today: date
) -> CareLogEntry:
    """Rule 6: a planned entry becomes done with the outcome text (required) and the actual date
    (default: the planned one), never in the future. The purpose it had is kept as a revision."""
    _lock_planned(session, entry)
    outcome = _clean(text)
    if outcome is None:
        raise CareLogInvalidError("text", "Write what happened.")
    if len(outcome) > MAX_TEXT:
        raise CareLogInvalidError("text", f"The text can't be longer than {MAX_TEXT} characters.")
    day = occurred_on if occurred_on is not None else entry.occurred_on
    if day > today:
        raise CareLogInvalidError("date", "Something that happened can't be in the future.")
    now = _db_now(session)
    if entry.text is not None:
        entry.revisions.append(CareLogEntryRevision(text=entry.text, created_at=now))
    entry.text = outcome
    entry.occurred_on = day
    entry.status = CareLogStatus.DONE
    entry.completed_at = now
    session.commit()
    return _reloaded(session, entry.id)


def cancel_entry(session: Session, entry: CareLogEntry, *, reason: str | None) -> CareLogEntry:
    """Rule 6: a planned entry stays visible as cancelled, with an optional reason."""
    _lock_planned(session, entry)
    cleaned = _clean(reason)
    if cleaned is not None and len(cleaned) > MAX_CANCEL_REASON:
        raise CareLogInvalidError(
            "reason", f"The reason can't be longer than {MAX_CANCEL_REASON} characters."
        )
    entry.status = CareLogStatus.CANCELLED
    entry.cancel_reason = cleaned
    session.commit()
    return _reloaded(session, entry.id)


def is_participant(entry: CareLogEntry, member_id: int | None) -> bool:
    return member_id is not None and any(p.member_id == member_id for p in entry.participants)


def coming_up(
    session: Session, viewer: CareLogViewer, member_id: int | None, *, today: date
) -> tuple[list[CareLogEntry], list[CareLogEntry]]:
    """Rule 11: the caller's planned entries (author or participant) not deleted: (past due, oldest
    first; today through the next COMING_UP_DAYS days, soonest first)."""
    ids = list(session.scalars(coming_up_query(viewer, member_id, today=today, horizon_days=COMING_UP_DAYS)))
    entries = load_entries(session, ids)
    return (
        [e for e in entries if e.occurred_on < today],
        [e for e in entries if e.occurred_on >= today],
    )
