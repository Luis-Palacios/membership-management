"""Report items: conversion between the stored text with person tokens and the API's segments.

An item's `text` stores tagged people as tokens, `@{member:198}` and `@{guest:45}`, never their names,
so a rename carries through (report tags rule 11). Anything that doesn't match the token pattern
exactly is plain text. `small_group_report_item_people` indexes the tokens: whoever writes `text`
writes those rows from the same segments.
"""

import re
from collections.abc import Iterable, Mapping
from typing import NamedTuple

from membership_management.data.small_groups.results import PersonKey

TOKEN_PATTERN = re.compile(r"@\{(member|guest):(\d+)\}")
_WHITESPACE = re.compile(r"\s+")
# Leading list markers dropped when a text is split into items (rule 2): bullets, and `1.` / `1)`.
# `-`, `*` and numbers need whitespace after them, so `-5 °C`, `*urgent*` or `1.5` keep theirs.
_LIST_MARKER = re.compile(r"^(?:[–•·]\s*|[-*]\s+|\d+[.)]\s+)")


class TextSegment(NamedTuple):
    text: str


class PersonSegment(NamedTuple):
    person: PersonKey
    # The person's current name; None in segments written by a client (input carries ids only).
    name: str | None = None


Segment = TextSegment | PersonSegment


def token(person: PersonKey) -> str:
    kind, person_id = person
    return f"@{{{kind}:{person_id}}}"


def _neutralize_tokens(text: str) -> str:
    """Plain text that happens to spell a token stays plain text: break the `@{` apart."""
    return TOKEN_PATTERN.sub(lambda m: "@ {" + m.group(0)[2:], text)


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def segments_to_text(segments: Iterable[Segment]) -> tuple[str, list[PersonKey]]:
    """The stored text for an item and the people it tags, in order of first appearance.

    Whitespace runs (line breaks included: an item has none of its own) become one space, and the
    result is trimmed; an empty string means the item is empty. Adjacent text segments are joined
    before anything token-like in them is broken apart, so only person segments become tags.
    """
    parts: list[str] = []
    people: list[PersonKey] = []
    pending_text: list[str] = []
    for segment in segments:
        if isinstance(segment, TextSegment):
            pending_text.append(segment.text)
            continue
        parts.append(_neutralize_tokens("".join(pending_text)))
        pending_text = []
        parts.append(token(segment.person))
        if segment.person not in people:
            people.append(segment.person)
    parts.append(_neutralize_tokens("".join(pending_text)))
    return _normalize("".join(parts)), people


def tagged_people(text: str) -> list[PersonKey]:
    """The people a stored text tags, in order of first appearance."""
    people: list[PersonKey] = []
    for match in TOKEN_PATTERN.finditer(text):
        person: PersonKey = ("member" if match.group(1) == "member" else "guest", int(match.group(2)))
        if person not in people:
            people.append(person)
    return people


def text_to_segments(text: str, names: Mapping[PersonKey, str]) -> list[Segment]:
    """A stored text split into segments; `names` maps every person it tags to their current name."""
    segments: list[Segment] = []
    position = 0
    for match in TOKEN_PATTERN.finditer(text):
        if match.start() > position:
            segments.append(TextSegment(text[position : match.start()]))
        person: PersonKey = ("member" if match.group(1) == "member" else "guest", int(match.group(2)))
        segments.append(PersonSegment(person, names[person]))
        position = match.end()
    if position < len(text):
        segments.append(TextSegment(text[position:]))
    return segments


def split_legacy_text(text: str | None) -> list[str]:
    """One item per line of an old free-text section (rules 2 and 5), for the stage 1 backfill migration.

    Leading list markers are dropped, whitespace is collapsed, blank lines are skipped, and token-like
    text is broken apart (nothing is tagged from old text).
    """
    if text is None:
        return []
    items: list[str] = []
    for line in text.splitlines():
        item = _normalize(_neutralize_tokens(_LIST_MARKER.sub("", line.strip())))
        if item:
            items.append(item)
    return items
