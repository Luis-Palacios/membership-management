"""drop small group report legacy texts

Contract step of report tags: the items are the only copy of the three group texts. Upgrade drops
`group_prayer_request`, `group_praise_report` and `group_relevant_discussion` and narrows the
`not_held_has_no_texts` check to the address. Downgrade re-creates the columns and fills them from
the items (one per line, people by full name, cut at the old 1024-character width), so a rollback
keeps the content; sections with no items stay NULL.

Revision ID: ecbadacc8044
Revises: c19ca7f78d85
Create Date: 2026-10-28 13:38:07.278089

"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ecbadacc8044"
down_revision: str | Sequence[str] | None = "c19ca7f78d85"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Section key -> old text column.
_COLUMNS = {
    "prayer": "group_prayer_request",
    "praise": "group_praise_report",
    "followUp": "group_relevant_discussion",
}
_TOKEN = re.compile(r"@\{(member|guest):(\d+)\}")
_OLD_WIDTH = 1024
_NOT_HELD_CHECK = op.f("ck_small_group_reports_not_held_has_no_texts")


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(_NOT_HELD_CHECK, "small_group_reports", type_="check")
    for column in _COLUMNS.values():
        op.drop_column("small_group_reports", column)
    op.create_check_constraint(_NOT_HELD_CHECK, "small_group_reports", "held OR address IS NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(_NOT_HELD_CHECK, "small_group_reports", type_="check")
    for column in _COLUMNS.values():
        op.add_column("small_group_reports", sa.Column(column, sa.String(length=_OLD_WIDTH), nullable=True))
    _restore_texts()
    op.create_check_constraint(
        _NOT_HELD_CHECK,
        "small_group_reports",
        "held OR (address IS NULL AND group_prayer_request IS NULL"
        " AND group_praise_report IS NULL AND group_relevant_discussion IS NULL)",
    )


def _restore_texts() -> None:
    """Each report's items back into the old columns: one per line, tokens replaced by full names."""
    items = sa.table(
        "small_group_report_items",
        sa.column("report_id", sa.Integer),
        sa.column("section", sa.String),
        sa.column("position", sa.SmallInteger),
        sa.column("text", sa.Text),
    )
    members = sa.table("members", sa.column("id", sa.Integer), sa.column("name", sa.String))
    guests = sa.table("guests", sa.column("id", sa.Integer), sa.column("name", sa.String))
    bind = op.get_bind()
    names = {
        ("member", row.id): row.name for row in bind.execute(sa.select(members.c.id, members.c.name))
    } | {("guest", row.id): row.name for row in bind.execute(sa.select(guests.c.id, guests.c.name))}
    lines: dict[tuple[int, str], list[str]] = {}
    rows = bind.execute(
        sa.select(items.c.report_id, items.c.section, items.c.text).order_by(
            items.c.report_id, items.c.section, items.c.position
        )
    )
    for row in rows:
        text = _TOKEN.sub(lambda m: names.get((m.group(1), int(m.group(2))), ""), row.text)
        lines.setdefault((row.report_id, row.section), []).append(text)
    reports = sa.table("small_group_reports", sa.column("id", sa.Integer), *map(sa.column, _COLUMNS.values()))
    for (report_id, section), texts in lines.items():
        column = _COLUMNS[section]
        bind.execute(
            sa.update(reports)
            .where(reports.c.id == report_id)
            .values({column: "\n".join(texts)[:_OLD_WIDTH]})
        )
