"""add report reminder runs

Revision ID: 7e1a4c9b2d58
Revises: b453135219c0
Create Date: 2026-11-23 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7e1a4c9b2d58"
down_revision: str | Sequence[str] | None = "b453135219c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "report_reminder_runs",
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column(
            "triggered_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("week_start", name=op.f("pk_report_reminder_runs")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("report_reminder_runs")
