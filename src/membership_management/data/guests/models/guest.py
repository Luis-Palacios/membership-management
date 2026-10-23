from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Identity, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from membership_management.data.database import MemberManagementBase
from membership_management.data.members.models import MemberSex

if TYPE_CHECKING:
    from membership_management.data.members.models import Member


class Guest(MemberManagementBase):
    """Someone who isn't a member (yet) and takes part in guest small groups.

    Never mixed into `members` (guest-small-groups spec, rule 2): no user account, no profile. Email
    isn't unique, since families share phones and emails; duplicates are caught by search instead.
    """

    __tablename__ = "guests"
    __table_args__ = (
        # Search (`GET /guests/search`, the list's `q`) matches substrings, so these are trigram GIN
        # indexes, not btrees. `guest_search_text` is the migration's IMMUTABLE wrapper around
        # lower(unaccent(...)): unaccent() itself is only STABLE, which Postgres refuses in an index.
        # Queries must use the same expressions to hit them.
        Index(
            "ix_guests_name_search",
            text("guest_search_text(name) gin_trgm_ops"),
            postgresql_using="gin",
        ),
        Index(
            "ix_guests_phone_digits",
            text("regexp_replace(phone, '\\D', '', 'g') gin_trgm_ops"),
            postgresql_using="gin",
        ),
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))
    # Same VARCHAR + CHECK as members.sex.
    sex: Mapped[MemberSex | None] = mapped_column(
        Enum(
            MemberSex,
            native_enum=False,
            create_constraint=True,
            length=10,
            name="sex",
            values_callable=lambda values: [v.value for v in values],
        ),
    )
    address: Mapped[str | None] = mapped_column(String(255))
    first_visit_date: Mapped[date | None] = mapped_column(Date)
    invited_by_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), index=True)
    # Null when the creator has no linked member (an unlinked admin or elder can create guests).
    created_by_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Points to the assimilation DB's Persona.Id_Persona, like members.legacy_id. This feature never
    # sets it: importing is a separate scope.
    legacy_id: Mapped[int | None] = mapped_column(unique=True)

    invited_by: Mapped["Member | None"] = relationship(foreign_keys=[invited_by_member_id])
    created_by: Mapped["Member | None"] = relationship(foreign_keys=[created_by_member_id])

    def __repr__(self) -> str:
        return f"<Guest(id={self.id}, name={self.name})>"
