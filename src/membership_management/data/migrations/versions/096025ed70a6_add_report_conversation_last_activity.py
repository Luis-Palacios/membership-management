"""add report conversation last activity

Revision ID: 096025ed70a6
Revises: b7d2c4a91e30
Create Date: 2026-11-05 18:53:11.906863

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "096025ed70a6"
down_revision: str | Sequence[str] | None = "b7d2c4a91e30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """`last_activity_at` (report conversations rule 17): the newest comment's time, deleted ones included.

    Added nullable, backfilled, then made NOT NULL. A thread with no comment rows (the code never
    creates one) falls back to `last_comment_at`. No server default: every insert sets it.
    """
    op.add_column(
        "report_conversations", sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        "UPDATE report_conversations SET last_activity_at = coalesce("
        "(SELECT max(c.created_at) FROM report_conversation_comments c"
        " WHERE c.conversation_id = report_conversations.id), last_comment_at)"
    )
    op.alter_column(
        "report_conversations", "last_activity_at", existing_type=sa.DateTime(timezone=True), nullable=False
    )


def downgrade() -> None:
    op.drop_column("report_conversations", "last_activity_at")
