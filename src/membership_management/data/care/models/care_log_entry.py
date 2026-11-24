from datetime import date, datetime, time
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    Time,
    desc,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from membership_management.data.database import MemberManagementBase
from membership_management.data.small_groups.models.report_conversation import ReportSection

if TYPE_CHECKING:
    from membership_management.data.care.models.care_log_entry_participant import CareLogEntryParticipant
    from membership_management.data.care.models.care_log_entry_person import CareLogEntryPerson
    from membership_management.data.care.models.care_log_entry_revision import CareLogEntryRevision
    from membership_management.data.members.models import Member


class CareLogKind(StrEnum):
    """What was recorded (care spec, rule 1)."""

    CALL = "call"
    MESSAGE = "message"
    MEETING = "meeting"
    VISIT = "visit"
    HEARD = "heard"
    NOTE = "note"


class CareLogStatus(StrEnum):
    DONE = "done"
    PLANNED = "planned"
    CANCELLED = "cancelled"


class MeetingMode(StrEnum):
    IN_PERSON = "in_person"
    ONLINE = "online"


class CareLogVisibility(StrEnum):
    """Who sees an entry that isn't inside a care (rule 8)."""

    LEADERS = "leaders"
    PRIVATE = "private"


class CareLogSourceKind(StrEnum):
    """What an entry was logged from (rule 12)."""

    ATTENDANCE = "attendance"
    SECTION = "section"
    CONVERSATION = "conversation"


# Kinds that may be planned (rule 6); the others are always done.
PLANNABLE_KINDS = frozenset({CareLogKind.CALL, CareLogKind.MEETING, CareLogKind.VISIT})


def _enum(enum: type[StrEnum], name: str, length: int) -> Enum:
    return Enum(
        enum,
        native_enum=False,
        create_constraint=True,
        length=length,
        name=name,
        values_callable=lambda values: [v.value for v in values],
    )


class CareLogEntry(MemberManagementBase):
    """One recorded or planned event of care about one or more people (care spec, Part 1).

    `user_id` columns are JWT `sub`s of auth-server users: strings with no foreign key. The source
    columns say what the entry was logged from; after the report, item or thread is deleted the kind
    stays and the ids go null, so the API can say the source is gone. `text` is kept after a soft
    delete but never returned again; earlier texts are in `care_log_entry_revisions`.
    """

    __tablename__ = "care_log_entries"
    __table_args__ = (
        CheckConstraint("kind IN ('call', 'meeting', 'visit') OR status = 'done'", name="plan_kinds"),
        # A plan may have no purpose, and cancelling it keeps it that way.
        CheckConstraint("status <> 'done' OR text IS NOT NULL", name="text_when_done"),
        CheckConstraint("(kind = 'meeting') = (meeting_mode IS NOT NULL)", name="meeting_mode_iff_meeting"),
        CheckConstraint("kind = 'heard' OR heard_from IS NULL", name="heard_from_only_when_heard"),
        CheckConstraint("char_length(heard_from) <= 200", name="heard_from_length"),
        CheckConstraint("char_length(others) <= 200", name="others_length"),
        CheckConstraint("char_length(cancel_reason) <= 500", name="cancel_reason_length"),
        CheckConstraint("char_length(text) BETWEEN 1 AND 4000", name="text_length"),
        CheckConstraint("source_section IN ('prayer', 'praise', 'followUp')", name="source_section_valid"),
        # The report and conversation ids are the ones that go null when the source is deleted; the person
        # of an attendance row and the section of a section source have no cascade, so they stay and the
        # kind keeps saying what the entry came from.
        CheckConstraint(
            "(source_kind IS NULL AND source_report_id IS NULL AND source_member_id IS NULL"
            " AND source_guest_id IS NULL AND source_section IS NULL AND source_conversation_id IS NULL)"
            " OR (source_kind = 'attendance' AND source_section IS NULL AND source_conversation_id IS NULL"
            " AND num_nonnulls(source_member_id, source_guest_id) = 1)"
            " OR (source_kind = 'section' AND source_section IS NOT NULL AND source_member_id IS NULL"
            " AND source_guest_id IS NULL AND source_conversation_id IS NULL)"
            " OR (source_kind = 'conversation' AND source_report_id IS NULL AND source_member_id IS NULL"
            " AND source_guest_id IS NULL AND source_section IS NULL)",
            name="source_matches_kind",
        ),
        # Newest first for the lists; a partial "not deleted" index would only repeat it (deleted rows are
        # rare, and every timeline query also filters by person).
        Index("ix_care_log_entries_occurred_on_desc", desc("occurred_on")),
        Index(
            "ix_care_log_entries_author_user_id_status_occurred_on", "author_user_id", "status", "occurred_on"
        ),
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    kind: Mapped[CareLogKind] = mapped_column(_enum(CareLogKind, "kind", 16))
    status: Mapped[CareLogStatus] = mapped_column(_enum(CareLogStatus, "status", 16))
    meeting_mode: Mapped[MeetingMode | None] = mapped_column(_enum(MeetingMode, "meeting_mode", 16))
    # The church date (not UTC) of the event, planned or done.
    occurred_on: Mapped[date] = mapped_column(Date)
    occurred_at_time: Mapped[time | None] = mapped_column(Time)
    # Null only while planned (its purpose is optional); completing a plan sets it.
    text: Mapped[str | None] = mapped_column(Text)
    heard_from: Mapped[str | None] = mapped_column(String(200))
    others: Mapped[str | None] = mapped_column(String(200))
    # Null from stage 6 on for entries inside a care, which follow the care's audience (rule 9).
    visibility: Mapped[CareLogVisibility] = mapped_column(_enum(CareLogVisibility, "visibility", 16))
    author_user_id: Mapped[str] = mapped_column(String)
    # Always set: logging needs a linked member, and the member's name is what's shown.
    author_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)

    source_kind: Mapped[CareLogSourceKind | None] = mapped_column(_enum(CareLogSourceKind, "source_kind", 16))
    # Deleting the report or thread keeps the entry and nulls the link (rule 12). A report section is
    # anchored by report and section, never by item: a report edit rewrites every item.
    source_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("small_group_reports.id", ondelete="SET NULL"), index=True
    )
    source_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"))
    source_guest_id: Mapped[int | None] = mapped_column(ForeignKey("guests.id"))
    source_section: Mapped[ReportSection | None] = mapped_column(String(16))
    source_conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("report_conversations.id", ondelete="SET NULL"), index=True
    )

    cancel_reason: Mapped[str | None] = mapped_column(String(500))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    author: Mapped["Member"] = relationship(foreign_keys=[author_member_id])
    people: Mapped[list["CareLogEntryPerson"]] = relationship(
        back_populates="entry",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CareLogEntryPerson.id",
    )
    participants: Mapped[list["CareLogEntryParticipant"]] = relationship(
        back_populates="entry",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CareLogEntryParticipant.id",
    )
    revisions: Mapped[list["CareLogEntryRevision"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", passive_deletes=True
    )
