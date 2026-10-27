"""Report items as the API sends and receives them: segments, with `viewable` decided by the caller."""

from collections.abc import Collection, Iterable, Sequence

from sqlalchemy.orm import Session

from membership_management.api.access import GuestScope, MemberScope, viewable_people
from membership_management.api.jwt_auth import AuthClaims
from membership_management.api.schemas.small_group_reports import (
    PersonSegmentSchema,
    ReportItemInputSchema,
    ReportItemSchema,
    ReportSectionsInputSchema,
    ReportSectionsSchema,
    SegmentSchema,
    TaggedPersonSchema,
    TextSegmentInputSchema,
    TextSegmentSchema,
)
from membership_management.data.small_groups.models import ReportSection
from membership_management.data.small_groups.report_items import PersonSegment, Segment, TextSegment
from membership_management.data.small_groups.results import PersonKey, ReportItemView, SectionsInput


def sections_input(sections: ReportSectionsInputSchema) -> SectionsInput:
    return {
        ReportSection.PRAYER: [_segments_input(item) for item in sections.prayer],
        ReportSection.PRAISE: [_segments_input(item) for item in sections.praise],
        ReportSection.FOLLOW_UP: [_segments_input(item) for item in sections.follow_up],
    }


def _segments_input(item: ReportItemInputSchema) -> list[Segment]:
    return [
        TextSegment(s.text)
        if isinstance(s, TextSegmentInputSchema)
        else PersonSegment((s.person.type, s.person.id))
        for s in item.segments
    ]


def tagged_in(items: Iterable[ReportItemView]) -> set[PersonKey]:
    """Everyone the items tag."""
    return {s.person for item in items for s in item.segments if isinstance(s, PersonSegment)}


def viewable_tagged(
    db: Session,
    claims: AuthClaims,
    items: Iterable[ReportItemView],
    member_scope: MemberScope,
    guest_scope: GuestScope,
) -> frozenset[PersonKey]:
    return viewable_people(db, claims, tagged_in(items), member_scope, guest_scope)


def segment_schemas(segments: Sequence[Segment], viewable: Collection[PersonKey]) -> list[SegmentSchema]:
    # `type` is passed explicitly: report routes exclude unset fields.
    result: list[SegmentSchema] = []
    for s in segments:
        if isinstance(s, TextSegment):
            result.append(TextSegmentSchema(type="text", text=s.text))
            continue
        kind, person_id = s.person
        result.append(
            PersonSegmentSchema(
                type="person",
                person=TaggedPersonSchema(
                    type=kind, id=person_id, name=s.name or "", viewable=s.person in viewable
                ),
            )
        )
    return result


def sections_schema(items: Sequence[ReportItemView], viewable: Collection[PersonKey]) -> ReportSectionsSchema:
    def section(key: ReportSection) -> list[ReportItemSchema]:
        return [
            ReportItemSchema(id=i.id, segments=segment_schemas(i.segments, viewable))
            for i in items
            if i.section == key
        ]

    return ReportSectionsSchema(
        prayer=section(ReportSection.PRAYER),
        praise=section(ReportSection.PRAISE),
        follow_up=section(ReportSection.FOLLOW_UP),
    )
