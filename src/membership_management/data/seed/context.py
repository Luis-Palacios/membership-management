import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session


@dataclass
class SeedContext:
    session: Session
    # Seeded RNG: every run with the same seed and `today` produces identical data.
    rng: random.Random
    # Dates (joined_at, report meeting dates, ...) are generated relative to this.
    today: date


# A seeder adds rows through ctx.session and flushes; it never commits (the runner commits once,
# so a failure leaves the DB untouched). Later seeders read earlier seeders' rows from the session.
Seeder = Callable[[SeedContext], None]
