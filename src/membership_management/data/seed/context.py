import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta, timezone

from sqlalchemy.orm import Session

# The demo church is in Managua (UTC-6, no daylight saving): `today` and every seeded time are
# Managua's, as the API's default CHURCH_TIMEZONE. Not read from the API's settings: the data layer
# doesn't import the api package.
MANAGUA_TZ = timezone(timedelta(hours=-6))


@dataclass
class SeedContext:
    session: Session
    # Seeded RNG: every run with the same seed and `today` produces identical data.
    rng: random.Random
    # Dates (joined_at, report meeting dates, ...) are generated relative to this; Managua's date.
    today: date


# A seeder adds rows through ctx.session and flushes; it never commits (the runner commits once,
# so a failure leaves the DB untouched). Later seeders read earlier seeders' rows from the session.
Seeder = Callable[[SeedContext], None]
