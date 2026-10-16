import random
import unicodedata
from datetime import date, timedelta

from membership_management.data.members.models import Member, MemberSex
from membership_management.data.seed import fixtures
from membership_management.data.seed.context import SeedContext

MEMBER_COUNT = 55
# Share of members with an email/phone on file; the rest are left null, as in real data.
EMAIL_RATE = 0.8
PHONE_RATE = 0.95
# Share of members with a sex on file.
SEX_RATE = 0.9


def seed_members(ctx: SeedContext) -> None:
    rng = ctx.rng
    names: set[str] = set()
    emails: set[str] = set()
    while len(names) < MEMBER_COUNT:
        female = rng.random() < 0.55
        given = rng.choice(fixtures.FEMALE_GIVEN_NAMES if female else fixtures.MALE_GIVEN_NAMES)
        first_surname, second_surname = rng.sample(fixtures.SURNAMES, 2)
        name = f"{given} {first_surname} {second_surname}"
        if name in names:
            continue
        names.add(name)
        ctx.session.add(
            Member(
                name=name,
                email=_unique_email(given, first_surname, emails) if rng.random() < EMAIL_RATE else None,
                phone=_phone(rng) if rng.random() < PHONE_RATE else None,
                address=managua_address(rng),
                birth_date=_birth_date(rng, ctx.today),
                sex=(MemberSex.FEMALE if female else MemberSex.MALE) if rng.random() < SEX_RATE else None,
            )
        )
    ctx.session.flush()


def managua_address(rng: random.Random, neighborhood: str | None = None) -> str:
    neighborhood = neighborhood or rng.choice(list(fixtures.NEIGHBORHOOD_LANDMARKS))
    landmark = rng.choice(fixtures.NEIGHBORHOOD_LANDMARKS[neighborhood])
    # Spanish contracts "de el" to "del".
    origin = f"del {landmark[3:]}" if landmark.startswith("el ") else f"de {landmark}"
    north_south = f"{rng.choice(fixtures.BLOCKS)} c. {rng.choice(fixtures.DIRECTIONS_NS)}"
    east_west = f"{rng.choice(fixtures.BLOCKS)} c. {rng.choice(fixtures.DIRECTIONS_EW)}"
    return f"{neighborhood}, {origin} {north_south}, {east_west}, casa #{rng.randint(1, 120)}, Managua"


def _unique_email(given: str, surname: str, taken: set[str]) -> str:
    # example.com (RFC 2606) never delivers, so nothing sent from a dev/demo DB reaches a real inbox.
    base = f"{_ascii(given.split()[0])}.{_ascii(surname)}"
    email, n = f"{base}@example.com", 2
    while email in taken:
        email, n = f"{base}{n}@example.com", n + 1
    taken.add(email)
    return email


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def _phone(rng: random.Random) -> str:
    digits = rng.choice(fixtures.MOBILE_PREFIXES) + "".join(str(rng.randint(0, 9)) for _ in range(7))
    return f"+505 {digits[:4]} {digits[4:]}"


def _birth_date(rng: random.Random, today: date) -> date:
    return today - timedelta(days=rng.randint(18 * 365, 78 * 365))
