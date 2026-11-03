"""add report status and drafts

Revision ID: b7d2c4a91e30
Revises: f4752a0af387
Create Date: 2026-11-02 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d2c4a91e30"
down_revision: str | Sequence[str] | None = "f4752a0af387"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Every existing report becomes `submitted`, started by its submitter at its submission time."""
    op.add_column(
        "small_group_reports", sa.Column("status", sa.Text(), server_default="submitted", nullable=False)
    )
    op.add_column(
        "small_group_reports", sa.Column("version", sa.Integer(), server_default="1", nullable=False)
    )
    op.add_column("small_group_reports", sa.Column("started_by_member_id", sa.Integer(), nullable=True))
    op.add_column(
        "small_group_reports",
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.add_column("small_group_reports", sa.Column("last_edited_by_member_id", sa.Integer(), nullable=True))
    op.add_column(
        "small_group_reports", sa.Column("last_edited_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.execute(
        "UPDATE small_group_reports "
        "SET started_by_member_id = submitted_by_member_id, started_at = submitted_at"
    )

    op.alter_column("small_group_reports", "started_by_member_id", nullable=False)
    op.alter_column(
        "small_group_reports", "submitted_by_member_id", existing_type=sa.Integer(), nullable=True
    )
    op.alter_column(
        "small_group_reports",
        "submitted_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
        server_default=None,
    )
    op.create_index(
        op.f("ix_small_group_reports_started_by_member_id"), "small_group_reports", ["started_by_member_id"]
    )
    op.create_foreign_key(
        op.f("fk_small_group_reports_started_by_member_id_members"),
        "small_group_reports",
        "members",
        ["started_by_member_id"],
        ["id"],
    )
    op.create_foreign_key(
        op.f("fk_small_group_reports_last_edited_by_member_id_members"),
        "small_group_reports",
        "members",
        ["last_edited_by_member_id"],
        ["id"],
    )
    op.create_check_constraint("status_valid", "small_group_reports", "status IN ('draft', 'submitted')")
    op.create_check_constraint(
        "submitted_by_unless_draft",
        "small_group_reports",
        "(status = 'draft') = (submitted_by_member_id IS NULL)",
    )
    op.create_check_constraint(
        "submitted_at_unless_draft", "small_group_reports", "(status = 'draft') = (submitted_at IS NULL)"
    )
    op.create_check_constraint(
        "no_meeting_never_draft", "small_group_reports", "held OR status = 'submitted'"
    )

    op.alter_column(
        "small_group_report_attendances", "attended_group", existing_type=sa.Boolean(), nullable=True
    )
    op.alter_column(
        "small_group_report_attendances", "attended_church", existing_type=sa.Boolean(), nullable=True
    )


def downgrade() -> None:
    """Refuses while a draft exists: its null answers and null submitter have no place in the old shape."""
    drafts = op.get_bind().scalar(sa.text("SELECT count(*) FROM small_group_reports WHERE status = 'draft'"))
    if drafts:
        raise RuntimeError(f"{drafts} draft report(s) exist: submit or discard them before downgrading.")

    op.alter_column(
        "small_group_report_attendances", "attended_church", existing_type=sa.Boolean(), nullable=False
    )
    op.alter_column(
        "small_group_report_attendances", "attended_group", existing_type=sa.Boolean(), nullable=False
    )

    op.drop_constraint(
        op.f("ck_small_group_reports_no_meeting_never_draft"), "small_group_reports", type_="check"
    )
    op.drop_constraint(
        op.f("ck_small_group_reports_submitted_at_unless_draft"), "small_group_reports", type_="check"
    )
    op.drop_constraint(
        op.f("ck_small_group_reports_submitted_by_unless_draft"), "small_group_reports", type_="check"
    )
    op.drop_constraint(op.f("ck_small_group_reports_status_valid"), "small_group_reports", type_="check")
    op.drop_constraint(
        op.f("fk_small_group_reports_last_edited_by_member_id_members"),
        "small_group_reports",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_small_group_reports_started_by_member_id_members"), "small_group_reports", type_="foreignkey"
    )
    op.drop_index(op.f("ix_small_group_reports_started_by_member_id"), table_name="small_group_reports")
    op.alter_column(
        "small_group_reports",
        "submitted_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
    op.alter_column(
        "small_group_reports", "submitted_by_member_id", existing_type=sa.Integer(), nullable=False
    )
    op.drop_column("small_group_reports", "last_edited_at")
    op.drop_column("small_group_reports", "last_edited_by_member_id")
    op.drop_column("small_group_reports", "started_at")
    op.drop_column("small_group_reports", "started_by_member_id")
    op.drop_column("small_group_reports", "version")
    op.drop_column("small_group_reports", "status")
