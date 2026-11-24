"""Who sees a care log entry (care spec rule 8), as plain data. Pure: no database, no HTTP.

`api/care_access.py` builds a `CareLogViewer` from the caller's permissions and scopes;
`queries.care_log_visible_condition` is the one place that turns it into SQL, and every route, list and
the person timeline use that, so they can't disagree.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CareLogViewer:
    """The caller, as far as care log visibility is concerned.

    `sees_all` is `careLog: all` (admins and elders), `can_view` is `careLog: view`. The scopes are the
    members and guests scopes of `api/access.py`: `members_full` / `guests_full` for `members: all` /
    `guests: all`; otherwise the groups whose active people are in scope (`member_group_ids` None means any
    open group, an empty set none; guests only ever have a set, empty when they lead no guest group).
    """

    user_id: str
    sees_all: bool
    can_view: bool
    members_full: bool
    member_group_ids: frozenset[int] | None
    guests_full: bool
    guest_group_ids: frozenset[int]
    # The caller's own member, for "with whom" (None when the account isn't linked to a member).
    member_id: int | None = None
