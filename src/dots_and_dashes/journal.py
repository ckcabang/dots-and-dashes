"""The Journal domain module: every bullet journal rule, with no I/O."""

import re
from dataclasses import dataclass, replace
from datetime import date, datetime, time, tzinfo
from enum import StrEnum


class EntryType(StrEnum):
    TASK = "task"
    EVENT = "event"
    NOTE = "note"


class TaskState(StrEnum):
    OPEN = "open"


class BlankEntryError(ValueError):
    """Raised when there is no text to log."""


class NestingError(ValueError):
    """Raised when an Entry can't be nested where it was asked to be."""


@dataclass(frozen=True)
class ParsedEntry:
    """What the Prefix rules read from typed text."""

    type: EntryType
    priority: bool
    inspiration: bool
    time: time | None
    text: str


_TYPE_CHARACTERS = {".": EntryType.TASK, "o": EntryType.EVENT, "-": EntryType.NOTE}
# Signifiers, then the type; either may be left out, but not both, and the
# Prefix must be followed by a space so text like ".5 miles" isn't read as one.
_PREFIX = re.compile(r"(?P<signifiers>[*!]*)(?P<type>[.o-]?) +")
# A time is a 24-hour HH:MM, or a 12-hour 9am or 2:30pm, followed by a space or
# the end of the text.
_TIME = re.compile(
    r"(?:(?P<hour>\d{1,2}):(?P<minute>\d{2})|(?P<hour12>\d{1,2})(?::(?P<minute12>\d{2}))?"
    r"(?P<meridiem>am|pm))(?: +|$)",
    re.IGNORECASE,
)


def _read_time(text: str) -> tuple[time | None, str]:
    """Split a leading time of day off text, if it starts with a valid one."""
    match = _TIME.match(text)
    if not match:
        return None, text
    if match["meridiem"]:
        hour12, minute = int(match["hour12"]), int(match["minute12"] or 0)
        if not 1 <= hour12 <= 12:
            return None, text
        hour = hour12 % 12 + (12 if match["meridiem"].lower() == "pm" else 0)
    else:
        hour, minute = int(match["hour"]), int(match["minute"])
    if hour > 23 or minute > 59:
        return None, text
    return time(hour, minute), text[match.end() :]


def read_prefix(text: str) -> ParsedEntry:
    """Read an Entry's Signifiers, type and time from the Prefix at the start of typed text."""
    match = _PREFIX.match(text)
    if not match or not (match["signifiers"] or match["type"]):
        return ParsedEntry(
            type=EntryType.TASK, priority=False, inspiration=False, time=None, text=text
        )
    at, rest = _read_time(text[match.end() :])
    return ParsedEntry(
        type=_TYPE_CHARACTERS.get(match["type"], EntryType.TASK),
        priority="*" in match["signifiers"],
        inspiration="!" in match["signifiers"],
        time=at,
        text=rest,
    )


@dataclass(frozen=True)
class NewEntry:
    """An Entry that has been logged but not yet stored."""

    type: EntryType
    state: TaskState | None  # only Tasks have a Task State
    priority: bool
    inspiration: bool
    time: time | None
    text: str
    day: date


@dataclass(frozen=True)
class Entry:
    """A stored Entry on a Daily Log."""

    id: int
    type: EntryType
    state: TaskState | None  # only Tasks have a Task State
    priority: bool
    inspiration: bool
    time: time | None
    text: str
    day: date
    # A Nested Note's parent: the Task or Event it is attached to.
    parent_id: int | None = None


def log_entry(text: str, *, on: date) -> NewEntry:
    """Turn text typed into a Daily Log's input box into an Entry on that day."""
    # Only leading whitespace goes before the Prefix is read: a trailing space
    # is what makes ". " a Prefix with no text rather than a Task called ".".
    parsed = read_prefix(text.lstrip())
    text = parsed.text.strip()
    if not text:
        raise BlankEntryError("an Entry needs some text")
    return NewEntry(
        type=parsed.type,
        state=TaskState.OPEN if parsed.type is EntryType.TASK else None,
        priority=parsed.priority,
        inspiration=parsed.inspiration,
        time=parsed.time,
        text=text,
        day=on,
    )


def daily_log_order(entries: list[Entry]) -> list[Entry]:
    """Order a Daily Log's Entries, given in the order they were logged.

    Timed Entries run in chronological order. Each untimed Entry stays after
    its Anchor, the Timed Entry logged most recently before it; untimed
    Entries logged before any Timed Entry stay at the top.
    """
    groups: list[list[Entry]] = [[]]
    for entry in entries:
        if entry.time is not None:
            groups.append([])
        groups[-1].append(entry)
    top, anchored = groups[0], groups[1:]
    # sorted() is stable, so Anchors at the same time keep their logged order.
    anchored = sorted(anchored, key=lambda group: group[0].time or time.min)
    return top + [entry for group in anchored for entry in group]


def arrange_daily_log(entries: list[Entry]) -> list[Entry]:
    """Lay out a Daily Log's Entries, given in the order they were logged.

    Entries that aren't Nested Notes follow the Daily Log ordering; each
    Nested Note sits under its parent, in the order it was logged, so it
    moves wherever its parent goes.
    """
    nested: dict[int, list[Entry]] = {}
    for entry in entries:
        if entry.parent_id is not None:
            nested.setdefault(entry.parent_id, []).append(entry)
    ordered = daily_log_order([entry for entry in entries if entry.parent_id is None])
    return [shown for entry in ordered for shown in [entry, *nested.get(entry.id, [])]]


def nest_note(note: Entry, daily_log: list[Entry]) -> Entry:
    """Nest a Note under the Task or Event above it on its Daily Log, given in display order."""
    if note.type is not EntryType.NOTE:
        raise NestingError("only Notes can be nested")
    # Nested Notes sit right under their parent, so the nearest Entry above
    # that isn't one is the Note's parent-to-be.
    above = [entry for entry in daily_log[: daily_log.index(note)] if entry.parent_id is None]
    if not above or above[-1].type not in (EntryType.TASK, EntryType.EVENT):
        raise NestingError("a Note nests only under the Task or Event above it")
    return replace(note, parent_id=above[-1].id)


def un_nest_note(note: Entry) -> Entry:
    """Detach a Nested Note from its parent so it stands alone again."""
    return replace(note, parent_id=None)


def today(now: datetime, timezone: tzinfo) -> date:
    """The User's current day: local midnight to midnight, with no rollover hour."""
    return now.astimezone(timezone).date()
