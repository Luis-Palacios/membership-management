from datetime import date, datetime
from typing import Literal, NamedTuple

from membership_management.data.small_groups.models import (
    ConversationSide,
    ConversationStatus,
    SmallGroupRole,
)


class SmallGroupSummary(NamedTuple):
    id: int
    name: str
    meeting_address: str | None
    meeting_day: int | None
    closed_at: date | None
    active_member_count: int
    leader_member_id: int | None
    leader_name: str | None


class SmallGroupActiveMember(NamedTuple):
    member_id: int
    member_name: str
    role: SmallGroupRole
    joined_at: date


class RosterPeriod(NamedTuple):
    member_id: int
    member_name: str
    role: SmallGroupRole
    joined_at: date
    left_at: date | None
    period_id: int


class AttendanceMark(NamedTuple):
    member_id: int
    attended_group: bool


class RosterPerson(NamedTuple):
    """Someone who belongs in a report for a date, with the role they held that day."""

    member_id: int
    member_name: str
    role: SmallGroupRole
    joined_at: date
    missed_streak: int


class ReportRoster(NamedTuple):
    people: list[RosterPerson]
    existing_report_id: int | None
    existing_report_held: bool | None = None


class AttendanceInput(NamedTuple):
    member_id: int
    attended_group: bool
    attended_church: bool
    observation: str | None


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


class ReportAttendanceView(NamedTuple):
    member_id: int
    member_name: str
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
    small_group_meeting_address: str | None
    small_group_closed_at: date | None
    meeting_date: date
    address: str | None
    group_prayer_request: str | None
    group_praise_report: str | None
    group_relevant_discussion: str | None
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
    meeting_day: int | None
    closed_at: date | None


class FiledReportRow(NamedTuple):
    id: int
    small_group_id: int
    small_group_name: str
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
    group_prayer_request: str | None
    group_praise_report: str | None
    group_relevant_discussion: str | None


class SharedEntry(NamedTuple):
    """A held report's three texts, trimmed (blank is None), with the group's leaders today."""

    report_id: int
    meeting_date: date
    small_group_id: int
    small_group_name: str
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


class ConversationSummary(NamedTuple):
    """A thread's row indicator on the report detail. `unread` and `needs_my_reply` are the caller's."""

    id: int
    member_id: int
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
    member_id: int
    member_name: str
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
    member: ConversationMember
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
