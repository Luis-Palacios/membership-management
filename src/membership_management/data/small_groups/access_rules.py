"""The small group access rules as pure functions: no claims, no DB, no FastAPI.

One copy of the rule for the API (`api/access.py`, from the JWT's `perms`) and the email worker (from
auth-server's `POST /internal/users/permissions`), so an email only goes to someone the API would let
read the conversation (report conversations rule 23).
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass

# The JWT's `perms` claim and POST /internal/users/permissions' values: resource -> actions.
Perms = Mapping[str, Collection[str]]


def holds(perms: Perms, resource: str, action: str) -> bool:
    return action in perms.get(resource, ())


@dataclass(frozen=True)
class SmallGroupScope:
    """Which small groups the caller may touch: all of them (`full`) or just `group_ids`.

    `full` is `smallGroups: all`; without it the scope is the groups the caller's member leads, or
    co-led when they closed. Permissions say what the caller may do, this says on which groups.
    """

    full: bool
    group_ids: frozenset[int]
    member_id: int | None

    def includes(self, small_group_id: int) -> bool:
        return self.full or small_group_id in self.group_ids


def small_group_scope_for(
    perms: Perms, led_group_ids: frozenset[int], member_id: int | None
) -> SmallGroupScope | None:
    """None without `smallGroups: view` (leading grants nothing by itself); full with `smallGroups: all`;
    otherwise the groups the member leads, or led when the group closed (`led_group_ids`, which the
    caller looks up: one member for the API, many at once for the worker)."""
    if not holds(perms, "smallGroups", "view"):
        return None
    if holds(perms, "smallGroups", "all"):
        return SmallGroupScope(full=True, group_ids=frozenset(), member_id=member_id)
    return SmallGroupScope(full=False, group_ids=led_group_ids, member_id=member_id)


def can_read_group_conversations(perms: Perms, scope: SmallGroupScope | None, small_group_id: int) -> bool:
    """Report conversations rule 3: may this user read (and so be emailed about, rule 23) the
    conversations of this group's reports? `smallGroupReports: view`, then a full scope needs
    `viewObservations` (being full is not leading the group), a scoped user needs the group in scope."""
    if scope is None or not holds(perms, "smallGroupReports", "view"):
        return False
    if scope.full:
        return holds(perms, "smallGroupReports", "viewObservations")
    return small_group_id in scope.group_ids
