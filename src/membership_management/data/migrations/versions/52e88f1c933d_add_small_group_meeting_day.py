"""add small group meeting day

Revision ID: 52e88f1c933d
Revises: b0b29b1995ef
Create Date: 2026-10-12 21:33:18.902394

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "52e88f1c933d"
down_revision: str | Sequence[str] | None = "b0b29b1995ef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("small_groups", sa.Column("meeting_day", sa.SmallInteger(), nullable=True))
    op.create_check_constraint(
        op.f("ck_small_groups_meeting_day_valid"), "small_groups", "meeting_day BETWEEN 1 AND 7"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f("ck_small_groups_meeting_day_valid"), "small_groups", type_="check")
    op.drop_column("small_groups", "meeting_day")
