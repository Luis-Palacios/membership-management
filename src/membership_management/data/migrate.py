"""Apply all pending migrations: `python -m membership_management.data.migrate`.

For deployments, where the image holds only the installed venv (no alembic.ini). Locally, use
`uv run alembic ...` from the repo root instead.
"""

import logging

from alembic import command
from alembic.config import Config


def main() -> None:
    # env.py only configures logging from alembic.ini, which doesn't exist here; without this,
    # nothing about which revisions ran would reach CloudWatch.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    config = Config()
    config.set_main_option("script_location", "membership_management.data:migrations")
    command.upgrade(config, "head")


if __name__ == "__main__":
    main()