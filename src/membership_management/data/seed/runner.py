import random
from datetime import UTC, date, datetime

from sqlalchemy import exists, select, text
from sqlalchemy.orm import Session

# Registers every model, so cross-domain relationship()s resolve and reset() sees every table.
import membership_management.data.models  # noqa: F401
from membership_management.data.config import settings
from membership_management.data.database import MemberManagementBase
from membership_management.data.seed.context import SeedContext, Seeder
from membership_management.data.seed.members import seed_members
from membership_management.data.seed.small_group_report_conversations import seed_report_conversations
from membership_management.data.seed.small_group_reports import seed_small_group_reports
from membership_management.data.seed.small_groups import seed_small_groups

# Run in this order: each seeder may read rows added by the ones before it.
SEEDERS: list[Seeder] = [
    seed_members,
    seed_small_groups,
    seed_small_group_reports,
    seed_report_conversations,
]

DEFAULT_RNG_SEED = 2026


class SeedRefusedError(Exception):
    """Seeding would touch a production DB or overwrite existing data."""


def run(
    session: Session, *, reset: bool = False, rng_seed: int = DEFAULT_RNG_SEED, today: date | None = None
) -> None:
    """Seed every table in one transaction; nothing is committed if any seeder fails."""
    if settings.environment == "production":
        raise SeedRefusedError("Refusing to seed a production database.")
    if reset:
        _truncate_all(session)
    elif _has_data(session):
        raise SeedRefusedError("The members DB already has data; pass --reset to wipe it first.")

    ctx = SeedContext(
        session=session,
        rng=random.Random(rng_seed),  # noqa: S311 -- reproducible test data, not crypto
        today=today or datetime.now(tz=UTC).date(),
    )
    for seeder in SEEDERS:
        seeder(ctx)
    session.commit()


def _truncate_all(session: Session) -> None:
    # Every table on the metadata, so new tables are covered automatically. alembic_version isn't
    # on it, so the migration state survives.
    tables = ", ".join(f'"{table.name}"' for table in MemberManagementBase.metadata.sorted_tables)
    session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


def _has_data(session: Session) -> bool:
    return any(
        session.scalar(select(exists().select_from(table)))
        for table in MemberManagementBase.metadata.sorted_tables
    )
