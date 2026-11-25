"""Notes from those who took part (care rules 59-63): the service and the routes."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from care_db_support import CareDbTestCase
from fastapi.testclient import TestClient
from sqlalchemy import select

from membership_management.api.dependencies import get_members_db
from membership_management.api.jwt_auth import AuthClaims, get_current_claims
from membership_management.api.main import app
from membership_management.data.care.models import (
    CareLogEntryNote,
    CareLogEntryNoteRevision,
    CareLogEntryParticipant,
    CareLogStatus,
)
from membership_management.data.care.services import (
    CareLogInvalidError,
    NoteExistsError,
    NoteNotAllowedError,
    NoteNotFoundError,
    add_note,
    can_add_note,
    delete_note,
    edit_note,
    get_entry,
    notes_for_entries,
)

if TYPE_CHECKING:
    from httpx import Response

    from membership_management.data.care.models import CareLogEntry
    from membership_management.data.members.models import Member

WRITE = {"careLog": ["view", "create"]}


def claims(member: Member, perms: dict[str, list[str]] | None = None) -> AuthClaims:
    return AuthClaims(sub=member.user_id or "", role="user", perms=WRITE if perms is None else perms)


class _Base(CareDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.alice = self.member("Alice Author", "user-alice")
        self.bob = self.member("Bob Participant", "user-bob")
        self.dana = self.member("Dana Participant", "user-dana")
        self.carol = self.member("Carol Person", "user-carol")
        self.erin = self.member("Erin Elder", "user-erin")
        self.entry_done = self.entry(self.alice, [self.carol], participants=[self.bob, self.dana])

    def note(self, entry: CareLogEntry, member: Member, text: str = "my note") -> CareLogEntryNote:
        note = CareLogEntryNote(
            entry_id=entry.id, author_member_id=member.id, author_user_id=member.user_id or "", text=text
        )
        self.db.add(note)
        self.db.flush()
        return note

    def loaded(self, entry_id: int) -> CareLogEntry:
        entry = get_entry(self.db, entry_id)
        if entry is None:
            raise AssertionError("the entry should exist")
        return entry

    def add(self, entry: CareLogEntry, member: Member, text: str = "hello") -> CareLogEntry:
        return add_note(self.db, entry, user_id=member.user_id or "", member_id=member.id, text=text)


class NoteServiceTest(_Base):
    def test_author_and_participants_each_write_one_note(self) -> None:
        for member in (self.alice, self.bob):
            self.add(self.entry_done, member, f"by {member.name}")
        notes = notes_for_entries(self.db, [self.entry_done.id])[self.entry_done.id]
        self.assertEqual(["by Alice Author", "by Bob Participant"], [n.text for n in notes])
        self.assertEqual([self.alice.id, self.bob.id], [n.author_member_id for n in notes])

    def test_text_is_trimmed_and_limited(self) -> None:
        self.add(self.entry_done, self.alice, "  spaced  ")
        self.assertEqual(
            "spaced", notes_for_entries(self.db, [self.entry_done.id])[self.entry_done.id][0].text
        )
        for bad in ("", "   ", "x" * 4001):
            with self.assertRaises(CareLogInvalidError) as raised:
                self.add(self.entry_done, self.bob, bad)
            self.assertEqual("text", raised.exception.code)
        self.add(self.entry_done, self.bob, "x" * 4000)

    def test_someone_not_on_the_entry_is_refused(self) -> None:
        with self.assertRaises(NoteNotAllowedError) as raised:
            self.add(self.entry_done, self.erin)
        self.assertEqual("not_participant", raised.exception.code)

    def test_planned_and_cancelled_entries_take_no_notes(self) -> None:
        for status in (CareLogStatus.PLANNED, CareLogStatus.CANCELLED):
            entry = self.entry(self.alice, [self.carol], participants=[self.bob], status=status)
            with self.assertRaises(CareLogInvalidError) as raised:
                self.add(entry, self.alice)
            self.assertEqual("not_done", raised.exception.code)

    def test_an_entry_without_participants_takes_no_notes(self) -> None:
        entry = self.entry(self.alice, [self.carol])
        with self.assertRaises(CareLogInvalidError) as raised:
            self.add(entry, self.alice)
        self.assertEqual("no_participants", raised.exception.code)

    def test_second_note_is_refused_but_allowed_after_a_delete(self) -> None:
        self.add(self.entry_done, self.bob, "first")
        with self.assertRaises(NoteExistsError):
            self.add(self.entry_done, self.bob, "second")
        first = notes_for_entries(self.db, [self.entry_done.id])[self.entry_done.id][0]
        delete_note(self.db, self.entry_done.id, first.id, user_id="user-bob")
        self.assertEqual({}, notes_for_entries(self.db, [self.entry_done.id]))
        self.add(self.entry_done, self.bob, "again")
        notes = notes_for_entries(self.db, [self.entry_done.id])[self.entry_done.id]
        self.assertEqual(["again"], [n.text for n in notes])
        # The deleted row stays.
        self.assertEqual(2, len(list(self.db.scalars(select(CareLogEntryNote)))))

    def test_edit_keeps_the_old_text_and_sets_edited_at(self) -> None:
        self.add(self.entry_done, self.bob, "first")
        note = notes_for_entries(self.db, [self.entry_done.id])[self.entry_done.id][0]
        self.assertIsNone(note.edited_at)
        edit_note(self.db, self.entry_done.id, note.id, user_id="user-bob", text=" second ")
        note = notes_for_entries(self.db, [self.entry_done.id])[self.entry_done.id][0]
        self.assertEqual("second", note.text)
        self.assertIsNotNone(note.edited_at)
        revisions = list(self.db.scalars(select(CareLogEntryNoteRevision)))
        self.assertEqual(["first"], [r.text for r in revisions])
        # The same text again changes nothing.
        edit_note(self.db, self.entry_done.id, note.id, user_id="user-bob", text="second")
        self.assertEqual(1, len(list(self.db.scalars(select(CareLogEntryNoteRevision)))))

    def test_nobody_edits_or_deletes_another_note_not_even_the_author(self) -> None:
        self.add(self.entry_done, self.bob)
        note = notes_for_entries(self.db, [self.entry_done.id])[self.entry_done.id][0]
        with self.assertRaises(NoteNotAllowedError) as raised:
            edit_note(self.db, self.entry_done.id, note.id, user_id="user-alice", text="mine now")
        self.assertEqual("not_note_writer", raised.exception.code)
        with self.assertRaises(NoteNotAllowedError):
            delete_note(self.db, self.entry_done.id, note.id, user_id="user-alice")

    def test_missing_deleted_or_foreign_notes_are_not_found(self) -> None:
        other = self.entry(self.alice, [self.carol], participants=[self.bob])
        self.add(other, self.bob)
        note = notes_for_entries(self.db, [other.id])[other.id][0]
        with self.assertRaises(NoteNotFoundError):
            edit_note(
                self.db, self.entry_done.id, note.id, user_id="user-bob", text="x"
            )  # another entry's note
        with self.assertRaises(NoteNotFoundError):
            edit_note(self.db, other.id, 0, user_id="user-bob", text="x")
        delete_note(self.db, other.id, note.id, user_id="user-bob")
        with self.assertRaises(NoteNotFoundError):
            delete_note(self.db, other.id, note.id, user_id="user-bob")

    def test_a_participant_removed_from_with_keeps_their_note(self) -> None:
        self.add(self.entry_done, self.bob)
        entry = self.loaded(self.entry_done.id)
        for participant in list(entry.participants):
            if participant.member_id == self.bob.id:
                self.db.delete(participant)
        self.db.flush()
        self.db.expire_all()
        notes = notes_for_entries(self.db, [self.entry_done.id])[self.entry_done.id]
        self.assertEqual([self.bob.id], [n.author_member_id for n in notes])
        self.assertEqual(
            0,
            len(
                list(
                    self.db.scalars(
                        select(CareLogEntryParticipant).where(
                            CareLogEntryParticipant.member_id == self.bob.id
                        )
                    )
                )
            ),
        )

    def test_adding_a_note_leaves_the_entry_alone(self) -> None:
        before = (self.entry_done.occurred_on, self.entry_done.status, self.entry_done.edited_at)
        self.add(self.entry_done, self.bob)
        entry = self.loaded(self.entry_done.id)
        self.assertEqual(before, (entry.occurred_on, entry.status, entry.edited_at))
        self.assertEqual(date(2026, 11, 20), entry.occurred_on)

    def test_can_add_note(self) -> None:
        entry = self.loaded(self.entry_done.id)

        def can(member: Member, *, write: bool = True) -> bool:
            notes = notes_for_entries(self.db, [entry.id]).get(entry.id, [])
            return can_add_note(
                entry, notes, user_id=member.user_id or "", member_id=member.id, can_write=write
            )

        self.assertTrue(can(self.alice))
        self.assertTrue(can(self.bob))
        self.assertFalse(can(self.erin))
        self.assertFalse(can(self.bob, write=False))
        self.add(self.entry_done, self.bob)
        self.assertFalse(can(self.bob))
        self.assertTrue(can(self.dana))


class NoteRouteTest(_Base):
    """Through the app, with the claims and the database overridden."""

    def setUp(self) -> None:
        super().setUp()
        self.claims = claims(self.alice)
        app.dependency_overrides[get_members_db] = lambda: self.db
        app.dependency_overrides[get_current_claims] = lambda: self.claims
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        super().tearDown()

    def as_(self, member: Member, perms: dict[str, list[str]] | None = None) -> None:
        self.claims = claims(member, perms)

    def post(self, entry: CareLogEntry, text: str = "A note") -> Response:
        return self.client.post(f"/care-log/{entry.id}/notes", json={"text": text})

    def test_create_returns_the_entry_with_the_note_and_can_add_note_false(self) -> None:
        response = self.post(self.entry_done, "  Hello  ")
        self.assertEqual(201, response.status_code)
        body = response.json()
        self.assertEqual(1, len(body["notes"]))
        note = body["notes"][0]
        self.assertEqual("Hello", note["text"])
        self.assertEqual({"memberId": self.alice.id, "name": "Alice Author"}, note["author"])
        self.assertTrue(note["canEdit"])
        self.assertIsNone(note["editedAt"])
        self.assertIn("createdAt", note)
        self.assertFalse(body["canAddNote"])
        self.assertIsNone(body["editedAt"])

    def test_can_add_note_and_can_edit_per_viewer(self) -> None:
        self.assertEqual(201, self.post(self.entry_done).status_code)
        self.as_(self.bob)
        body = self.client.get(f"/care-log/{self.entry_done.id}").json()
        self.assertTrue(body["canAddNote"])
        self.assertEqual([False], [n["canEdit"] for n in body["notes"]])
        self.as_(self.carol)  # about herself: never sees it (rule 8)
        self.assertEqual(404, self.client.get(f"/care-log/{self.entry_done.id}").status_code)
        self.as_(self.erin, {"careLog": ["view", "create", "all"]})
        body = self.client.get(f"/care-log/{self.entry_done.id}").json()
        self.assertFalse(body["canAddNote"])  # an elder not on the entry
        self.assertEqual(1, len(body["notes"]))

    def test_errors_and_their_codes(self) -> None:
        self.as_(self.erin, {"careLog": ["view", "create", "all"]})
        response = self.post(self.entry_done)
        self.assertEqual((403, "not_participant"), (response.status_code, response.json()["code"]))
        self.as_(self.alice)
        planned = self.entry(self.alice, [self.carol], participants=[self.bob], status=CareLogStatus.PLANNED)
        response = self.post(planned)
        self.assertEqual((422, "not_done"), (response.status_code, response.json()["code"]))
        alone = self.entry(self.alice, [self.carol])
        response = self.post(alone)
        self.assertEqual((422, "no_participants"), (response.status_code, response.json()["code"]))
        response = self.post(self.entry_done, "  ")
        self.assertEqual((422, "text"), (response.status_code, response.json()["code"]))
        self.assertEqual(201, self.post(self.entry_done).status_code)
        response = self.post(self.entry_done)
        self.assertEqual((409, "note_exists"), (response.status_code, response.json()["code"]))

    def test_unlinked_caller_is_409_link_and_without_permission_403(self) -> None:
        self.claims = AuthClaims(
            sub="user-unlinked", role="elder", perms={"careLog": ["view", "create", "all"]}
        )
        response = self.post(self.entry_done)
        self.assertEqual((409, "link"), (response.status_code, response.json()["code"]))
        self.as_(self.bob, {"careLog": ["view"]})
        self.assertEqual(403, self.post(self.entry_done).status_code)

    def test_hidden_or_deleted_entries_are_404_for_every_note_route(self) -> None:
        self.as_(self.carol)
        self.assertEqual(404, self.post(self.entry_done).status_code)
        self.assertEqual(
            404, self.client.patch(f"/care-log/{self.entry_done.id}/notes/1", json={"text": "x"}).status_code
        )
        self.assertEqual(404, self.client.delete(f"/care-log/{self.entry_done.id}/notes/1").status_code)
        self.as_(self.alice)
        gone = self.entry(self.alice, [self.carol], participants=[self.bob], deleted=True)
        self.assertEqual(404, self.post(gone).status_code)

    def test_patch_and_delete_only_by_the_writer(self) -> None:
        self.as_(self.bob)
        note_id = self.post(self.entry_done, "bob's").json()["notes"][0]["id"]
        url = f"/care-log/{self.entry_done.id}/notes/{note_id}"
        self.as_(self.alice)  # the entry's author
        for response in (self.client.patch(url, json={"text": "no"}), self.client.delete(url)):
            self.assertEqual((403, "not_note_writer"), (response.status_code, response.json()["code"]))
        self.as_(self.bob)
        response = self.client.patch(url, json={"text": "bob's, edited"})
        self.assertEqual(200, response.status_code)
        note = response.json()["notes"][0]
        self.assertEqual(("bob's, edited", True), (note["text"], note["canEdit"]))
        self.assertIsNotNone(note["editedAt"])
        self.assertEqual(422, self.client.patch(url, json={"text": ""}).status_code)
        self.assertEqual(204, self.client.delete(url).status_code)
        self.assertEqual(404, self.client.delete(url).status_code)
        body = self.client.get(f"/care-log/{self.entry_done.id}").json()
        self.assertEqual([], body["notes"])
        self.assertTrue(body["canAddNote"])

    def test_notes_are_oldest_first_and_reach_the_list(self) -> None:
        self.as_(self.bob)
        self.post(self.entry_done, "second writer")
        self.as_(self.alice)
        self.post(self.entry_done, "third writer")
        listing = self.client.get("/care-log?from=2026-11-01&to=2026-11-30").json()
        self.assertEqual(["second writer", "third writer"], [n["text"] for n in listing[0]["notes"]])

    def test_a_removed_participant_keeps_the_note_but_loses_the_entry(self) -> None:
        self.as_(self.bob)
        self.post(self.entry_done, "bob's")
        entry = self.loaded(self.entry_done.id)
        for participant in list(entry.participants):
            if participant.member_id == self.bob.id:
                self.db.delete(participant)
        self.db.flush()
        self.db.expire_all()
        self.assertEqual(404, self.client.get(f"/care-log/{self.entry_done.id}").status_code)
        self.as_(self.alice)
        body = self.client.get(f"/care-log/{self.entry_done.id}").json()
        self.assertEqual(["bob's"], [n["text"] for n in body["notes"]])
        self.assertEqual(self.bob.id, body["notes"][0]["author"]["memberId"])

    def test_deleting_the_entry_hides_its_notes(self) -> None:
        self.post(self.entry_done)
        self.assertEqual(204, self.client.delete(f"/care-log/{self.entry_done.id}").status_code)
        self.assertEqual(404, self.client.get(f"/care-log/{self.entry_done.id}").status_code)
        self.assertEqual(404, self.post(self.entry_done).status_code)
