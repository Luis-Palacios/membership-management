"""Items of seeded reports: the texts the report seeders draw become untagged items, and extra items tag
people, written through the service's own validation."""

import random
from collections.abc import Sequence

from sqlalchemy.orm import Session

from membership_management.data.seed import fixtures
from membership_management.data.small_groups.models import ReportSection, SmallGroupReport
from membership_management.data.small_groups.report_items import PersonSegment, Segment, TextSegment
from membership_management.data.small_groups.results import PersonKey
from membership_management.data.small_groups.services import set_new_report_items

# Share of tagged items about someone from another group; the rest tag someone on the report.
OTHER_GROUP_TAG_RATE = 0.25
# Chance the follow-up point names someone instead of being about the group.
TAGGED_FOLLOW_UP_RATE = 0.5


def add_report_items(
    session: Session,
    report: SmallGroupReport,
    group_name: str,
    *,
    prayer: str,
    praise: str | None,
    follow_up: str | None,
    roster: Sequence[PersonKey],
    others: Sequence[PersonKey],
) -> None:
    """1-3 prayer items, 0-2 praise, 0-1 follow-up; about half tag one person.

    `prayer`, `praise` and `follow_up` are the texts the caller drew from its own RNG, which keeps its
    sequence (and every other seeded row) as it was. The extra items use an RNG seeded by group and
    date, so a run is still deterministic.
    """
    rng = random.Random(f"report-items:{group_name}:{report.meeting_date.isoformat()}")  # noqa: S311 -- test data

    def tagged(templates: Sequence[str], count: int) -> list[list[Segment]]:
        return [_with_person(t, _pick(rng, roster, others)) for t in rng.sample(templates, count)]

    praise_items = [_text(praise)] if praise is not None else []
    praise_items += tagged(fixtures.TAGGED_PRAISE_REPORTS, rng.randint(0, 2 - len(praise_items)))
    follow_up_items: list[list[Segment]] = []
    if follow_up is not None:
        follow_up_items = (
            tagged(fixtures.TAGGED_DISCUSSIONS, 1)
            if rng.random() < TAGGED_FOLLOW_UP_RATE
            else [_text(follow_up)]
        )
    set_new_report_items(
        session,
        report,
        {
            ReportSection.PRAYER: [
                _text(prayer),
                *tagged(fixtures.TAGGED_PRAYER_REQUESTS, rng.randint(0, 2)),
            ],
            ReportSection.PRAISE: praise_items,
            ReportSection.FOLLOW_UP: follow_up_items,
        },
    )


def _pick(rng: random.Random, roster: Sequence[PersonKey], others: Sequence[PersonKey]) -> PersonKey:
    if others and rng.random() < OTHER_GROUP_TAG_RATE:
        return rng.choice(others)
    return rng.choice(roster)


def _text(text: str) -> list[Segment]:
    return [TextSegment(text)]


def _with_person(template: str, person: PersonKey) -> list[Segment]:
    before, after = template.split("{p}")
    return [TextSegment(before), PersonSegment(person), TextSegment(after)]
