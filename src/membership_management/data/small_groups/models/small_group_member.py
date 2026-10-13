from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, Enum, ForeignKey, Identity, Index, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from membership_management.data.database import MemberManagementBase

if TYPE_CHECKING:
    from membership_management.data.members.models import Member
    from membership_management.data.small_groups.models.small_group import SmallGroup


class SmallGroupRole(StrEnum):
    MEMBER = "member"
    LEADER = "leader"
    CO_LEADER = "co_leader"


class SmallGroupMember(MemberManagementBase):
    """One period of someone's membership in a group, in one role.

    Leaving sets left_at; rejoining, or changing role (e.g. member -> leader), closes the current row
    and inserts a new one, so the full membership and leadership history is kept.
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
        CheckConstraint("left_at IS NULL OR left_at >= joined_at", name="left_after_joined"),
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    small_group_id: Mapped[int] = mapped_column(ForeignKey("small_groups.id"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
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

    member: Mapped["Member"] = relationship()
    small_group: Mapped["SmallGroup"] = relationship()
