"""make member email unique ignoring case

Revision ID: 5fd6f845810b
Revises: c2aef2b4f157
Create Date: 2026-10-15 09:40:18.300165

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5fd6f845810b"
down_revision: str | Sequence[str] | None = "c2aef2b4f157"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Fails if two existing members have emails differing only by case; fix those rows first.
    op.drop_constraint(op.f("uq_members_email"), "members", type_="unique")
    op.create_index("uq_members_email_lower", "members", [sa.literal_column("lower(email)")], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_members_email_lower", table_name="members")
    op.create_unique_constraint(
        op.f("uq_members_email"), "members", ["email"], postgresql_nulls_not_distinct=False
    )
