"""add care log entry notes

Revision ID: 5b8e2d7a1c94
Revises: 329e2849ed61
Create Date: 2026-11-25 15:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5b8e2d7a1c94"
down_revision: str | Sequence[str] | None = "329e2849ed61"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "care_log_entry_notes",
        sa.Column("id", sa.Integer(), sa.Identity(always=True), nullable=False),
        sa.Column("entry_id", sa.Integer(), nullable=False),
        sa.Column("author_user_id", sa.String(), nullable=False),
        sa.Column("author_member_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "char_length(text) BETWEEN 1 AND 4000", name=op.f("ck_care_log_entry_notes_text_length")
        ),
        sa.ForeignKeyConstraint(
            ["author_member_id"],
            ["members.id"],
            name=op.f("fk_care_log_entry_notes_author_member_id_members"),
        ),
        sa.ForeignKeyConstraint(
            ["entry_id"],
            ["care_log_entries.id"],
            name=op.f("fk_care_log_entry_notes_entry_id_care_log_entries"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_care_log_entry_notes")),
    )
    op.create_index(
        op.f("ix_care_log_entry_notes_author_member_id"),
        "care_log_entry_notes",
        ["author_member_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_care_log_entry_notes_entry_id"), "care_log_entry_notes", ["entry_id"], unique=False
    )
    op.create_index(
        "uq_care_log_entry_notes_entry_id_author_member_id",
        "care_log_entry_notes",
        ["entry_id", "author_member_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "care_log_entry_note_revisions",
        sa.Column("id", sa.Integer(), sa.Identity(always=True), nullable=False),
        sa.Column("note_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["note_id"],
            ["care_log_entry_notes.id"],
            name=op.f("fk_care_log_entry_note_revisions_note_id_care_log_entry_notes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_care_log_entry_note_revisions")),
    )
    op.create_index(
        op.f("ix_care_log_entry_note_revisions_note_id"),
        "care_log_entry_note_revisions",
        ["note_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_care_log_entry_note_revisions_note_id"), table_name="care_log_entry_note_revisions"
    )
    op.drop_table("care_log_entry_note_revisions")
    op.drop_index(
        "uq_care_log_entry_notes_entry_id_author_member_id",
        table_name="care_log_entry_notes",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index(op.f("ix_care_log_entry_notes_entry_id"), table_name="care_log_entry_notes")
    op.drop_index(op.f("ix_care_log_entry_notes_author_member_id"), table_name="care_log_entry_notes")
    op.drop_table("care_log_entry_notes")
