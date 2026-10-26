"""The Journal domain module: every bullet journal rule, with no I/O."""

import re
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, tzinfo
from enum import StrEnum


class EntryType(StrEnum):
    TASK = "task"
    EVENT = "event"
    NOTE = "note"


class TaskState(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Location(StrEnum):
    """Where an Entry lives: a Daily Log, a Monthly Log's task list or the Future Log."""

    DAY = "day"
    MONTH = "month"
    FUTURE = "future"


class BlankEntryError(ValueError):
    """Raised when there is no text to log."""


class PlacementError(ValueError):
    """Raised when an Entry cannot live where it was put."""


class NoMonthlyLogError(PlacementError):
    """Raised for a month after the current one, which has no Monthly Log."""


class EventNeedsDateError(PlacementError):
    """Raised for an Event without a date outside the Future Log."""


class NotAFutureMonthError(PlacementError):
    """Raised for a Future Log month that is not after the current one."""


class DateOutsideMonthError(PlacementError):
    """Raised for a Future Log date that is not in its month."""


class NotOnADailyLogError(PlacementError):
    """Raised for an Entry on the Monthly Log or Future Log where a Daily Log one is needed."""


class NestingError(ValueError):
    """Raised when an Entry can't be nested where it was asked to be."""


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
    day: date | None  # a Daily Log's date; optional in the Future Log
    location: Location = Location.DAY
    month: date | None = None  # for the Monthly Log's task list and the Future Log


@dataclass(frozen=True)
class Entry:
    """A stored Entry."""

    id: int
    type: EntryType
    state: TaskState | None  # only Tasks have a Task State
    priority: bool
    inspiration: bool
    time: time | None
    text: str
    day: date | None  # a Daily Log's date; optional in the Future Log
    location: Location = Location.DAY
    month: date | None = None  # for the Monthly Log's task list and the Future Log
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


class TimedEntryMoveError(ValueError):
    """Raised when a Timed Entry is dragged; it moves only by changing its time."""


class NestedNoteMoveError(ValueError):
    """Raised when a Nested Note is moved on its own; it moves with its parent."""


class UntimedEntryError(ValueError):
    """Raised when changing the time of an Entry that has none."""


def _anchored_groups(entries: list[Entry]) -> tuple[list[Entry], list[list[Entry]]]:
    """Split Entries in manual order into the untimed ones at the top of the day
    and groups each led by a Timed Entry, followed by the Entries Anchored to it."""
    groups: list[list[Entry]] = [[]]
    for entry in entries:
        if entry.time is not None:
            groups.append([])
        groups[-1].append(entry)
    return groups[0], groups[1:]


def _in_order(top: list[Entry], anchored: list[list[Entry]]) -> list[Entry]:
    # sorted() is stable, so Anchors at the same time keep their manual order.
    anchored = sorted(anchored, key=lambda group: group[0].time or time.min)
    return top + [entry for group in anchored for entry in group]


def daily_log_order(entries: list[Entry]) -> list[Entry]:
    """Order a Daily Log's Entries, given in their manual order.

    Timed Entries run in chronological order. Each untimed Entry stays after
    its Anchor, the nearest Timed Entry before it in manual order; untimed
    Entries before any Timed Entry stay at the top. Storing the result as the
    new manual order leaves it unchanged.
    """
    return _in_order(*_anchored_groups(entries))


def arrange_daily_log(entries: list[Entry]) -> list[Entry]:
    """Lay out a Daily Log's Entries, given in their manual order.

    Entries that aren't Nested Notes follow the Daily Log ordering; each
    Nested Note sits under its parent, in manual order, so it moves wherever
    its parent goes.
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


def _find(entries: list[Entry], entry_id: int) -> Entry:
    for entry in entries:
        if entry.id == entry_id:
            return entry
    raise LookupError(f"no Entry {entry_id} on this Daily Log")


def anchor(entries: list[Entry], entry_id: int) -> Entry | None:
    """The Anchor of an Entry: the nearest Timed Entry above it, if it is untimed."""
    found: Entry | None = None
    for entry in arrange_daily_log(entries):
        if entry.id == entry_id:
            return None if entry.time is not None else found
        if entry.time is not None and entry.parent_id is None:
            found = entry
    raise LookupError(f"no Entry {entry_id} on this Daily Log")


def _split_nested(entries: list[Entry]) -> tuple[list[Entry], list[Entry]]:
    """A Daily Log's Entries, given in display order, as those that aren't
    Nested Notes and those that are."""
    return (
        [entry for entry in entries if entry.parent_id is None],
        [entry for entry in entries if entry.parent_id is not None],
    )


def change_time(entries: list[Entry], entry_id: int, *, to: time) -> list[Entry]:
    """Give a Timed Entry a new time; the Entries Anchored to it move with it.

    Returns the Daily Log's Entries in their new order. A Timed Entry moved to
    a time another already has goes after it.
    """
    if _find(entries, entry_id).time is None:
        raise UntimedEntryError("only a Timed Entry's time can be changed")
    unnested, nested = _split_nested(arrange_daily_log(entries))
    top, anchored = _anchored_groups(unnested)
    moving = next(group for group in anchored if group[0].id == entry_id)
    others = [group for group in anchored if group is not moving]
    moved = [replace(moving[0], time=to), *moving[1:]]
    return arrange_daily_log(_in_order(top, [*others, moved]) + nested)


def move_entry(entries: list[Entry], entry_id: int, *, to: int) -> list[Entry]:
    """Move an untimed Entry to index `to` of the rest of the Daily Log, by
    keyboard or drag; its Nested Notes go with it.

    It re-Anchors to whatever Timed Entry ends up above it, and never lands
    between another Entry and its Nested Notes. Returns the Daily Log's
    Entries in their new order.
    """
    moving = _find(entries, entry_id)
    if moving.parent_id is not None:
        raise NestedNoteMoveError("a Nested Note moves only with its parent")
    if moving.time is not None:
        raise TimedEntryMoveError("a Timed Entry moves only by changing its time")
    shown = arrange_daily_log(entries)
    block = [moving, *(entry for entry in shown if entry.parent_id == entry_id)]
    rest = [entry for entry in shown if entry not in block]
    to = max(0, min(to, len(rest)))
    while to < len(rest) and rest[to].parent_id is not None:
        to += 1
    return arrange_daily_log(rest[:to] + block + rest[to:])


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

    Everything the Prefix rules read from text (type, Signifiers, time, text)
    is replaced. The Entry's location, month and day stay, a Task that stays
    a Task keeps its Task State, and a Nested Note stays nested only while it
    is still a Note. An Entry on a Monthly Log's task list cannot become an
    Event, which belongs on a day.
    """
    read = _read_entry(text)
    if read.type is EntryType.EVENT and entry.location is Location.MONTH:
        raise EventNeedsDateError("an Event belongs on a day")
    state: TaskState | None = TaskState.OPEN if read.type is EntryType.TASK else None
    if read.type == entry.type and entry.state is not None:
        state = entry.state
    return replace(
        entry,
        type=read.type,
        state=state,
        priority=read.priority,
        inspiration=read.inspiration,
        time=read.time,
        text=read.text,
        parent_id=entry.parent_id if read.type is EntryType.NOTE else None,
    )


# A month is written as the date of its first day.


def month_of(day: date) -> date:
    """The month a day falls in."""
    return day.replace(day=1)


def next_month(month: date) -> date:
    """The month after a month, rolling December over into January."""
    if month.month == 12:
        return date(month.year + 1, 1, 1)
    return month.replace(month=month.month + 1)


def has_monthly_log(month: date, *, today: date) -> bool:
    """Only the current and past months have a Monthly Log; later ones live in the Future Log."""
    return month_of(month) <= month_of(today)


def _read_entry(text: str) -> ParsedEntry:
    """Read typed text with the Prefix rules, refusing it if no text is left."""
    parsed = read_prefix(text.lstrip())
    text = parsed.text.strip()
    if not text:
        raise BlankEntryError("an Entry needs some text")
    return ParsedEntry(
        type=parsed.type,
        priority=parsed.priority,
        inspiration=parsed.inspiration,
        time=parsed.time,
        text=text,
    )


def _new_entry(
    parsed: ParsedEntry, *, location: Location, day: date | None, month: date | None
) -> NewEntry:
    return NewEntry(
        type=parsed.type,
        state=TaskState.OPEN if parsed.type is EntryType.TASK else None,
        priority=parsed.priority,
        inspiration=parsed.inspiration,
        time=parsed.time,
        text=parsed.text,
        day=day,
        location=location,
        month=month,
    )


def log_month_entry(text: str, *, month: date, today: date) -> NewEntry:
    """Turn text typed into a Monthly Log into an Entry on that month's task list."""
    month = month_of(month)
    if not has_monthly_log(month, today=today):
        raise NoMonthlyLogError("months after the current one have no Monthly Log")
    parsed = _read_entry(text)
    if parsed.type is EntryType.EVENT:
        raise EventNeedsDateError("an Event belongs on a day")
    return _new_entry(parsed, location=Location.MONTH, day=None, month=month)


def log_future_entry(
    text: str, *, month: date, today: date, on: date | None = None
) -> NewEntry:
    """Turn text typed into the Future Log into an Entry under a later month.

    It may carry a specific date in that month. An Event's date is optional
    here, the only place it is.
    """
    month = month_of(month)
    if has_monthly_log(month, today=today):
        raise NotAFutureMonthError("the Future Log holds months after the current one")
    if on is not None and month_of(on) != month:
        raise DateOutsideMonthError("a Future Log date must fall in its month")
    return _new_entry(_read_entry(text), location=Location.FUTURE, day=on, month=month)


@dataclass(frozen=True)
class CalendarDay:
    """One day of a Monthly Log's calendar."""

    day: date
    events: list[Entry]


def monthly_calendar(month: date, entries: list[Entry]) -> list[CalendarDay]:
    """A Monthly Log's calendar: every day of the month with the Events on its Daily Log.

    It is derived from Daily Log Entries, given in the order they were logged,
    so nothing is entered twice.
    """
    month = month_of(month)
    by_day: dict[date, list[Entry]] = {}
    for entry in entries:
        if (
            entry.type is EntryType.EVENT
            and entry.location is Location.DAY
            and entry.day is not None
            and month_of(entry.day) == month
        ):
            by_day.setdefault(entry.day, []).append(entry)
    days = (next_month(month) - month).days
    return [
        CalendarDay(day=day, events=daily_log_order(by_day.get(day, [])))
        for day in (month + timedelta(days=n) for n in range(days))
    ]


@dataclass(frozen=True)
class FutureMonth:
    """One month's bucket in the Future Log."""

    month: date
    entries: list[Entry]


FUTURE_LOG_MONTHS = 6  # buckets always shown, so the next months can be planned


def future_log(entries: list[Entry], *, today: date) -> list[FutureMonth]:
    """The Future Log: Entries, given in the order they were logged, grouped by month.

    It shows the next few months even when empty, plus any later month with
    Entries. Months that have arrived are left out, since they now have a
    Monthly Log. In each month, dated Entries come first, in date order.
    """
    first = next_month(month_of(today))
    by_month: dict[date, list[Entry]] = {}
    month = first
    for _ in range(FUTURE_LOG_MONTHS):
        by_month[month] = []
        month = next_month(month)
    for entry in entries:
        if (
            entry.location is Location.FUTURE
            and entry.month is not None
            and entry.month >= first
        ):
            by_month.setdefault(entry.month, []).append(entry)
    return [
        FutureMonth(
            month=month,
            entries=sorted(by_month[month], key=lambda e: (e.day is None, e.day or month)),
        )
        for month in sorted(by_month)
    ]


def daily_log_day(entry: Entry) -> date:
    """The day of the Daily Log an Entry is on."""
    if entry.location is not Location.DAY or entry.day is None:
        raise NotOnADailyLogError("this Entry is not on a Daily Log")
    return entry.day
