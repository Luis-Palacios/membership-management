import random
from datetime import date, timedelta

from sqlalchemy import select

from membership_management.data.members.models import Member, MemberSex
from membership_management.data.seed import fixtures
from membership_management.data.seed.context import SeedContext
from membership_management.data.seed.members import managua_address
from membership_management.data.small_groups.models import SmallGroup, SmallGroupMember, SmallGroupRole

# Active members per group, leader and co-leader included.
GROUP_SIZE_RANGE = (8, 10)
# Members now in a group who used to be in another one (closed period in the old group).
TRANSFER_COUNT = 2
# Members not in any group now who used to be (a single closed period).
FORMER_MEMBER_COUNT = 2


def seed_small_groups(ctx: SeedContext) -> None:
    rng, today = ctx.rng, ctx.today
    members = list(ctx.session.scalars(select(Member).order_by(Member.id)))
    rng.shuffle(members)
    # Seed data only: leaders and co-leaders are always men (members with a known male sex).
    men = [m for m in members if m.sex == MemberSex.MALE]
    # Every group's leaders are picked before any regulars, or an earlier group could take as a
    # regular a man a later group then picks as its leader.
    leaders = [(men.pop(), men.pop()) for _ in fixtures.SMALL_GROUPS]
    for leader, co_leader in leaders:
        members.remove(leader)
        members.remove(co_leader)

    groups: list[tuple[SmallGroup, date]] = []
    current_rows: list[SmallGroupMember] = []
    for (name, neighborhood, meeting_day), (leader, co_leader) in zip(
        fixtures.SMALL_GROUPS, leaders, strict=True
    ):
        size = rng.randint(*GROUP_SIZE_RANGE)
        regulars = [members.pop() for _ in range(size - 2)]
        started = today - timedelta(days=rng.randint(400, 1100))
        # The group meets at the leader's home, so move the leader into the group's neighborhood.
        leader.address = managua_address(rng, neighborhood)
        group = SmallGroup(name=name, meeting_address=leader.address, meeting_day=meeting_day)
        ctx.session.add(group)
        groups.append((group, started))

        _add(ctx, group, leader, SmallGroupRole.LEADER, started)
        # The co-leader was a regular member first, then promoted: two periods, as the API records it.
        co_joined = _between(rng, started, today - timedelta(days=200))
        promoted = _between(rng, co_joined + timedelta(days=60), today - timedelta(days=90))
        _add(ctx, group, co_leader, SmallGroupRole.MEMBER, co_joined, left_at=promoted)
        current_rows.append(_add(ctx, group, co_leader, SmallGroupRole.CO_LEADER, promoted))
        for member in regulars:
            current_rows.append(
                _add(
                    ctx,
                    group,
                    member,
                    SmallGroupRole.MEMBER,
                    _between(rng, started, today - timedelta(days=1)),
                )
            )

    # Whoever is left in `members` belongs to no group; a few of them used to.
    for member in members[:FORMER_MEMBER_COUNT]:
        group, started = rng.choice(groups)
        joined = _between(rng, started, today - timedelta(days=120))
        _add(ctx, group, member, SmallGroupRole.MEMBER, joined, left_at=_between(rng, joined, today))

    transfers = 0
    for row in rng.sample(current_rows, len(current_rows)):
        if transfers == TRANSFER_COUNT:
            break
        other_group, other_started = rng.choice([g for g in groups if g[0] is not row.small_group])
        if row.joined_at - other_started < timedelta(days=60):
            continue
        joined = _between(rng, other_started, row.joined_at - timedelta(days=30))
        _add(ctx, other_group, row.member, SmallGroupRole.MEMBER, joined, left_at=row.joined_at)
        transfers += 1

    ctx.session.flush()


def _add(
    ctx: SeedContext,
    group: SmallGroup,
    member: Member,
    role: SmallGroupRole,
    joined_at: date,
    left_at: date | None = None,
) -> SmallGroupMember:
    row = SmallGroupMember(small_group=group, member=member, role=role, joined_at=joined_at, left_at=left_at)
    ctx.session.add(row)
    return row


def _between(rng: random.Random, start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, max((end - start).days, 0)))
