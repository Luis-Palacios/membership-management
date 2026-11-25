"""A scratch Postgres for the care log tests that need real SQL.

Set `CARE_TEST_DATABASE_URL` to an empty database already migrated to head (`MEMBERS_DATABASE_URL=<url>
uv run alembic upgrade head`, the functions and extensions come from the migrations) whose name contains
"scratch" or "test". The tests only write inside transactions they roll back, but keep it off the dev
database; without the variable those tests are skipped.
"""

from __future__ import annotations

import os
import unittest
from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING

from sqlalchemy import create_engine, select
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session

from membership_management.data import models as _models  # noqa: F401  (registers every table)
from membership_management.data.care.access_rules import CareLogViewer
from membership_management.data.care.models import (
    CareLogEntry,
    CareLogEntryParticipant,
    CareLogEntryPerson,
    CareLogKind,
    CareLogStatus,
    CareLogVisibility,
    MeetingMode,
)
from membership_management.data.care.queries import care_log_visible_condition
from membership_management.data.guests.models import Guest
from membership_management.data.members.models import Member
from membership_management.data.small_groups.models import (
    GroupAudience,
    SmallGroup,
    SmallGroupMember,
    SmallGroupRole,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.engine import Engine

DATABASE_URL = os.environ.get("CARE_TEST_DATABASE_URL")


def _safe(url: str) -> bool:
    name = make_url(url).database or ""
    return "scratch" in name or "test" in name


@unittest.skipUnless(DATABASE_URL and _safe(DATABASE_URL), "CARE_TEST_DATABASE_URL (a scratch DB) not set")
class CareDbTestCase(unittest.TestCase):
    """Each test runs in a transaction that is rolled back; the tables live for the class."""

    engine: Engine
    db: Session

    @classmethod
    def setUpClass(cls) -> None:
        if DATABASE_URL is None:
            raise unittest.SkipTest("CARE_TEST_DATABASE_URL not set")
        cls.engine = create_engine(DATABASE_URL)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        # An outer transaction the session joins through savepoints: a route that commits (the note
        # routes do) only releases a savepoint, and tearDown still rolls everything back.
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.db = Session(bind=self.connection, join_transaction_mode="create_savepoint")

    def tearDown(self) -> None:
        self.db.close()
        self.transaction.rollback()
        self.connection.close()

    # --- fixtures ---------------------------------------------------------------------------------------

    def member(self, name: str, user_id: str | None = None) -> Member:
        member = Member(name=name, user_id=user_id)
        self.db.add(member)
        self.db.flush()
        return member

    def group(
        self,
        name: str,
        members: Sequence[Member],
        *,
        left: Sequence[Member] = (),
        leader: Member | None = None,
    ) -> SmallGroup:
        group = SmallGroup(name=name, audience=GroupAudience.MEMBERS)
        self.db.add(group)
        self.db.flush()
        if leader is not None:
            self.db.add(
                SmallGroupMember.for_group(
                    group, member_id=leader.id, role=SmallGroupRole.LEADER, joined_at=date(2026, 1, 1)
                )
            )
        for member in members:
            self.db.add(
                SmallGroupMember.for_group(
                    group, member_id=member.id, role=SmallGroupRole.MEMBER, joined_at=date(2026, 1, 1)
                )
            )
        for member in left:
            self.db.add(
                SmallGroupMember.for_group(
                    group,
                    member_id=member.id,
                    role=SmallGroupRole.MEMBER,
                    joined_at=date(2026, 1, 1),
                    left_at=date(2026, 6, 1),
                )
            )
        self.db.flush()
        return group

    def guest_group(self, name: str, guests: Sequence[Guest]) -> SmallGroup:
        group = SmallGroup(name=name, audience=GroupAudience.GUESTS)
        self.db.add(group)
        self.db.flush()
        for guest in guests:
            self.db.add(SmallGroupMember.for_group(group, guest_id=guest.id, joined_at=date(2026, 1, 1)))
        self.db.flush()
        return group

    def guest(self, name: str) -> Guest:
        guest = Guest(name=name)
        self.db.add(guest)
        self.db.flush()
        return guest

    def entry(
        self,
        author: Member,
        about: Sequence[Member],
        *,
        about_guests: Sequence[Guest] = (),
        participants: Sequence[Member] = (),
        visibility: CareLogVisibility = CareLogVisibility.LEADERS,
        kind: CareLogKind = CareLogKind.CALL,
        status: CareLogStatus = CareLogStatus.DONE,
        occurred_on: date = date(2026, 11, 20),
        at: time | None = None,
        deleted: bool = False,
    ) -> CareLogEntry:
        entry = CareLogEntry(
            kind=kind,
            status=status,
            meeting_mode=MeetingMode.ONLINE if kind == CareLogKind.MEETING else None,
            occurred_on=occurred_on,
            occurred_at_time=at,
            text=None if status == CareLogStatus.PLANNED else "text",
            visibility=visibility,
            author_user_id=author.user_id or f"user-{author.id}",
            author_member_id=author.id,
            people=[
                *(CareLogEntryPerson(member_id=m.id) for m in about),
                *(CareLogEntryPerson(guest_id=g.id) for g in about_guests),
            ],
            participants=[CareLogEntryParticipant(member_id=m.id) for m in participants],
        )
        if deleted:
            entry.deleted_at = datetime.now(UTC)
        self.db.add(entry)
        self.db.flush()
        return entry

    def viewer(
        self,
        member: Member,
        *,
        sees_all: bool = False,
        can_view: bool = True,
        group_ids: Sequence[int] = (),
    ) -> CareLogViewer:
        """The caller as `api/care_access.py` would build them: a leader's members scope is the groups
        they lead."""
        return CareLogViewer(
            user_id=member.user_id or f"user-{member.id}",
            sees_all=sees_all,
            can_view=can_view,
            members_full=False,
            member_group_ids=frozenset(group_ids),
            guests_full=False,
            guest_group_ids=frozenset(),
            member_id=member.id,
        )

    def visible_ids(self, viewer: CareLogViewer) -> set[int]:
        return set(
            self.db.scalars(
                select(CareLogEntry.id).where(
                    CareLogEntry.deleted_at.is_(None), care_log_visible_condition(viewer)
                )
            )
        )
