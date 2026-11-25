"""Care log rules 3 and 8: who sees an entry, with participants (`care_log_visible_condition`), and who
gains it (`participant_gains`)."""

from __future__ import annotations

import unittest
from datetime import date, datetime, time
from typing import TYPE_CHECKING, ClassVar

from care_db_support import CareDbTestCase

from membership_management.data.care.access_rules import participant_gains
from membership_management.data.care.models import (
    CareLogEntryParticipant,
    CareLogKind,
    CareLogStatus,
    CareLogVisibility,
)
from membership_management.data.care.services import coming_up, participants_gaining

if TYPE_CHECKING:
    from membership_management.data.small_groups.results import PersonKey

PRIVATE = CareLogVisibility.PRIVATE
NOW = datetime.combine(date(2026, 11, 24), time(10, 0))


class ParticipantVisibilityTest(CareDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.author = self.member("Alice Author", "user-alice")
        self.bob = self.member("Bob Participant", "user-bob")
        self.carol = self.member("Carol Person", "user-carol")
        self.erin = self.member("Erin Leader", "user-erin")
        self.frank = self.member("Frank Other Leader", "user-frank")
        self.group_g = self.group("G", [self.carol, self.bob])
        self.group_h = self.group("H", [self.frank])
        self.private = self.entry(self.author, [self.carol], participants=[self.bob], visibility=PRIVATE)
        self.leaders = self.entry(self.author, [self.carol], participants=[self.bob])
        self.about_bob = self.entry(self.author, [self.bob], participants=[self.bob])
        self.plain = self.entry(self.author, [self.carol])

    def test_a_participant_sees_a_private_entry_they_are_named_on(self) -> None:
        ids = self.visible_ids(self.viewer(self.bob))
        self.assertIn(self.private.id, ids)
        self.assertIn(self.leaders.id, ids)

    def test_a_participant_sees_only_the_entries_they_are_named_on(self) -> None:
        self.assertNotIn(self.plain.id, self.visible_ids(self.viewer(self.bob)))

    def test_a_participant_without_care_log_view_still_sees_the_entry(self) -> None:
        ids = self.visible_ids(self.viewer(self.bob, can_view=False))
        self.assertEqual({self.private.id, self.leaders.id}, ids)

    def test_being_named_on_an_entry_about_yourself_doesnt_lift_rule_8(self) -> None:
        for viewer in (self.viewer(self.bob), self.viewer(self.bob, can_view=False)):
            self.assertNotIn(self.about_bob.id, self.visible_ids(viewer))

    def test_the_author_of_an_entry_about_themselves_still_sees_it(self) -> None:
        own = self.entry(self.bob, [self.bob], participants=[self.bob])
        self.assertIn(own.id, self.visible_ids(self.viewer(self.bob)))

    def test_care_log_all_sees_everything_including_entries_about_themselves(self) -> None:
        ids = self.visible_ids(self.viewer(self.bob, sees_all=True))
        self.assertEqual({self.private.id, self.leaders.id, self.about_bob.id, self.plain.id}, ids)

    def test_a_leader_who_is_not_named_is_unchanged(self) -> None:
        leader = self.viewer(self.erin, group_ids=[self.group_g.id])
        # Bob is in the group too, so the entry about him is the leader's; rule 8 only hides it from Bob.
        self.assertEqual({self.leaders.id, self.plain.id, self.about_bob.id}, self.visible_ids(leader))

    def test_a_leader_of_another_group_sees_nothing(self) -> None:
        self.assertEqual(set(), self.visible_ids(self.viewer(self.frank, group_ids=[self.group_h.id])))

    def test_the_author_sees_theirs_without_care_log_view(self) -> None:
        ids = self.visible_ids(self.viewer(self.author, can_view=False))
        self.assertEqual({self.private.id, self.leaders.id, self.about_bob.id, self.plain.id}, ids)

    def test_a_participant_added_later_gains_it_and_one_removed_loses_it(self) -> None:
        self.assertNotIn(self.plain.id, self.visible_ids(self.viewer(self.frank)))
        participant = CareLogEntryParticipant(entry_id=self.plain.id, member_id=self.frank.id)
        self.db.add(participant)
        self.db.flush()
        self.assertIn(self.plain.id, self.visible_ids(self.viewer(self.frank)))
        self.db.delete(participant)
        self.db.flush()
        self.assertNotIn(self.plain.id, self.visible_ids(self.viewer(self.frank)))

    def test_coming_up_lists_the_plans_a_participant_newly_sees(self) -> None:
        plan = self.entry(
            self.author,
            [self.carol],
            participants=[self.bob],
            visibility=PRIVATE,
            kind=CareLogKind.MEETING,
            status=CareLogStatus.PLANNED,
            occurred_on=date(2026, 11, 26),
        )
        other = self.entry(
            self.author,
            [self.carol],
            visibility=PRIVATE,
            kind=CareLogKind.CALL,
            status=CareLogStatus.PLANNED,
            occurred_on=date(2026, 11, 26),
        )
        past_due, upcoming = coming_up(self.db, self.viewer(self.bob), self.bob.id, now=NOW)
        self.assertEqual([plan.id], [e.id for e in upcoming])
        self.assertEqual([], past_due)
        self.assertNotIn(other.id, [e.id for e in upcoming])


class ParticipantsGainingTest(CareDbTestCase):
    """The service behind `POST /care-log/audience`: rule 3's warning."""

    def setUp(self) -> None:
        super().setUp()
        self.caller = self.member("Caller", "u-caller")
        self.person = self.member("Person", "u-person")
        self.leader_g = self.member("Leader of G", "u-lg")
        self.leader_h = self.member("Leader of H", "u-lh")
        self.elder = self.member("Elder", "u-elder")
        self.no_user = self.member("No User")
        self.group("G", [self.person], leader=self.leader_g)
        self.group("H", [], leader=self.leader_h)
        leader = {"careLog": ["view"], "smallGroups": ["view"], "members": ["view"]}
        self.perms = {
            "u-caller": leader,
            "u-person": leader,
            "u-lg": leader,
            "u-lh": leader,
            "u-elder": {"careLog": ["view", "all"]},
        }

    def gaining(
        self, visibility: CareLogVisibility, participants: list[int], *, about: list[int] | None = None
    ) -> list[int] | None:
        about = [self.person.id] if about is None else about
        people: list[PersonKey] = [("member", m) for m in about]
        members = [self.caller, self.person, self.leader_g, self.leader_h, self.elder, self.no_user]
        return participants_gaining(
            self.db,
            participants=participants,
            user_ids={m.id: m.user_id for m in members},
            people=people,
            visibility=visibility,
            perms_by_user=self.perms,
            caller_member_id=self.caller.id,
        )

    def test_leaders_entry_is_gained_by_the_leader_outside_the_persons_group_only(self) -> None:
        ids = [self.leader_g.id, self.leader_h.id, self.elder.id]
        self.assertEqual([self.leader_h.id], self.gaining(CareLogVisibility.LEADERS, ids))

    def test_private_entry_is_gained_by_everyone_but_elders(self) -> None:
        ids = [self.leader_g.id, self.leader_h.id, self.elder.id]
        self.assertEqual([self.leader_g.id, self.leader_h.id], self.gaining(PRIVATE, ids))

    def test_never_the_caller_the_person_or_a_member_without_a_user(self) -> None:
        ids = [self.caller.id, self.person.id, self.no_user.id]
        self.assertEqual([], self.gaining(PRIVATE, ids))

    def test_unknown_when_permissions_couldnt_be_had(self) -> None:
        result = participants_gaining(
            self.db,
            participants=[self.leader_h.id],
            user_ids={self.leader_h.id: "u-lh"},
            people=[("member", self.person.id)],
            visibility=PRIVATE,
            perms_by_user=None,
            caller_member_id=self.caller.id,
        )
        self.assertIsNone(result)

    def test_a_banned_or_unknown_user_gains_nothing(self) -> None:
        del self.perms["u-lh"]
        self.assertEqual([], self.gaining(PRIVATE, [self.leader_h.id]))


class ParticipantGainsRuleTest(unittest.TestCase):
    """The pure half of `POST /care-log/audience` (rule 3)."""

    LEADER: ClassVar[dict[str, list[str]]] = {"careLog": ["view"]}
    ELDER: ClassVar[dict[str, list[str]]] = {"careLog": ["view", "all"]}
    NOBODY: ClassVar[dict[str, list[str]]] = {}

    def test_private_is_gained_by_everyone_who_isnt_care_log_all(self) -> None:
        for perms in (self.LEADER, self.NOBODY):
            self.assertTrue(
                participant_gains(perms, PRIVATE, is_one_of_the_people=False, person_in_scope=True)
            )
        self.assertFalse(
            participant_gains(self.ELDER, PRIVATE, is_one_of_the_people=False, person_in_scope=False)
        )

    def test_leaders_is_gained_without_view_or_without_the_person_in_scope(self) -> None:
        leaders = CareLogVisibility.LEADERS
        self.assertFalse(
            participant_gains(self.LEADER, leaders, is_one_of_the_people=False, person_in_scope=True)
        )
        self.assertTrue(
            participant_gains(self.LEADER, leaders, is_one_of_the_people=False, person_in_scope=False)
        )
        self.assertTrue(
            participant_gains(self.NOBODY, leaders, is_one_of_the_people=False, person_in_scope=True)
        )
        self.assertFalse(
            participant_gains(self.ELDER, leaders, is_one_of_the_people=False, person_in_scope=False)
        )

    def test_one_of_the_people_gains_nothing(self) -> None:
        for visibility in CareLogVisibility:
            self.assertFalse(
                participant_gains(self.LEADER, visibility, is_one_of_the_people=True, person_in_scope=False)
            )


if __name__ == "__main__":
    unittest.main()
