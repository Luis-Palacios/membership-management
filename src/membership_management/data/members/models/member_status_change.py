from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, ForeignKey, Identity, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from membership_management.data.database import MemberManagementBase
from membership_management.data.members.models.member import MemberStatus


class MemberInactiveReason(StrEnum):
    """Why a member was marked inactive (inactive-members spec, rule 3). Required to deactivate, none
    on reactivation. No reason gets special handling; they exist for filtering and reporting."""

    MOVED_AWAY = "moved_away"
    TRANSFERRED = "transferred"
    STOPPED_ATTENDING = "stopped_attending"
    CHURCH_DISCIPLINE = "church_discipline"
    DECEASED = "deceased"
    OTHER = "other"


class MemberStatusChange(MemberManagementBase):
    """One change of a member's status. Append-only: rows are never updated or deleted."""

    __tablename__ = "member_status_changes"
    __table_args__ = (
        # A reason goes with every deactivation and with nothing else.
        CheckConstraint("(status = 'inactive') = (reason IS NOT NULL)", name="reason_iff_inactive"),
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    # The status the member changed TO.
    status: Mapped[MemberStatus] = mapped_column(
        Enum(
            MemberStatus,
            native_enum=False,
            create_constraint=True,
            length=10,
            name="status",
            values_callable=lambda values: [v.value for v in values],
        ),
    )
    reason: Mapped[MemberInactiveReason | None] = mapped_column(
        Enum(
            MemberInactiveReason,
            native_enum=False,
            create_constraint=True,
            length=20,
            name="reason",
            values_callable=lambda values: [v.value for v in values],
        ),
    )
    # The date the person left, which can be earlier than the day it was recorded (rule 6); today on
    # reactivation. Informational: it never moves a group period's `left_at`.
    effective_date: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    # JWT `sub` of whoever did it. A plain string: auth-server's users live in another database.
    changed_by_user_id: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# A member's history, newest first.
Index(
    "ix_member_status_changes_member_id_created_at",
    MemberStatusChange.member_id,
    MemberStatusChange.created_at.desc(),
)
