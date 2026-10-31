from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from membership_management.data.guests.models import (
    Guest,
    GuestInactiveReason,
    GuestStatus,
    GuestStatusChange,
)
from membership_management.data.members.models import MemberSex
from membership_management.data.seed.context import MANAGUA_TZ, SeedContext
from membership_management.data.seed.members import _phone, managua_address
from membership_management.data.small_groups.models import (
    GroupAudience,
    LeftReason,
    SmallGroup,
    SmallGroupMember,
    SmallGroupReport,
    SmallGroupReportAttendance,
)

# Whoever recorded the changes: a made-up user id that no auth-server account matches.
CHANGED_BY = "seed-elder-1"
ATTENDED_RATE = 0.85
ATTENDED_CHURCH_RATE = 0.5


@dataclass
class _Change:
    """A status change, in days before today."""

    days_ago: int
    status: GuestStatus
    reason: GuestInactiveReason | None = None
    note: str | None = None
    # A deactivation closes the guest's open period on the day it's recorded; the date they left
    # (`effective_date`) can be earlier.
    left_days_before: int = 0


@dataclass
class _Period:
    """A period in the guest group, in days before today; `left_days_ago` None means still in it."""

    joined_days_ago: int
    left_days_ago: int | None
    left_reason: LeftReason | None = None


@dataclass
class _Plan:
    name: str
    sex: MemberSex
    # Days before today of the first visit.
    first_visit_days_ago: int
    changes: list[_Change]
    periods: list[_Period]


PLANS = [
    # Left a guest group when marked inactive.
    _Plan(
        name="Nubia Calero Herrera",
        sex=MemberSex.FEMALE,
        first_visit_days_ago=150,
        changes=[
            _Change(
                30,
                GuestStatus.INACTIVE,
                GuestInactiveReason.MOVED_AWAY,
                "Se mudó a Estelí con su familia.",
                left_days_before=10,
            ),
        ],
        periods=[_Period(150, 30, LeftReason.GUEST_INACTIVE)],
    ),
    # Visited once and was never in a group.
    _Plan(
        name="Óscar Guevara Núñez",
        sex=MemberSex.MALE,
        first_visit_days_ago=120,
        changes=[_Change(45, GuestStatus.INACTIVE, GuestInactiveReason.JOINED_ANOTHER_CHURCH)],
        periods=[],
    ),
    # Left and came back: active now, in a guest group again, with both kinds of status entry.
    _Plan(
        name="Sandra Mairena Rocha",
        sex=MemberSex.FEMALE,
        first_visit_days_ago=200,
        changes=[
            _Change(
                70,
                GuestStatus.INACTIVE,
                GuestInactiveReason.STOPPED_ATTENDING,
                "Dejó de venir por su horario de trabajo.",
                left_days_before=14,
            ),
            _Change(21, GuestStatus.ACTIVE, note="Cambió de turno y volvió a venir."),
        ],
        periods=[_Period(200, 70, LeftReason.GUEST_INACTIVE), _Period(21, None)],
    ),
]


def seed_inactive_guests(ctx: SeedContext) -> None:
    """Inactive guests and one who came back, with their history. They are extra rows (attendance lines
    included, in reports of the guest group they were in), so every other seeded row is unchanged."""
    session, rng, today = ctx.session, ctx.rng, ctx.today
    group = session.scalars(
        select(SmallGroup).where(SmallGroup.audience == GroupAudience.GUESTS).order_by(SmallGroup.id).limit(1)
    ).one()
    reports = list(
        session.scalars(
            select(SmallGroupReport)
            .where(SmallGroupReport.small_group_id == group.id, SmallGroupReport.held)
            .order_by(SmallGroupReport.meeting_date)
        )
    )
    for plan in PLANS:
        first_visit = today - timedelta(days=plan.first_visit_days_ago)
        guest = Guest(
            name=plan.name,
            phone=_phone(rng),
            sex=plan.sex,
            address=managua_address(rng),
            first_visit_date=first_visit,
            created_at=datetime.combine(first_visit, time(12, 0), MANAGUA_TZ),
        )
        session.add(guest)
        session.flush()

        for planned in plan.periods:
            joined_at = today - timedelta(days=planned.joined_days_ago)
            left_at = None if planned.left_days_ago is None else today - timedelta(days=planned.left_days_ago)
            period = SmallGroupMember.for_group(
                group, guest_id=guest.id, joined_at=joined_at, left_at=left_at
            )
            period.left_reason = planned.left_reason
            session.add(period)
            _add_attendance(ctx, guest, reports, joined_at, left_at)

        for change in plan.changes:
            recorded = datetime.combine(today - timedelta(days=change.days_ago), time(10, 0), MANAGUA_TZ)
            session.add(
                GuestStatusChange(
                    guest_id=guest.id,
                    status=change.status,
                    reason=change.reason,
                    effective_date=today - timedelta(days=change.days_ago + change.left_days_before),
                    note=change.note,
                    changed_by_user_id=CHANGED_BY,
                    created_at=recorded,
                )
            )
            guest.status, guest.status_changed_at = change.status, recorded
    session.flush()


def _add_attendance(
    ctx: SeedContext, guest: Guest, reports: list[SmallGroupReport], joined_at: date, left_at: date | None
) -> None:
    """A line in each report the period covers, as the roster rule would have put them on the list."""
    for report in reports:
        if joined_at <= report.meeting_date and (left_at is None or report.meeting_date <= left_at):
            report.attendances.append(
                SmallGroupReportAttendance(
                    guest_id=guest.id,
                    attended_group=ctx.rng.random() < ATTENDED_RATE,
                    attended_church=ctx.rng.random() < ATTENDED_CHURCH_RATE,
                )
            )
