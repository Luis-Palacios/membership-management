from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from membership_management.data.care.models import (
    CareLogEntry,
    CareLogEntryParticipant,
    CareLogEntryPerson,
    CareLogEntryRevision,
    CareLogKind,
    CareLogSourceKind,
    CareLogStatus,
    CareLogVisibility,
    MeetingMode,
)
from membership_management.data.guests.models import Guest, GuestStatus
from membership_management.data.members.models import Member, MemberSex, MemberStatus
from membership_management.data.seed.context import MANAGUA_TZ, SeedContext
from membership_management.data.small_groups.models import (
    ReportConversationComment,
    ReportSection,
    SmallGroup,
    SmallGroupMember,
    SmallGroupReport,
    SmallGroupReportItem,
    SmallGroupReportItemPerson,
    SmallGroupRole,
)

# The member group the story is set in (the canvas's "Jóvenes Bello Horizonte").
STORY_GROUP = "GP - #4"


def seed_care_log(ctx: SeedContext) -> None:
    """The care log story of the design canvas, on the seeded data: a member (the canvas's Lucía) with a
    call by an elder from a follow-up item, WhatsApp messages by her group's leader, a past planned call
    waiting for *Record how it went*, a planned meeting ahead with the leader taking part and an elders-only
    `heard` entry; and a guest with a visit from a follow-up item.

    Draws no random numbers, so it can run last without moving anything. The elders are the two the
    conversations seeder made up (`seed-elder-N`), the leaders have made-up user ids (`seed-user-<member
    id>`): no auth-server account matches them, so every entry shows as someone else's whoever you sign in
    as. Dates are relative to today.
    """
    session = ctx.session
    group = session.scalars(select(SmallGroup).where(SmallGroup.name == STORY_GROUP)).one()
    leader = session.scalars(
        select(Member)
        .join(SmallGroupMember, SmallGroupMember.member_id == Member.id)
        .where(
            SmallGroupMember.small_group_id == group.id,
            SmallGroupMember.left_at.is_(None),
            SmallGroupMember.role == SmallGroupRole.LEADER,
        )
    ).one()
    elders = _elders(ctx)
    elder_member, elder_user = elders[0]

    follow_up = _follow_up_item(ctx, group.id)
    if follow_up is not None:
        item, report, tagged_member_id = follow_up
    else:
        item = report = None
        tagged_member_id = session.scalars(
            select(SmallGroupMember.member_id)
            .join(Member, Member.id == SmallGroupMember.member_id)
            .where(
                SmallGroupMember.small_group_id == group.id,
                SmallGroupMember.left_at.is_(None),
                SmallGroupMember.role == SmallGroupRole.MEMBER,
                Member.status == MemberStatus.ACTIVE,
                Member.sex == MemberSex.FEMALE,
            )
            .order_by(SmallGroupMember.member_id)
        ).first()
    if tagged_member_id is None:
        return  # The seeded group has nobody to write about.
    lucia = tagged_member_id
    today = ctx.today
    leader_user = f"seed-user-{leader.id}"

    def at(day: int, hour: int) -> datetime:
        return datetime.combine(today + timedelta(days=day), time(hour, 0), MANAGUA_TZ)

    call_day = min((report.meeting_date + timedelta(days=2) - today).days, -1) if report else -26
    entries = [
        # A call by an elder, logged from the follow-up item.
        _entry(
            kind=CareLogKind.CALL,
            status=CareLogStatus.DONE,
            occurred_on=today + timedelta(days=call_day),
            occurred_at_time=time(18, 30),
            text="Hablé con ella por teléfono. Está cansada pero animada; prefiere discreción en el grupo.",
            visibility=CareLogVisibility.LEADERS,
            author=(elder_member, elder_user),
            people=[("member", lucia)],
            created_at=at(call_day, 19),
            source_item_id=item.id if item is not None else None,
        ),
        # WhatsApp messages by her group's leader, edited once.
        _entry(
            kind=CareLogKind.MESSAGE,
            status=CareLogStatus.DONE,
            occurred_on=today - timedelta(days=12),
            text="Le escribí por WhatsApp para saber cómo sigue. Está mejor y vendrá el jueves.",
            visibility=CareLogVisibility.LEADERS,
            author=(leader.id, leader_user),
            people=[("member", lucia)],
            created_at=at(-12, 20),
            edited_from="Le escribí por WhatsApp. Respondió que está mejor.",
        ),
        # A call planned for a past day: waiting for *Record how it went*. The leader takes part.
        _entry(
            kind=CareLogKind.CALL,
            status=CareLogStatus.PLANNED,
            occurred_on=today - timedelta(days=3),
            occurred_at_time=time(17, 0),
            text="Preguntarle cómo le fue con la decisión.",
            visibility=CareLogVisibility.LEADERS,
            author=(elder_member, elder_user),
            people=[("member", lucia)],
            participants=[leader.id],
            created_at=at(-8, 10),
        ),
        # A meeting ahead, in person, with the leader as participant.
        _entry(
            kind=CareLogKind.MEETING,
            status=CareLogStatus.PLANNED,
            occurred_on=today + timedelta(days=4),
            occurred_at_time=time(12, 30),
            meeting_mode=MeetingMode.IN_PERSON,
            text="Almuerzo para hablar de su lugar en el grupo.",
            visibility=CareLogVisibility.LEADERS,
            author=(elder_member, elder_user),
            people=[("member", lucia)],
            participants=[leader.id],
            created_at=at(-2, 9),
        ),
        # Something an elder heard: elders only.
        _entry(
            kind=CareLogKind.HEARD,
            status=CareLogStatus.DONE,
            occurred_on=today - timedelta(days=8),
            text="Comentó que ha tenido tensión en casa desde hace semanas.",
            heard_from="su hermana, después del servicio",
            others="su hija, 15 años",
            visibility=CareLogVisibility.PRIVATE,
            author=(elder_member, elder_user),
            people=[("member", lucia)],
            created_at=at(-8, 13),
        ),
    ]

    guest_story = _guest_story(ctx)
    if guest_story is not None:
        guest_id, guest_leader, guest_item = guest_story
        entries.append(
            _entry(
                kind=CareLogKind.VISIT,
                status=CareLogStatus.DONE,
                occurred_on=today - timedelta(days=5),
                text="Lo visité en su casa. Nos recibió bien y quedó en venir al grupo esta semana.",
                visibility=CareLogVisibility.LEADERS,
                author=(guest_leader.id, f"seed-user-{guest_leader.id}"),
                people=[("guest", guest_id)],
                created_at=at(-5, 16),
                source_item_id=guest_item.id if guest_item is not None else None,
            )
        )
    session.add_all(entries)
    session.flush()


def _entry(
    *,
    kind: CareLogKind,
    status: CareLogStatus,
    occurred_on: date,
    text: str | None,
    visibility: CareLogVisibility,
    author: tuple[int, str],
    people: list[tuple[str, int]],
    created_at: datetime,
    occurred_at_time: time | None = None,
    meeting_mode: MeetingMode | None = None,
    heard_from: str | None = None,
    others: str | None = None,
    participants: list[int] | None = None,
    source_item_id: int | None = None,
    edited_from: str | None = None,
) -> CareLogEntry:
    entry = CareLogEntry(
        kind=kind,
        status=status,
        meeting_mode=meeting_mode,
        occurred_on=occurred_on,
        occurred_at_time=occurred_at_time,
        text=text,
        heard_from=heard_from,
        others=others,
        visibility=visibility,
        author_member_id=author[0],
        author_user_id=author[1],
        created_at=created_at,
        people=[
            CareLogEntryPerson(
                member_id=person_id if person_kind == "member" else None,
                guest_id=person_id if person_kind == "guest" else None,
            )
            for person_kind, person_id in people
        ],
        participants=[CareLogEntryParticipant(member_id=member_id) for member_id in participants or []],
    )
    if source_item_id is not None:
        entry.source_kind = CareLogSourceKind.ITEM
        entry.source_item_id = source_item_id
    if edited_from is not None:
        entry.edited_at = created_at + timedelta(minutes=20)
        entry.revisions.append(CareLogEntryRevision(text=edited_from, created_at=entry.edited_at))
    return entry


def _elders(ctx: SeedContext) -> list[tuple[int, str]]:
    """The made-up elders of the conversations seeder, as (member id, user id)."""
    rows = ctx.session.execute(
        select(ReportConversationComment.author_member_id, ReportConversationComment.author_user_id)
        .where(ReportConversationComment.author_user_id.like("seed-elder-%"))
        .distinct()
        .order_by(ReportConversationComment.author_user_id)
    ).all()
    if rows:
        return [(row.author_member_id, row.author_user_id) for row in rows]
    # No conversations seeded: the first member who leads nothing.
    led = select(SmallGroupMember.member_id).where(SmallGroupMember.role != SmallGroupRole.MEMBER)
    member_id = ctx.session.scalars(
        select(Member.id)
        .where(Member.id.not_in(led), Member.status == MemberStatus.ACTIVE)
        .order_by(Member.id)
    ).first()
    if member_id is None:
        raise RuntimeError("The care seeder needs at least one member who leads nothing.")
    return [(member_id, "seed-elder-1")]


def _follow_up_item(
    ctx: SeedContext, group_id: int, *, guest_id: int | None = None
) -> tuple[SmallGroupReportItem, SmallGroupReport, int | None] | None:
    """The newest follow-up item of the group's reports that tags a member (or this guest), as (item,
    report, the tagged member's id)."""
    tagged = (
        SmallGroupReportItemPerson.guest_id == guest_id
        if guest_id is not None
        else SmallGroupReportItemPerson.member_id.is_not(None)
    )
    row = ctx.session.execute(
        select(SmallGroupReportItem, SmallGroupReport, SmallGroupReportItemPerson.member_id)
        .join(SmallGroupReport, SmallGroupReport.id == SmallGroupReportItem.report_id)
        .join(SmallGroupReportItemPerson, SmallGroupReportItemPerson.item_id == SmallGroupReportItem.id)
        .where(
            SmallGroupReport.small_group_id == group_id,
            SmallGroupReportItem.section == ReportSection.FOLLOW_UP,
            tagged,
        )
        .order_by(
            SmallGroupReport.meeting_date.desc(), SmallGroupReportItem.id, SmallGroupReportItemPerson.id
        )
        .limit(1)
    ).first()
    return None if row is None else (row[0], row[1], row[2])


def _guest_story(ctx: SeedContext) -> tuple[int, Member, SmallGroupReportItem | None] | None:
    """The newest follow-up item that tags an active guest (in any group's report), the guest and the
    member who submitted that report; a guest's visit is then logged from that item."""
    session = ctx.session
    row = session.execute(
        select(SmallGroupReportItem, SmallGroupReportItemPerson.guest_id, Member)
        .join(SmallGroupReport, SmallGroupReport.id == SmallGroupReportItem.report_id)
        .join(SmallGroupReportItemPerson, SmallGroupReportItemPerson.item_id == SmallGroupReportItem.id)
        .join(Guest, Guest.id == SmallGroupReportItemPerson.guest_id)
        .join(Member, Member.id == SmallGroupReport.submitted_by_member_id)
        .where(SmallGroupReportItem.section == ReportSection.FOLLOW_UP, Guest.status == GuestStatus.ACTIVE)
        .order_by(SmallGroupReport.meeting_date.desc(), SmallGroupReportItem.id)
        .limit(1)
    ).first()
    return None if row is None else (row[1], row[2], row[0])
