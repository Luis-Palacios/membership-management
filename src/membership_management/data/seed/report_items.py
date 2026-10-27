"""Items of seeded reports: the texts the report seeders draw become untagged items, and extra items tag
people, written through the service's own validation."""

import random
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from membership_management.data.guests.models import Guest
from membership_management.data.seed import fixtures
from membership_management.data.seed.context import SeedContext
from membership_management.data.small_groups.models import (
    GroupAudience,
    ReportSection,
    SmallGroup,
    SmallGroupReport,
)
from membership_management.data.small_groups.report_items import PersonSegment, Segment, TextSegment
from membership_management.data.small_groups.results import PersonKey
from membership_management.data.small_groups.services import report_item_views, set_new_report_items

# Share of tagged items about someone from another group; the rest tag someone on the report.
OTHER_GROUP_TAG_RATE = 0.25
# Chance the follow-up point names someone instead of being about the group.
TAGGED_FOLLOW_UP_RATE = 0.5
# Every Nth held report of a member group also mentions a guest (someone the group invited or met).
GUEST_TAG_EVERY = 3


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


def seed_guest_tags_in_member_reports(ctx: SeedContext) -> None:
    """Every third held report of a member group gets one more prayer or praise item tagging a guest.

    Member groups' reports are seeded before the guests exist, so this runs after `seed_guests`: it
    gives a guest's timeline rows from reports of groups that aren't theirs. The guests go round in id
    order, so each is tagged at least once. No shared RNG draws, so the other seeded rows are the same
    (only these reports' items are rewritten, and get new ids).
    """
    session = ctx.session
    guests = list(session.scalars(select(Guest.id).order_by(Guest.id)))
    if not guests:
        return
    reports = session.scalars(
        select(SmallGroupReport)
        .join(SmallGroup, SmallGroup.id == SmallGroupReport.small_group_id)
        .where(SmallGroup.audience == GroupAudience.MEMBERS, SmallGroupReport.held)
        .order_by(SmallGroupReport.small_group_id, SmallGroupReport.meeting_date)
    ).all()
    for index, report in enumerate(reports[::GUEST_TAG_EVERY]):
        rng = random.Random(f"guest-tag:{report.small_group_id}:{report.meeting_date.isoformat()}")  # noqa: S311 -- test data
        section = rng.choice([ReportSection.PRAYER, ReportSection.PRAISE])
        templates = (
            fixtures.TAGGED_PRAYER_REQUESTS
            if section == ReportSection.PRAYER
            else fixtures.TAGGED_PRAISE_REPORTS
        )
        guest: PersonKey = ("guest", guests[index % len(guests)])
        existing = report_item_views(session, frozenset({report.id})).get(report.id, [])
        sections: dict[ReportSection, list[list[Segment]]] = {s: [] for s in ReportSection}
        for item in existing:
            sections[item.section].append(item.segments)
        sections[section].append(_with_person(rng.choice(templates), guest))
        # The unit of work would insert the new items before deleting the old and trip the positions.
        report.items = []
        session.flush()
        set_new_report_items(session, report, sections)
    session.flush()
