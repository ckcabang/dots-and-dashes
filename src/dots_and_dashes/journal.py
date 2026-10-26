"""The Journal domain module: every bullet journal rule, with no I/O."""

import re
from dataclasses import dataclass, fields, replace
from datetime import date, datetime, time, tzinfo
from enum import StrEnum


class EntryType(StrEnum):
    TASK = "task"
    EVENT = "event"
    NOTE = "note"


class TaskState(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class BlankEntryError(ValueError):
    """Raised when there is no text to log."""


class TaskStateError(ValueError):
    """Raised when an Entry cannot move to the Task State asked for."""


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


def today(now: datetime, timezone: tzinfo) -> date:
    """The User's current day: local midnight to midnight, with no rollover hour."""
    return now.astimezone(timezone).date()


def _change_state(entry: Entry, *, allowed_from: set[TaskState], to: TaskState) -> Entry:
    if entry.state not in allowed_from:
        raise TaskStateError(f"a {entry.state or 'stateless'} Entry cannot become {to}")
    return replace(entry, state=to)


def complete(entry: Entry) -> Entry:
    """Mark an Open Task Completed (×)."""
    return _change_state(entry, allowed_from={TaskState.OPEN}, to=TaskState.COMPLETED)


def cancel(entry: Entry) -> Entry:
    """Mark an Open Task Cancelled: a recorded decision to abandon it."""
    return _change_state(entry, allowed_from={TaskState.OPEN}, to=TaskState.CANCELLED)


def reopen(entry: Entry) -> Entry:
    """Put a Completed or Cancelled Task back to Open."""
    return _change_state(
        entry,
        allowed_from={TaskState.COMPLETED, TaskState.CANCELLED},
        to=TaskState.OPEN,
    )


def as_typed(entry: Entry) -> str:
    """The Entry as it would be typed: the inverse of reading text with log_entry.

    Editing offers this text, so it spells out the Prefix (Signifiers, type,
    time) that log_entry reads back into the same Entry. A plain untimed Task
    is offered as its bare text, unless that text would itself read as a Prefix.
    """
    plain = ParsedEntry(
        type=EntryType.TASK, priority=False, inspiration=False, time=None, text=entry.text
    )
    wanted = ParsedEntry(
        type=entry.type,
        priority=entry.priority,
        inspiration=entry.inspiration,
        time=entry.time,
        text=entry.text,
    )
    if wanted == plain == read_prefix(entry.text):
        return entry.text
    type_character = {kind: char for char, kind in _TYPE_CHARACTERS.items()}[entry.type]
    prefix = "*" * entry.priority + "!" * entry.inspiration + type_character
    at = f" {entry.time:%H:%M}" if entry.time else ""
    return f"{prefix}{at} {entry.text}"


def edit_entry(entry: Entry, text: str) -> Entry:
    """Re-read edited text with the Prefix rules, keeping the Entry's place.

    Everything log_entry reads from text (type, Signifiers, time, text) is
    replaced. The day stays, and a Task that stays a Task keeps its Task State.
    """
    read = log_entry(text, on=entry.day)
    changes = {f.name: getattr(read, f.name) for f in fields(read)}
    del changes["day"]
    if read.type == entry.type and entry.state is not None:
        changes["state"] = entry.state
    return replace(entry, **changes)
