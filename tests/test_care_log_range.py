"""`GET /care-log` (care rule 53): the calendar's feed, by service and through the route."""

from __future__ import annotations

from datetime import date, time, timedelta
from typing import TYPE_CHECKING

from care_db_support import CareDbTestCase
from fastapi.testclient import TestClient

from membership_management.api.dependencies import get_members_db
from membership_management.api.jwt_auth import AuthClaims, get_current_claims
from membership_management.api.main import app
from membership_management.data.care.models import CareLogKind, CareLogStatus, CareLogVisibility
from membership_management.data.care.services import CareLogInvalidError, entries_in_range

if TYPE_CHECKING:
    from collections.abc import Sequence

    from httpx import Response

    from membership_management.data.members.models import Member

START = date(2026, 11, 1)
END = date(2026, 11, 30)
NO_KINDS: list[CareLogKind] = []


class _Base(CareDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.author = self.member("Alice Author", "user-alice")
        self.bob = self.member("Bob Participant", "user-bob")
        self.carol = self.member("Carol Person", "user-carol")
        self.erin = self.member("Erin Leader", "user-erin")
        self.lena = self.member("Lena Left", "user-lena")
        self.group_g = self.group("G", [self.carol, self.bob], left=[self.lena], leader=self.erin)


class EntriesInRangeTest(_Base):
    def ids(
        self,
        viewer_member: Member,
        *,
        sees_all: bool = False,
        group_ids: Sequence[int] = (),
        from_: date = START,
        to: date = END,
        mine: bool = False,
        small_group_id: int | None = None,
        kinds: Sequence[CareLogKind] = NO_KINDS,
    ) -> list[int]:
        viewer = self.viewer(viewer_member, sees_all=sees_all, group_ids=group_ids)
        entries = entries_in_range(
            self.db,
            viewer,
            from_=from_,
            to=to,
            mine=mine,
            small_group_id=small_group_id,
            kinds=kinds,
        )
        return [e.id for e in entries]

    def test_orders_by_date_then_time_with_all_day_first_then_id(self) -> None:
        late = self.entry(self.author, [self.carol], occurred_on=date(2026, 11, 10), at=time(15, 0))
        early = self.entry(self.author, [self.carol], occurred_on=date(2026, 11, 10), at=time(9, 0))
        all_day = self.entry(self.author, [self.carol], occurred_on=date(2026, 11, 10))
        all_day_2 = self.entry(self.author, [self.carol], occurred_on=date(2026, 11, 10))
        before = self.entry(self.author, [self.carol], occurred_on=date(2026, 11, 2), at=time(23, 0))
        self.assertEqual(
            [before.id, all_day.id, all_day_2.id, early.id, late.id], self.ids(self.author, sees_all=True)
        )

    def test_both_ends_are_included_and_outside_is_not(self) -> None:
        first = self.entry(self.author, [self.carol], occurred_on=START)
        last = self.entry(self.author, [self.carol], occurred_on=END)
        self.entry(self.author, [self.carol], occurred_on=START - timedelta(days=1))
        self.entry(self.author, [self.carol], occurred_on=END + timedelta(days=1))
        self.assertEqual([first.id, last.id], self.ids(self.author))

    def test_cancelled_and_deleted_are_left_out_planned_and_done_stay(self) -> None:
        done = self.entry(self.author, [self.carol])
        planned = self.entry(
            self.author,
            [self.carol],
            status=CareLogStatus.PLANNED,
            kind=CareLogKind.VISIT,
            occurred_on=date(2026, 11, 28),
        )
        self.entry(self.author, [self.carol], status=CareLogStatus.CANCELLED, kind=CareLogKind.CALL)
        self.entry(self.author, [self.carol], deleted=True)
        self.assertEqual([done.id, planned.id], self.ids(self.author))

    def test_uses_the_visibility_condition(self) -> None:
        hidden = self.entry(self.author, [self.carol], visibility=CareLogVisibility.PRIVATE)
        shown = self.entry(self.author, [self.carol])
        self.assertEqual([shown.id], self.ids(self.erin, group_ids=[self.group_g.id]))
        self.assertEqual([hidden.id, shown.id], self.ids(self.erin, sees_all=True))

    def test_mine_is_written_by_me_or_naming_me(self) -> None:
        wrote = self.entry(self.bob, [self.carol])
        named = self.entry(self.author, [self.carol], participants=[self.bob])
        self.entry(self.author, [self.carol])
        self.assertEqual([wrote.id, named.id], self.ids(self.bob, mine=True, group_ids=[self.group_g.id]))

    def test_mine_without_a_participation_shows_the_participants_private_entries_too(self) -> None:
        private = self.entry(
            self.author, [self.carol], participants=[self.bob], visibility=CareLogVisibility.PRIVATE
        )
        self.assertEqual([private.id], self.ids(self.bob, mine=True))

    def test_group_is_entries_about_someone_currently_in_it(self) -> None:
        about_carol = self.entry(self.author, [self.carol])
        both = self.entry(self.author, [self.lena, self.carol])
        other = self.member("Other")
        self.entry(self.author, [other])
        # Lena left G, so an entry only about her isn't in it.
        self.entry(self.author, [self.lena])
        self.assertEqual(
            [about_carol.id, both.id], self.ids(self.author, sees_all=True, small_group_id=self.group_g.id)
        )

    def test_group_includes_guests_in_a_guest_group(self) -> None:
        guest = self.guest("Gina Guest")
        guest_group = self.guest_group("Guests", [guest])
        visit = self.entry(self.author, [], about_guests=[guest], kind=CareLogKind.VISIT)
        self.entry(self.author, [self.carol])
        self.assertEqual([visit.id], self.ids(self.author, sees_all=True, small_group_id=guest_group.id))

    def test_kind_repeats(self) -> None:
        call = self.entry(self.author, [self.carol], kind=CareLogKind.CALL)
        visit = self.entry(self.author, [self.carol], kind=CareLogKind.VISIT)
        self.entry(self.author, [self.carol], kind=CareLogKind.NOTE)
        self.assertEqual(
            [call.id, visit.id], self.ids(self.author, kinds=[CareLogKind.CALL, CareLogKind.VISIT])
        )

    def test_the_range_may_span_63_days_inclusive_but_not_64(self) -> None:
        self.assertEqual([], self.ids(self.author, from_=START, to=START + timedelta(days=62)))
        with self.assertRaises(CareLogInvalidError) as caught:
            self.ids(self.author, from_=START, to=START + timedelta(days=63))
        self.assertEqual("range", caught.exception.code)

    def test_to_before_from_is_a_range_error(self) -> None:
        with self.assertRaises(CareLogInvalidError) as caught:
            self.ids(self.author, from_=END, to=START)
        self.assertEqual("range", caught.exception.code)

    def test_a_one_day_range_is_fine(self) -> None:
        only = self.entry(self.author, [self.carol], occurred_on=START)
        self.assertEqual([only.id], self.ids(self.author, from_=START, to=START))


class CareLogRouteTest(_Base):
    """Through the app, with the claims and the database overridden."""

    ELDER = AuthClaims(sub="user-alice", role="elder", perms={"careLog": ["view", "create", "all"]})
    LEADER = AuthClaims(
        sub="user-erin",
        role="smallGroupLeader",
        perms={"careLog": ["view", "create"], "smallGroups": ["view"], "members": ["view"]},
    )

    def setUp(self) -> None:
        super().setUp()
        self.claims = self.ELDER
        app.dependency_overrides[get_members_db] = lambda: self.db
        app.dependency_overrides[get_current_claims] = lambda: self.claims
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        super().tearDown()

    def get(self, params: str) -> Response:
        return self.client.get(f"/care-log?{params}")

    def status_for_group(self, group_id: int) -> int:
        return self.get(f"from=2026-11-01&to=2026-11-30&groupId={group_id}").status_code

    def test_returns_entries_in_order_as_the_entry_schema(self) -> None:
        a = self.entry(self.author, [self.carol], occurred_on=date(2026, 11, 3))
        b = self.entry(self.author, [self.carol], occurred_on=date(2026, 11, 2), participants=[self.bob])
        response = self.get("from=2026-11-01&to=2026-11-30")
        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual([b.id, a.id], [e["id"] for e in body])
        self.assertEqual("Carol Person", body[0]["people"][0]["name"])
        self.assertEqual("Bob Participant", body[0]["participants"][0]["name"])
        self.assertIn("canComplete", body[0])

    def test_the_other_get_routes_still_resolve(self) -> None:
        entry = self.entry(self.author, [self.carol])
        self.assertEqual(200, self.client.get("/care-log/coming-up").status_code)
        self.assertEqual(200, self.client.get(f"/care-log/{entry.id}").status_code)
        self.assertEqual(200, self.client.get("/care-log/people-search?q=ca").status_code)

    def test_repeated_kind_and_mine_and_group_parameters(self) -> None:
        call = self.entry(self.author, [self.carol], kind=CareLogKind.CALL)
        visit = self.entry(self.author, [self.carol], kind=CareLogKind.VISIT)
        self.entry(self.author, [self.carol], kind=CareLogKind.NOTE)
        response = self.get(f"from=2026-11-01&to=2026-11-30&kind=call&kind=visit&groupId={self.group_g.id}")
        self.assertEqual([call.id, visit.id], [e["id"] for e in response.json()])
        response = self.get("from=2026-11-01&to=2026-11-30&mine=true")
        self.assertEqual(3, len(response.json()))

    def test_range_errors_are_422_with_the_range_code(self) -> None:
        for params in ("from=2026-11-30&to=2026-11-01", "from=2026-11-01&to=2027-01-10"):
            response = self.get(params)
            self.assertEqual(422, response.status_code)
            self.assertEqual("range", response.json()["code"])

    def test_a_missing_date_or_an_unknown_kind_is_422(self) -> None:
        self.assertEqual(422, self.get("from=2026-11-01").status_code)
        self.assertEqual(422, self.get("from=2026-11-01&to=2026-11-30&kind=poem").status_code)

    def test_a_group_outside_the_callers_reach_is_404_and_inside_it_is_fine(self) -> None:
        other = self.group("Other", [self.author])
        self.entry(self.author, [self.carol])
        self.claims = self.LEADER
        self.assertEqual(404, self.status_for_group(other.id))
        self.assertEqual(404, self.status_for_group(999999))
        self.assertEqual(200, self.status_for_group(self.group_g.id))
        self.claims = self.ELDER
        self.assertEqual(200, self.status_for_group(other.id))
        self.assertEqual(404, self.status_for_group(999999))

    def test_a_leader_sees_what_rule_8_shares_and_a_user_without_the_permission_gets_403(self) -> None:
        self.entry(self.author, [self.carol], visibility=CareLogVisibility.PRIVATE)
        shown = self.entry(self.author, [self.carol])
        self.claims = self.LEADER
        response = self.get("from=2026-11-01&to=2026-11-30")
        self.assertEqual([shown.id], [e["id"] for e in response.json()])
        self.claims = AuthClaims(sub="user-x", role="user", perms={})
        self.assertEqual(403, self.get("from=2026-11-01&to=2026-11-30").status_code)
