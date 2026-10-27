from datetime import date, datetime
from typing import TYPE_CHECKING, Literal, NamedTuple

from membership_management.data.small_groups.models import (
    ConversationSide,
    ConversationStatus,
    GroupAudience,
    ReportSection,
    SmallGroupRole,
)

if TYPE_CHECKING:
    # report_items imports PersonKey from here; annotations are evaluated lazily.
    from membership_management.data.small_groups.report_items import Segment

# A member or a guest, as in an attendance row: ("member", id) or ("guest", id).
PersonKey = tuple[Literal["member", "guest"], int]


def person_key(member_id: int | None, guest_id: int | None) -> PersonKey:
    """The key of whoever a row is about: exactly one of the two ids is set."""
    if member_id is not None:
        return ("member", member_id)
    if guest_id is not None:
        return ("guest", guest_id)
    raise ValueError("a row needs a member or a guest")


class SmallGroupSummary(NamedTuple):
    id: int
    name: str
    audience: GroupAudience
    meeting_address: str | None
    meeting_day: int | None
    closed_at: date | None
    # Members only; guests are counted apart (guest-small-groups rule 20).
    active_member_count: int
    active_guest_count: int
    leader_member_id: int | None
    leader_name: str | None


class SmallGroupActiveMember(NamedTuple):
    member_id: int
    member_name: str
    role: SmallGroupRole
    joined_at: date


class SmallGroupActiveGuest(NamedTuple):
    guest_id: int
    guest_name: str
    joined_at: date


class GuestStanding(NamedTuple):
    """How a guest in a guest group is doing, for the group detail."""

    guest_id: int
    missed_streak: int
    last_attended_date: date | None


class OtherGroup(NamedTuple):
    """The guest group a guest is active in, as much as a caller outside its scope may learn (rule 7)."""

    id: int
    name: str
    joined_at: date


class RosterPeriod(NamedTuple):
    # Exactly one of the two ids.
    member_id: int | None
    guest_id: int | None
    name: str
    role: SmallGroupRole
    joined_at: date
    left_at: date | None
    period_id: int


class AttendanceMark(NamedTuple):
    # Exactly one of the two ids, as in the attendance row.
    member_id: int | None
    guest_id: int | None
    attended_group: bool


class RosterPerson(NamedTuple):
    """Someone who belongs in a report for a date, with the role they held that day: a member, or a
    guest of a guest group (always a plain participant)."""

    # Exactly one of the two ids.
    member_id: int | None
    guest_id: int | None
    name: str
    role: SmallGroupRole
    joined_at: date
    missed_streak: int

    @property
    def key(self) -> PersonKey:
        return person_key(self.member_id, self.guest_id)


class ReportRoster(NamedTuple):
    people: list[RosterPerson]
    existing_report_id: int | None
    existing_report_held: bool | None = None


class AttendanceInput(NamedTuple):
    # Exactly one of the two ids.
    member_id: int | None
    guest_id: int | None
    attended_group: bool
    attended_church: bool
    observation: str | None


# A report's items as sent: per section, each item's segments (person segments carry ids only).
SectionsInput = dict[ReportSection, list[list["Segment"]]]


class ReportInput(NamedTuple):
    """The body of a create or edit, already trimmed (blank text is None)."""

    meeting_date: date
    address: str | None
    group_prayer_request: str | None
    group_praise_report: str | None
    group_relevant_discussion: str | None
    attendances: list[AttendanceInput]
    # A no meeting (held False) carries no texts or attendances, only the optional reason.
    held: bool = True
    not_held_reason: str | None = None
    # Create only: delete the date's no meeting and insert this held report in one transaction.
    replaces_no_meeting: bool = False
    # When set it wins over the three texts above, which are then ignored; when None, each text is
    # split into items, one per line (report tags rule 2), until the old fields go away.
    sections: SectionsInput | None = None


class ReportItemRow(NamedTuple):
    id: int
    report_id: int
    section: ReportSection
    text: str


class TaggedPersonRow(NamedTuple):
    kind: Literal["member", "guest"]
    id: int
    name: str
    inactive: bool


class TagSearchRow(NamedTuple):
    kind: Literal["member", "guest"]
    id: int
    name: str
    phone: str | None
    in_this_group: bool


class PersonGroupRow(NamedTuple):
    # Exactly one of the two ids.
    member_id: int | None
    guest_id: int | None
    id: int
    name: str
    audience: GroupAudience
    role: SmallGroupRole


class PersonGroup(NamedTuple):
    id: int
    name: str
    audience: GroupAudience
    role: SmallGroupRole


class TaggablePerson(NamedTuple):
    """A tag search row: only what tells people apart (report tags rules 8 and 10)."""

    person: PersonKey
    name: str
    in_this_group: bool
    # Open groups the person is active in today, by name.
    groups: list[PersonGroup]
    # Guests only: the last 4 digits of their phone, None when it has fewer.
    phone_last4: str | None


class ReportItemView(NamedTuple):
    """An item with its person segments named (current names)."""

    id: int
    section: ReportSection
    segments: list["Segment"]


class ReportAttendanceView(NamedTuple):
    # Exactly one of the two ids.
    member_id: int | None
    guest_id: int | None
    name: str
    role: SmallGroupRole
    # Start of the membership period covering the meeting date; None if memberships were edited since.
    joined_at: date | None
    attended_group: bool
    attended_church: bool
    missed_streak: int
    # Always None when the viewer may not see observations (rule 9), so no mapping can leak one.
    observation: str | None


class ReportDetail(NamedTuple):
    id: int
    small_group_id: int
    small_group_name: str
    small_group_audience: GroupAudience
    small_group_meeting_address: str | None
    small_group_closed_at: date | None
    meeting_date: date
    address: str | None
    # Derived from the items (one per line, people by full name) until the old fields go away.
    group_prayer_request: str | None
    group_praise_report: str | None
    group_relevant_discussion: str | None
    # By section, then position.
    items: list[ReportItemView]
    submitted_by_member_id: int
    submitted_by_name: str
    submitted_at: datetime
    observations_visible: bool
    attendances: list[ReportAttendanceView]
    held: bool = True
    not_held_reason: str | None = None
    # Threads on the report; the delete dialog says they go with it. Not an observation: always set.
    conversation_count: int = 0


class ReportGroupRow(NamedTuple):
    id: int
    name: str
    audience: GroupAudience
    meeting_day: int | None
    closed_at: date | None


class FiledReportRow(NamedTuple):
    id: int
    small_group_id: int
    small_group_name: str
    small_group_audience: GroupAudience
    small_group_closed_at: date | None
    meeting_date: date
    submitted_by_member_id: int
    submitted_by_name: str
    submitted_at: datetime
    roster_count: int
    attended_group_count: int
    attended_church_count: int
    held: bool = True
    not_held_reason: str | None = None


class NotFiledMeeting(NamedTuple):
    small_group_id: int
    small_group_name: str
    small_group_audience: GroupAudience
    small_group_closed_at: date | None
    meeting_date: date


class ReportDate(NamedTuple):
    report_id: int
    small_group_id: int
    meeting_date: date
    held: bool


class LeadershipPeriod(NamedTuple):
    small_group_id: int
    joined_at: date
    left_at: date | None


class RecentMeeting(NamedTuple):
    """A date rule 10 looks at, with the report filed on it (None when not filed)."""

    date: date
    report_id: int | None
    # None when not filed.
    held: bool | None = None


class GroupRole(NamedTuple):
    small_group_id: int
    role: SmallGroupRole


class ReportCounts(NamedTuple):
    all: int
    # Held reports only; a no meeting counts under `not_held`.
    filed: int
    not_held: int
    not_filed: int


class ReportPage(NamedTuple):
    items: list[FiledReportRow | NotFiledMeeting]
    counts: ReportCounts
    total: int


class GroupReportSummary(NamedTuple):
    group: ReportGroupRow
    role: SmallGroupRole | None
    last_report: FiledReportRow | None
    not_filed_dates: list[date]
    # An active leader or co-leader today.
    has_leader: bool
    # Newest first; `not_filed_dates` is the entries without a report.
    recent_meetings: list[RecentMeeting]


WeekStatus = Literal["submitted", "notHeld", "notFiled", "today", "upcoming", "noLeader", "noMeetingDay"]


class WeekReportRow(NamedTuple):
    """A report dated in the week, with counts only: observation text never leaves the database."""

    id: int
    small_group_id: int
    meeting_date: date
    roster_count: int
    attended_group_count: int
    attended_church_count: int
    observation_count: int
    submitted_by_member_id: int
    submitted_by_name: str
    held: bool = True
    not_held_reason: str | None = None


class ActiveLeaderRow(NamedTuple):
    small_group_id: int
    member_id: int
    member_name: str
    role: SmallGroupRole


class WeekLeader(NamedTuple):
    member_id: int
    name: str
    role: SmallGroupRole


class WeekGroup(NamedTuple):
    group: ReportGroupRow
    leaders: list[WeekLeader]
    status: WeekStatus
    # The week's date on the group's meeting day (even when the report is on another day).
    meeting_date: date | None
    reports: list[WeekReportRow]


class ReportWeek(NamedTuple):
    week_start: date
    week_end: date
    today: date
    is_current_week: bool
    groups: list[WeekGroup]


class SharedReportRow(NamedTuple):
    report_id: int
    meeting_date: date
    small_group_id: int
    small_group_name: str
    small_group_audience: GroupAudience
    group_prayer_request: str | None
    group_praise_report: str | None
    group_relevant_discussion: str | None


class SharedEntry(NamedTuple):
    """A held report's three texts, trimmed (blank is None), with the group's leaders today."""

    report_id: int
    meeting_date: date
    small_group_id: int
    small_group_name: str
    small_group_audience: GroupAudience
    leaders: list[WeekLeader]
    prayer: str | None
    praise: str | None
    follow_up: str | None


StillToReportStatus = Literal["notFiled", "today", "upcoming"]


class StillToReport(NamedTuple):
    group: ReportGroupRow
    status: StillToReportStatus
    meeting_date: date


class ReportShared(NamedTuple):
    week_start: date
    week_end: date
    today: date
    is_current_week: bool
    entries: list[SharedEntry]
    # Open groups that may still add texts this week (or didn't, in a past week), as the week view.
    still_to_report: list[StillToReport]


class ConversationMember(NamedTuple):
    member_id: int
    name: str


class ConversationPerson(NamedTuple):
    """Who a thread is about: a member or a guest (never set for a section thread)."""

    type: Literal["member", "guest"]
    id: int
    name: str


class ConversationSummary(NamedTuple):
    """A thread's row indicator on the report detail. `unread` and `needs_my_reply` are the caller's."""

    id: int
    # The anchor: a member, a guest or a report section, exactly one.
    member_id: int | None
    guest_id: int | None
    # Null for a section thread.
    person: ConversationPerson | None
    section: ReportSection | None
    status: ConversationStatus
    comment_count: int
    unread: bool
    needs_my_reply: bool
    last_comment_at: datetime


class ConversationSummaries(NamedTuple):
    conversations: list[ConversationSummary]
    total: int
    needs_my_reply: int


class CommentAuthor(NamedTuple):
    member_id: int
    name: str
    side: ConversationSide


class ConversationComment(NamedTuple):
    id: int
    author: CommentAuthor
    # None once deleted: the stored text is never returned again.
    body: str | None
    created_at: datetime
    edited_at: datetime | None
    deleted: bool
    # Written by the caller (author_user_id is the caller's sub).
    mine: bool


class ConversationThread(NamedTuple):
    id: int
    # The anchor: a member (`member_id`, with their name), a guest or a report section, exactly one.
    member_id: int | None
    member_name: str | None
    guest_id: int | None
    # Null for a section thread.
    person: ConversationPerson | None
    section: ReportSection | None
    status: ConversationStatus
    resolved_by: ConversationMember | None
    resolved_at: datetime | None
    # First comment by someone else after the caller's last_read_at; None if none.
    first_unread_comment_id: int | None
    comments: list[ConversationComment]


class InboxGroup(NamedTuple):
    id: int
    name: str
    closed: bool
    audience: GroupAudience


class InboxReport(NamedTuple):
    id: int
    meeting_date: date


class InboxLastComment(NamedTuple):
    author_name: str
    mine: bool
    deleted: bool
    # First 160 characters of the newest non-deleted comment, whitespace collapsed; None if all deleted.
    excerpt: str | None
    created_at: datetime


class InboxRow(NamedTuple):
    id: int
    status: ConversationStatus
    needs_my_reply: bool
    unread: bool
    # None for a section thread, and for a guest's (`person` has them).
    member: ConversationMember | None
    # Who the thread is about, a member or a guest; None for a section thread.
    person: ConversationPerson | None
    section: ReportSection | None
    group: InboxGroup
    report: InboxReport
    last_comment: InboxLastComment
    resolved_by: ConversationMember | None
    comment_count: int


class InboxCounts(NamedTuple):
    reply: int
    open: int
    resolved: int


class InboxPage(NamedTuple):
    items: list[InboxRow]
    counts: InboxCounts
    total: int
