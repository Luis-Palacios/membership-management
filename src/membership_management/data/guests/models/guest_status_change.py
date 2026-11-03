from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, ForeignKey, Identity, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from membership_management.data.database import MemberManagementBase
from membership_management.data.guests.models.guest import GuestStatus


class GuestInactiveReason(StrEnum):
    """Why a guest was marked inactive (inactive-guests spec, rule 3). Required to deactivate, none on
    reactivation. No reason gets special handling; they exist for filtering and reporting."""

    MOVED_AWAY = "moved_away"
    STOPPED_ATTENDING = "stopped_attending"
    JOINED_ANOTHER_CHURCH = "joined_another_church"
    DECEASED = "deceased"
    OTHER = "other"


class GuestStatusChange(MemberManagementBase):
    """One change of a guest's status. Append-only: rows are never updated or deleted."""

    __tablename__ = "guest_status_changes"
    __table_args__ = (
        # A reason goes with every deactivation and with nothing else.
        CheckConstraint("(status = 'inactive') = (reason IS NOT NULL)", name="reason_iff_inactive"),
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    guest_id: Mapped[int] = mapped_column(ForeignKey("guests.id"))
    # The status the guest changed TO.
    status: Mapped[GuestStatus] = mapped_column(
        Enum(
            GuestStatus,
            native_enum=False,
            create_constraint=True,
            length=10,
            name="status",
            values_callable=lambda values: [v.value for v in values],
        ),
    )
    reason: Mapped[GuestInactiveReason | None] = mapped_column(
        Enum(
            GuestInactiveReason,
            native_enum=False,
            create_constraint=True,
            length=30,
            name="reason",
            values_callable=lambda values: [v.value for v in values],
        ),
    )
    # The date the person left, which can be earlier than the day it was recorded (rule 3); today on
    # reactivation. Informational: it never moves a group period's `left_at`.
    effective_date: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    # JWT `sub` of whoever did it. A plain string: auth-server's users live in another database.
    changed_by_user_id: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# A guest's history, newest first.
Index(
    "ix_guest_status_changes_guest_id_created_at",
    GuestStatusChange.guest_id,
    GuestStatusChange.created_at.desc(),
)
