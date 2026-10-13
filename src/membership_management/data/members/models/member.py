from sqlalchemy import Identity, String
from sqlalchemy.orm import Mapped, mapped_column

from membership_management.data.database import MemberManagementBase


class Member(MemberManagementBase):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    phone: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[str | None] = mapped_column(String(255))

    # ID of the linked user, managed by the separate better-auth service (auth-server).
    user_id: Mapped[str | None] = mapped_column(String(255), unique=True)

    # Temporary while we migrate data from the SQL Server DB.
    legacy_id: Mapped[int | None] = mapped_column(unique=True)
