from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, Enum, ForeignKey, ForeignKeyConstraint, Identity, Index, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from membership_management.data.database import MemberManagementBase
from membership_management.data.small_groups.models.small_group import GroupAudience, SmallGroup

if TYPE_CHECKING:
    from membership_management.data.guests.models import Guest
    from membership_management.data.members.models import Member


class SmallGroupRole(StrEnum):
    MEMBER = "member"
    LEADER = "leader"
    CO_LEADER = "co_leader"


class LeftReason(StrEnum):
    """Why a period ended (guest-small-groups spec, rule 8). Null for role changes, group closes and
    history from before this existed. `moved_group` is only ever set by a move between guest groups."""

    STOPPED_COMING = "stopped_coming"
    MOVED_GROUP = "moved_group"
    OTHER = "other"


class SmallGroupMember(MemberManagementBase):
    """One period of someone's membership in a group, in one role.

    Leaving sets left_at; rejoining, or changing role (e.g. member -> leader), closes the current row
    and inserts a new one, so the full membership and leadership history is kept.

    The person is a member or a guest (exactly one of `member_id`, `guest_id`). Guests only exist in
    guest groups, as plain participants: `audience` copies the group's, and the composite foreign key
    to `small_groups (id, audience)` plus the checks below make the database refuse a guest in a member
    group, or as leader. Insert through `for_group` so `audience` is always set from the group.
    """

    __tablename__ = "small_group_members"
    __table_args__ = (
        # At most one *active* row per (group, member); closed periods can repeat.
        Index(
            "uq_small_group_members_active",
            "small_group_id",
            "member_id",
            unique=True,
            postgresql_where=text("left_at IS NULL"),
        ),
        # At most one active leader per group (co-leaders are unlimited).
        Index(
            "uq_small_group_members_active_leader",
            "small_group_id",
            unique=True,
            postgresql_where=text("left_at IS NULL AND role = 'leader'"),
        ),
        # One active guest group per guest, across all groups (rule 7). A move closes the old period
        # before opening the new one.
        Index(
            "uq_small_group_members_active_guest",
            "guest_id",
            unique=True,
            postgresql_where=text("left_at IS NULL"),
        ),
        CheckConstraint("left_at IS NULL OR left_at >= joined_at", name="left_after_joined"),
        CheckConstraint("num_nonnulls(member_id, guest_id) = 1", name="one_person"),
        CheckConstraint(
            "guest_id IS NULL OR (audience = 'guests' AND role = 'member')", name="guest_participant_only"
        ),
        ForeignKeyConstraint(
            ["small_group_id", "audience"],
            ["small_groups.id", "small_groups.audience"],
            name="fk_small_group_members_small_group_id_audience_small_groups",
        ),
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    small_group_id: Mapped[int] = mapped_column(ForeignKey("small_groups.id"), index=True)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), index=True)
    guest_id: Mapped[int | None] = mapped_column(ForeignKey("guests.id"), index=True)
    # Copy of the group's audience, here only so the composite foreign key can enforce the rules above.
    # No default: every insert states it (see for_group).
    audience: Mapped[GroupAudience] = mapped_column(
        Enum(
            GroupAudience,
            native_enum=False,
            create_constraint=False,
            length=10,
            name="audience",
            values_callable=lambda values: [v.value for v in values],
        ),
    )
    # VARCHAR + CHECK rather than a native Postgres ENUM type: adding a role later is a plain
    # constraint swap instead of ALTER TYPE. Autogenerate doesn't detect changes to the allowed
    # values either way, so a new role needs a hand-written migration.
    role: Mapped[SmallGroupRole] = mapped_column(
        Enum(
            SmallGroupRole,
            native_enum=False,
            create_constraint=True,
            length=20,
            name="role",
            values_callable=lambda roles: [role.value for role in roles],
        ),
        default=SmallGroupRole.MEMBER,
    )
    joined_at: Mapped[date] = mapped_column(Date)
    left_at: Mapped[date | None] = mapped_column(Date)
    left_reason: Mapped[LeftReason | None] = mapped_column(
        Enum(
            LeftReason,
            native_enum=False,
            create_constraint=True,
            length=20,
            name="left_reason",
            values_callable=lambda values: [v.value for v in values],
        ),
    )

    member: Mapped["Member | None"] = relationship()
    guest: Mapped["Guest | None"] = relationship()
    small_group: Mapped[SmallGroup] = relationship(foreign_keys=[small_group_id])

    @classmethod
    def for_group(
        cls,
        small_group: SmallGroup,
        *,
        member_id: int | None = None,
        guest_id: int | None = None,
        role: SmallGroupRole = SmallGroupRole.MEMBER,
        joined_at: date,
        left_at: date | None = None,
    ) -> "SmallGroupMember":
        """A new period in `small_group`, with `audience` taken from it. Every insert goes through here."""
        return cls(
            small_group=small_group,
            audience=small_group.audience,
            member_id=member_id,
            guest_id=guest_id,
            role=role,
            joined_at=joined_at,
            left_at=left_at,
        )
