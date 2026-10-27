from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from membership_management.data.guests.models import Guest
from membership_management.data.members.models import Member, MemberSex
from membership_management.data.seed import fixtures
from membership_management.data.seed.context import MANAGUA_TZ, SeedContext
from membership_management.data.seed.members import _ascii, _phone, managua_address
from membership_management.data.seed.report_items import add_report_items
from membership_management.data.seed.small_group_reports import WEEKS_OF_REPORTS
from membership_management.data.small_groups.models import (
    GroupAudience,
    LeftReason,
    SmallGroup,
    SmallGroupMember,
    SmallGroupReport,
    SmallGroupReportAttendance,
    SmallGroupRole,
)
from membership_management.data.small_groups.results import PersonKey, person_key

STEADY_ATTENDANCE_RATE = 0.85
ATTENDED_CHURCH_RATE = 0.5
# Supporting members of a guest group come to nearly every meeting.
MEMBER_ATTENDANCE_RATE = 0.95
MEMBER_CHURCH_RATE = 0.85

# (name, ISO weekday, neighborhood it meets in)
GUEST_GROUPS = [
    ("Primeros Pasos", 7, "Altagracia"),
    ("Nuevos Comienzos", 4, "Bolonia"),
]


@dataclass
class _GuestPlan:
    """A guest's story, in meeting indexes of their group (0 = oldest of the seeded meetings)."""

    name: str
    group: int  # index into GUEST_GROUPS
    # First meeting they are in the group for; None = joined before the seeded meetings.
    joined_at_meeting: int | None
    # Attendance of each meeting from the first one they're in, then steady: a list is taken
    # literally, a number N means "came until the last N meetings, then missed them all".
    attendance: list[bool] | int | None = None
    phone: str | None = "random"
    # They leave the group at this meeting (on its date, so that report still has their row).
    stopped_at_meeting: int | None = None
    # They move to another guest group at this meeting of the other group: (group index, meeting).
    moves_to: tuple[int, int] | None = None
    # Shares the phone number of the guest with this name (the near-duplicate pair).
    phone_of: str | None = None


PLANS = [
    _GuestPlan("Ana Rivas Cuadra", 0, None),
    _GuestPlan("Walter Pineda Solís", 0, None, attendance=4),  # missed the last 4 meetings
    _GuestPlan("Mayra Solís Obando", 0, None, attendance=6),  # past 5
    _GuestPlan("Josué Barrera Lanzas", 0, 5),  # came for the first time recently
    _GuestPlan("Lorena Quiroz Medrano", 0, 1, phone=None),
    _GuestPlan("Carolina Baldizón Téllez", 0, 2),
    _GuestPlan("Hilario Mena Zeledón", 0, None, stopped_at_meeting=2),  # now in no group
    _GuestPlan("Tatiana Ruiz Gaitán", 0, None, moves_to=(1, 4)),  # Primeros Pasos -> Nuevos Comienzos
    _GuestPlan("Elmer Jarquín Báez", 1, None),
    _GuestPlan("Rosaura Altamirano Lacayo", 1, 1),
    _GuestPlan("Kevin Espinoza Mairena", 1, 3, phone=None),
    # Same person registered twice (one with the accent missing), same phone: the duplicate hint.
    _GuestPlan("Carolina Baldizon Tellez", 1, 3, phone_of="Carolina Baldizón Téllez"),
]


def seed_guests(ctx: SeedContext) -> None:
    """Two guest groups with members leading and supporting, twelve guests and their last reports."""
    rng, session, today = ctx.rng, ctx.session, ctx.today
    people = _pick_members(ctx)

    groups: list[SmallGroup] = []
    for (name, meeting_day, neighborhood), (leader, co_leader, supporter) in zip(
        GUEST_GROUPS, people, strict=True
    ):
        meetings = _meeting_dates(meeting_day, today)
        group = SmallGroup(
            name=name,
            audience=GroupAudience.GUESTS,
            meeting_day=meeting_day,
            meeting_address=managua_address(rng, neighborhood),
        )
        session.add(group)
        session.flush()
        started = meetings[0] - timedelta(days=rng.randint(60, 200))
        for member, role in ((leader, SmallGroupRole.LEADER), (co_leader, SmallGroupRole.CO_LEADER)):
            if member is not None:
                session.add(
                    SmallGroupMember.for_group(group, member_id=member.id, role=role, joined_at=started)
                )
        session.add(
            SmallGroupMember.for_group(
                group, member_id=supporter.id, role=SmallGroupRole.MEMBER, joined_at=started
            )
        )
        groups.append(group)
    session.flush()

    meetings = [_meeting_dates(day, today) for _, day, _ in GUEST_GROUPS]
    leaders = [leader for leader, _, _ in people]
    periods = _seed_guests_and_periods(ctx, groups, meetings, leaders)
    _seed_reports(ctx, groups, meetings, leaders, periods)


def _pick_members(ctx: SeedContext) -> list[tuple[Member, Member | None, Member]]:
    """Per guest group, (leader, co-leader or None, supporter): members that lead no group today."""
    session, rng = ctx.session, ctx.rng
    leading = set(
        session.scalars(
            select(SmallGroupMember.member_id).where(SmallGroupMember.role != SmallGroupRole.MEMBER)
        )
    )
    free = [m for m in session.scalars(select(Member).order_by(Member.id)) if m.id not in leading]
    men = [m for m in free if m.sex == MemberSex.MALE]
    women = [m for m in free if m.sex == MemberSex.FEMALE]
    # Seed data only: leaders are men, as in the member groups. Primeros Pasos also has a woman as
    # supporting co-leader.
    leader_a, leader_b, supporter_b = rng.sample(men, 3)
    co_leader_a, supporter_a = rng.sample(women, 2)
    return [(leader_a, co_leader_a, supporter_a), (leader_b, None, supporter_b)]


def _meeting_dates(meeting_day: int, today: date) -> list[date]:
    """The last WEEKS_OF_REPORTS meeting days strictly before today, oldest first."""
    days_back = (today.isoweekday() - meeting_day) % 7 or 7
    latest = today - timedelta(days=days_back)
    return [latest - timedelta(weeks=week) for week in reversed(range(WEEKS_OF_REPORTS))]


@dataclass
class _Period:
    guest: Guest
    plan: _GuestPlan
    group: SmallGroup
    joined_at: date
    left_at: date | None


def _seed_guests_and_periods(
    ctx: SeedContext, groups: list[SmallGroup], meetings: list[list[date]], leaders: list[Member]
) -> list[_Period]:
    rng, session = ctx.rng, ctx.session
    members = list(session.scalars(select(Member).order_by(Member.id)))
    by_name: dict[str, Guest] = {}
    periods: list[_Period] = []
    for plan in PLANS:
        group_index = plan.group
        group_meetings = meetings[group_index]
        first = plan.joined_at_meeting
        joined_at = (
            group_meetings[0] - timedelta(days=rng.randint(7, 60)) if first is None else group_meetings[first]
        )
        guest = Guest(
            name=plan.name,
            phone=by_name[plan.phone_of].phone if plan.phone_of else (_phone(rng) if plan.phone else None),
            email=_email(plan.name) if rng.random() < 0.4 else None,
            sex=rng.choice([MemberSex.MALE, MemberSex.FEMALE]) if rng.random() < 0.8 else None,
            address=managua_address(rng) if rng.random() < 0.7 else None,
            first_visit_date=joined_at,
            invited_by_member_id=rng.choice(members).id if rng.random() < 0.6 else None,
            created_by_member_id=leaders[group_index].id,
            # Set, not the server's now(): two seed runs must give identical rows.
            created_at=datetime.combine(joined_at, time(12, 0), MANAGUA_TZ),
        )
        session.add(guest)
        session.flush()
        by_name[plan.name] = guest

        left_at = None
        left_reason = None
        if plan.stopped_at_meeting is not None:
            left_at, left_reason = group_meetings[plan.stopped_at_meeting], LeftReason.STOPPED_COMING
        elif plan.moves_to is not None:
            target_group, target_meeting = plan.moves_to
            # The old period ends the day before the new one starts.
            left_at, left_reason = (
                meetings[target_group][target_meeting] - timedelta(days=1),
                LeftReason.MOVED_GROUP,
            )
        row = SmallGroupMember.for_group(
            groups[group_index], guest_id=guest.id, joined_at=joined_at, left_at=left_at
        )
        row.left_reason = left_reason
        session.add(row)
        periods.append(_Period(guest, plan, groups[group_index], joined_at, left_at))
        if plan.moves_to is not None:
            target_group, target_meeting = plan.moves_to
            new_joined = meetings[target_group][target_meeting]
            new_row = SmallGroupMember.for_group(
                groups[target_group], guest_id=guest.id, joined_at=new_joined
            )
            session.add(new_row)
            periods.append(_Period(guest, plan, groups[target_group], new_joined, None))
    session.flush()
    return periods


def _seed_reports(
    ctx: SeedContext,
    groups: list[SmallGroup],
    meetings: list[list[date]],
    leaders: list[Member],
    periods: list[_Period],
) -> None:
    rng, session, today = ctx.rng, ctx.session, ctx.today
    # Who a guest group's report can tag from another group: members in a member group today.
    others: list[PersonKey] = sorted(
        ("member", member_id)
        for member_id in session.scalars(
            select(SmallGroupMember.member_id)
            .distinct()
            .join(SmallGroup, SmallGroup.id == SmallGroupMember.small_group_id)
            .where(
                SmallGroupMember.left_at.is_(None),
                SmallGroupMember.member_id.is_not(None),
                SmallGroup.audience == GroupAudience.MEMBERS,
            )
        )
        if member_id is not None
    )
    for group_index, group in enumerate(groups):
        member_rows = list(
            session.scalars(
                select(SmallGroupMember).where(
                    SmallGroupMember.small_group_id == group.id, SmallGroupMember.member_id.is_not(None)
                )
            )
        )
        group_periods = [p for p in periods if p.group is group]
        for index, meeting_date in enumerate(meetings[group_index]):
            submitter = leaders[group_index]
            submitted_at = min(
                datetime.combine(meeting_date, time(21, 0), MANAGUA_TZ) + timedelta(hours=rng.randint(0, 40)),
                datetime.combine(today, time(8, 0), MANAGUA_TZ),
            )
            report = SmallGroupReport(
                small_group=group,
                meeting_date=meeting_date,
                address=group.meeting_address,
                submitted_by_member_id=submitter.id,
                submitted_at=submitted_at,
            )
            # Drawn here, in the order they always were, so the shared RNG's sequence doesn't change.
            prayer = rng.choice(fixtures.GROUP_PRAYER_REQUESTS)
            praise = rng.choice(fixtures.GROUP_PRAISE_REPORTS) if rng.random() < 0.7 else None
            follow_up = rng.choice(fixtures.GROUP_DISCUSSIONS) if rng.random() < 0.4 else None
            for member_row in member_rows:
                attended = member_row.member_id == submitter.id or rng.random() < MEMBER_ATTENDANCE_RATE
                report.attendances.append(
                    SmallGroupReportAttendance(
                        member_id=member_row.member_id,
                        attended_group=attended,
                        attended_church=rng.random() < MEMBER_CHURCH_RATE,
                    )
                )
            for period in group_periods:
                # Roster rule: active on the date, the end date included (the stop is filed on it).
                if not (
                    period.joined_at <= meeting_date
                    and (period.left_at is None or period.left_at >= meeting_date)
                ):
                    continue
                attended_group = _guest_attended(rng.random(), period, index, len(meetings[group_index]))
                report.attendances.append(
                    SmallGroupReportAttendance(
                        guest_id=period.guest.id,
                        attended_group=attended_group,
                        attended_church=rng.random() < ATTENDED_CHURCH_RATE,
                        observation=(
                            rng.choice(fixtures.ABSENCE_OBSERVATIONS)
                            if not attended_group and rng.random() < 0.4
                            else None
                        ),
                    )
                )
            # Guest groups' reports mostly tag the guests on them (they're most of the list).
            add_report_items(
                session,
                report,
                group.name,
                prayer=prayer,
                praise=praise,
                follow_up=follow_up,
                roster=[person_key(a.member_id, a.guest_id) for a in report.attendances],
                others=others,
            )
            session.add(report)
    session.flush()


def _guest_attended(roll: float, period: _Period, meeting: int, meeting_count: int) -> bool:
    attendance = period.plan.attendance
    if isinstance(attendance, int):
        return meeting < meeting_count - attendance
    if period.plan.stopped_at_meeting == meeting:
        return False  # the meeting they were marked as stopped coming on
    return roll < STEADY_ATTENDANCE_RATE


def _email(name: str) -> str:
    given, *surnames = name.split()
    return f"{_ascii(given)}.{_ascii(surnames[0])}@example.com"
