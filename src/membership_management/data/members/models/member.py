from sqlalchemy.orm import Mapped, mapped_column

from membership_management.data.database import MemberManagementBase


class Member(MemberManagementBase):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(nullable=False)
    email: Mapped[str] = mapped_column(unique=True, nullable=False)
    phone: Mapped[str] = mapped_column(unique=False, nullable=True)
    address: Mapped[str] = mapped_column(nullable=True)

    
    """
    The ID of the user associated with this member.
    handled by separated better-auth service (auth-server)
    """
    user_id: Mapped[str] = mapped_column(nullable=True)

    # Temporal while we migrate data from the SQL Server DB
    legacy_id: Mapped[int] = mapped_column(nullable=True)