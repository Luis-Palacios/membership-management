"""enable unaccent extension

Revision ID: a7c3e91d2b46
Revises: f93bcf4485fd
Create Date: 2026-10-19 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c3e91d2b46"
down_revision: str | Sequence[str] | None = "f93bcf4485fd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # For the accent-insensitive member search. Trusted since PG 13, so the migrating user
    # (the DB owner; on RDS also rds_superuser) can create it; the app user only needs to call it.
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP EXTENSION IF EXISTS unaccent")
