from datetime import date
from enum import StrEnum

from sqlalchemy import Date, Enum, Identity, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from membership_management.data.database import MemberManagementBase


class MemberSex(StrEnum):
    MALE = "male"
    FEMALE = "female"


class Member(MemberManagementBase):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[str | None] = mapped_column(String(255))
    birth_date: Mapped[date | None] = mapped_column(Date)
    # VARCHAR + CHECK rather than a native Postgres ENUM, like small_group_members.role.
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

    # ID of the linked user, managed by the separate better-auth service (auth-server).
    user_id: Mapped[str | None] = mapped_column(String(255), unique=True)

    # Temporary while we migrate data from the SQL Server DB.
    legacy_id: Mapped[int | None] = mapped_column(unique=True)


# Email is unique ignoring case (A@x.com and a@x.com are one address); the casing people typed is
# kept as stored. Any lookup by email must compare lower(email) so it can use this index.
Index("uq_members_email_lower", func.lower(Member.email), unique=True)
