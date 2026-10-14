"""Seed the members DB: `uv run python -m membership_management.data.seed [--reset]`."""

import argparse
import sys
from datetime import date

from sqlalchemy import func, select

from membership_management.data.database import MemberManagementBase, MembershipSessionLocal
from membership_management.data.seed.runner import DEFAULT_RNG_SEED, SeedRefusedError, run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="truncate every members-DB table first")
    parser.add_argument("--rng-seed", type=int, default=DEFAULT_RNG_SEED, help="change to get different data")
    parser.add_argument(
        "--today", type=date.fromisoformat, default=None, help="pin the reference date (YYYY-MM-DD)"
    )
    args = parser.parse_args()

    with MembershipSessionLocal() as session:
        try:
            run(session, reset=args.reset, rng_seed=args.rng_seed, today=args.today)
        except SeedRefusedError as exc:
            sys.exit(str(exc))
        for table in MemberManagementBase.metadata.sorted_tables:
            print(f"{table.name}: {session.scalar(select(func.count()).select_from(table))}")


if __name__ == "__main__":
    main()
