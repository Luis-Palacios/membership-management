from dataclasses import dataclass
from datetime import datetime, time, timedelta

from sqlalchemy import select

from membership_management.data.members.models import (
    Member,
    MemberInactiveReason,
    MemberSex,
    MemberStatus,
    MemberStatusChange,
)
from membership_management.data.seed.context import MANAGUA_TZ, SeedContext
from membership_management.data.seed.members import _ascii, managua_address
from membership_management.data.small_groups.models import (
    GroupAudience,
    LeftReason,
    SmallGroup,
    SmallGroupMember,
    SmallGroupRole,
)

# Whoever recorded the changes: a made-up user id that no auth-server account matches.
CHANGED_BY = "seed-elder-1"


@dataclass
class _Change:
    """A status change, in days before today."""

    days_ago: int
    status: MemberStatus
    reason: MemberInactiveReason | None = None
    note: str | None = None
    # A deactivation closes the member's open periods on the day it's recorded; the date they left
    # (`effective_date`) can be earlier.
    left_days_before: int = 0


@dataclass
class _Plan:
    name: str
    sex: MemberSex
    # Linked to a user, as someone who could sign in would be.
    user_id: str | None
    changes: list[_Change]
    # Days before today each group period starts; one entry per deactivation, in order.
    periods_started: list[int]


PLANS = [
    # Left, came back and left again: the board's "left and came back" case.
    _Plan(
        name="Ernesto Ordóñez Zamora",
        sex=MemberSex.MALE,
        user_id="seed-user-inactive-1",
        changes=[
            _Change(
                300,
                MemberStatus.INACTIVE,
                MemberInactiveReason.MOVED_AWAY,
                "Se fue a Costa Rica por trabajo.",
            ),
            _Change(200, MemberStatus.ACTIVE, note="Regresó a Managua."),
            _Change(40, MemberStatus.INACTIVE, MemberInactiveReason.STOPPED_ATTENDING, left_days_before=25),
        ],
        periods_started=[700, 190],
    ),
    _Plan(
        name="Gioconda Palacios Rueda",
        sex=MemberSex.FEMALE,
        user_id=None,
        changes=[
            _Change(
                90,
                MemberStatus.INACTIVE,
                MemberInactiveReason.TRANSFERRED,
                "Se congrega ahora en una iglesia cerca de su nueva casa.",
                left_days_before=14,
            ),
        ],
        periods_started=[500],
    ),
    _Plan(
        name="Teodoro Selva Blandón",
        sex=MemberSex.MALE,
        user_id=None,
        changes=[_Change(20, MemberStatus.INACTIVE, MemberInactiveReason.DECEASED, left_days_before=2)],
        periods_started=[900],
    ),
]


def seed_inactive_members(ctx: SeedContext) -> None:
    """Three inactive members with their history. They are extra rows, so every other seeded row is
    unchanged."""
    session, rng, today = ctx.session, ctx.rng, ctx.today
    groups = list(
        session.scalars(
            select(SmallGroup).where(SmallGroup.audience == GroupAudience.MEMBERS).order_by(SmallGroup.id)
        )
    )
    for plan in PLANS:
        member = Member(
            name=plan.name,
            email=f"{_ascii(plan.name.split()[0])}.inactive@example.com",
            address=managua_address(rng),
            birth_date=today - timedelta(days=rng.randint(30 * 365, 75 * 365)),
            sex=plan.sex,
            user_id=plan.user_id,
        )
        session.add(member)
        session.flush()

        group = rng.choice(groups)
        deactivations = [c for c in plan.changes if c.status == MemberStatus.INACTIVE]
        for started, change in zip(plan.periods_started, deactivations, strict=True):
            period = SmallGroupMember.for_group(
                group,
                member_id=member.id,
                role=SmallGroupRole.MEMBER,
                joined_at=today - timedelta(days=started),
                left_at=today - timedelta(days=change.days_ago),
            )
            period.left_reason = LeftReason.MEMBER_INACTIVE
            session.add(period)

        for change in plan.changes:
            recorded = datetime.combine(today - timedelta(days=change.days_ago), time(10, 0), MANAGUA_TZ)
            session.add(
                MemberStatusChange(
                    member_id=member.id,
                    status=change.status,
                    reason=change.reason,
                    effective_date=today - timedelta(days=change.days_ago + change.left_days_before),
                    note=change.note,
                    changed_by_user_id=CHANGED_BY,
                    created_at=recorded,
                )
            )
            member.status, member.status_changed_at = change.status, recorded
    session.flush()
