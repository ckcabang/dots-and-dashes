"""The Journal domain module: every bullet journal rule, with no I/O."""

import re
from collections.abc import Callable, Mapping
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
    MIGRATED = "migrated"
    SCHEDULED = "scheduled"
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
    # The copy this one was migrated or scheduled from, in its Migration Chain.
    migrated_from_id: int | None = None


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
    # The copy this one was migrated or scheduled from, in its Migration Chain.
    migrated_from_id: int | None = None
    # Its Migration Chain's Migration Count, worked out when it is loaded.
    migration_count: int = 0


def log_entry(text: str, *, on: date) -> NewEntry:
    """Turn text typed into a Daily Log's input box into an Entry on that day."""
    return _new_entry(_read_entry(text), location=Location.DAY, day=on, month=None)


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
    return _with_nested_notes(entries, daily_log_order)


def place_on_daily_log(entry: Entry, daily_log: list[Entry]) -> list[Entry]:
    """Put an Entry logged or moved onto a Daily Log, given the Entries already there.

    It goes to the bottom of the manual order, so an untimed Entry ends up
    last and a Timed Entry slots in by its time. Returns the Daily Log in its
    new order, to store as its manual order.
    """
    return arrange_daily_log([*daily_log, entry])


def arrange_task_list(entries: list[Entry]) -> list[Entry]:
    """Lay out a Monthly Log's task list, given in the order its Entries were logged.

    Entries stay in logged order, each with its Nested Notes under it.
    """
    return _with_nested_notes(entries, list)


def _with_nested_notes(
    entries: list[Entry], order: Callable[[list[Entry]], list[Entry]]
) -> list[Entry]:
    """Order the Entries that aren't Nested Notes, then put each Nested Note under its parent.

    A Nested Note whose parent isn't among the Entries is left out.
    """
    nested: dict[int, list[Entry]] = {}
    for entry in entries:
        if entry.parent_id is not None:
            nested.setdefault(entry.parent_id, []).append(entry)
    ordered = order([entry for entry in entries if entry.parent_id is None])
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
    raise LookupError(f"no Entry {entry_id} here")


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


def is_draggable(entry: Entry) -> bool:
    """Whether an Entry is reordered by keyboard or drag: an untimed one on a
    Daily Log that isn't a Nested Note. The others move with their time or parent."""
    return entry.location is Location.DAY and entry.time is None and entry.parent_id is None


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


def as_typed(entry: Entry | ParsedEntry) -> str:
    """The Entry as it would be typed: the inverse of reading text with log_entry.

    Editing offers this text, and Triage offers its suggestion this way, so it
    spells out the Prefix (Signifiers, type, time) that log_entry reads back
    into the same Entry. A plain untimed Task
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


def notes_released_by_edit(edited: Entry, nested_notes: list[Entry]) -> list[Entry]:
    """The Nested Notes an edit lets stand alone, to store: all of them if the
    edit made their parent a Note, since Notes don't nest under Notes."""
    if edited.type is not EntryType.NOTE:
        return []
    return [un_nest_note(note) for note in nested_notes]


# A month is written as the date of its first day.


def month_of(day: date) -> date:
    """The month a day falls in."""
    return day.replace(day=1)


def next_month(month: date) -> date:
    """The month after a month, rolling December over into January."""
    if month.month == 12:
        return date(month.year + 1, 1, 1)
    return month.replace(month=month.month + 1)


def previous_month(month: date) -> date:
    """The month before a month, rolling January back into December."""
    return month_of(month_of(month) - timedelta(days=1))


def has_monthly_log(month: date, *, today: date) -> bool:
    """Only the current and past months have a Monthly Log; later ones live in the Future Log."""
    return month_of(month) <= month_of(today)


def _read_entry(text: str) -> ParsedEntry:
    """Read typed text with the Prefix rules, refusing it if no text is left."""
    # Only leading whitespace goes before the Prefix is read: a trailing space
    # is what makes ". " a Prefix with no text rather than a Task called ".".
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
        FutureMonth(month=month, entries=_in_future_log_order(by_month[month], month))
        for month in sorted(by_month)
    ]


def _in_future_log_order(entries: list[Entry], month: date) -> list[Entry]:
    """A Future Log month's Entries: dated ones first, in date order, each with
    its Nested Notes under it."""
    return _with_nested_notes(
        entries, lambda unnested: sorted(unnested, key=lambda e: (e.day is None, e.day or month))
    )


def daily_log_day(entry: Entry) -> date:
    """The day of the Daily Log an Entry is on."""
    if entry.location is not Location.DAY or entry.day is None:
        raise NotOnADailyLogError("this Entry is not on a Daily Log")
    return entry.day


# Migration and Scheduling (ADR-0001): a Task moves forward by being copied.
# The original stays where it is, marked Migrated or Scheduled, and a new Open
# copy at the destination links back to it.


class MigrationError(ValueError):
    """Raised when an Entry cannot be migrated or scheduled where it was asked to go."""


@dataclass(frozen=True)
class Destination:
    """Where a Task is migrated or scheduled to."""

    location: Location
    day: date | None = None
    month: date | None = None

    @classmethod
    def daily_log(cls, day: date) -> "Destination":
        return cls(Location.DAY, day=day)

    @classmethod
    def monthly_log(cls, month: date) -> "Destination":
        """A month's task list."""
        return cls(Location.MONTH, month=month_of(month))

    @classmethod
    def future_log(cls, month: date, on: date | None = None) -> "Destination":
        """A later month in the Future Log, optionally on a specific date."""
        return cls(Location.FUTURE, day=on, month=month_of(month))


@dataclass(frozen=True)
class Migration:
    """A Task moved forward: the original, now marked, and its Open copy to store."""

    original: Entry
    copy: NewEntry


# Migrating from this local time until midnight is the night before, planning
# tomorrow; from midnight until then it is the morning, planning today.
EVENING_STARTS = time(18, 0)


def is_night_before(now: datetime, timezone: tzinfo) -> bool:
    """Whether Migrating now is the night before: from 18:00 local time."""
    return now.astimezone(timezone).time() >= EVENING_STARTS


@dataclass(frozen=True)
class Planning:
    """The day being planned, and whether that makes it the night before."""

    day: date
    night_before: bool


def daily_migration_planning(
    now: datetime, timezone: tzinfo, *, night_before: bool | None = None
) -> Planning:
    """The day a Migration done now plans: tomorrow in the evening, otherwise today.

    The User can choose the other day by saying whether it is the night before.
    """
    if night_before is None:
        night_before = is_night_before(now, timezone)
    planning = today(now, timezone)
    return Planning(
        day=planning + timedelta(days=1) if night_before else planning,
        night_before=night_before,
    )


def migrate(task: Entry, *, to: Destination, planning: date) -> Migration:
    """Migrate or Schedule an Open Task to a destination.

    The destination decides which, given the day being planned (see
    daily_migration_planning): that day or its month's task list Migrates the
    Task (>), and a later day that month or a later month in the Future Log
    Schedules it (<). The copy keeps the Task's text, Signifiers and time. A
    Task only moves forward, so one on a Daily Log never moves to an earlier one.
    """
    if task.type is not EntryType.TASK:
        raise MigrationError("only Tasks are migrated or scheduled")
    if task.state is not TaskState.OPEN:
        raise TaskStateError(f"a {task.state} Task cannot be migrated or scheduled")
    if (task.location, task.day, task.month) == (to.location, to.day, to.month):
        raise MigrationError("the Task is already there")
    if (
        task.location is Location.DAY
        and to.location is Location.DAY
        and task.day is not None
        and to.day is not None
        and to.day < task.day
    ):
        raise MigrationError("a Task cannot move back to an earlier day")
    state = _marker_for(to, planning=planning)
    return Migration(original=replace(task, state=state), copy=_open_copy(task, to=to))


def _open_copy(task: Entry, *, to: Destination) -> NewEntry:
    """A Task's new Open copy at a destination, keeping its text, Signifiers and time."""
    return NewEntry(
        type=task.type,
        state=TaskState.OPEN,
        priority=task.priority,
        inspiration=task.inspiration,
        time=task.time,
        text=task.text,
        day=to.day,
        location=to.location,
        month=to.month,
        migrated_from_id=task.id,
    )


def _marker_for(to: Destination, *, planning: date) -> TaskState:
    """Migrated or Scheduled, for a Task moving to a destination."""
    this_month = month_of(planning)
    if to.location is Location.DAY and to.day is not None:
        if to.day < planning:
            raise MigrationError("a Task cannot move to a day before the one being planned")
        if month_of(to.day) != this_month:
            raise MigrationError("a later month's Tasks go in the Future Log")
        return TaskState.MIGRATED if to.day == planning else TaskState.SCHEDULED
    if to.location is Location.MONTH and to.month is not None:
        if to.month != this_month:
            raise MigrationError("a Task migrates only to the current month's task list")
        return TaskState.MIGRATED
    if to.location is Location.FUTURE and to.month is not None:
        if to.month <= this_month:
            raise MigrationError("the Future Log holds months after the current one")
        if to.day is not None and month_of(to.day) != to.month:
            raise MigrationError("a Future Log date must fall in its month")
        return TaskState.SCHEDULED
    raise MigrationError("a destination needs a day or a month")


def schedule_destination(day: date, *, planning: date) -> Destination:
    """Where a Task scheduled to a date goes: that day's Daily Log if it is in the
    month being planned, or else the Future Log under its month, on that date."""
    if month_of(day) == month_of(planning):
        return Destination.daily_log(day)
    return Destination.future_log(month_of(day), on=day)


def move_nested_notes(notes: list[Entry], *, to: Entry) -> list[Entry]:
    """Re-parent a migrated Task's Nested Notes onto its new copy, wherever it is."""
    return [
        replace(note, parent_id=to.id, location=to.location, day=to.day, month=to.month)
        for note in notes
    ]


def migration_count(entry_id: int, links: Mapping[int, int | None]) -> int:
    """How many times a Task was migrated or scheduled: its Migration Chain's moves.

    links maps each copy's id to the id it was migrated from. Every copy in a
    chain shows the same count, so a Task's history reads the same anywhere.
    """
    successors = {earlier: later for later, earlier in links.items() if earlier is not None}
    count, at = 0, entry_id
    while (earlier := links.get(at)) is not None:
        count, at = count + 1, earlier
    at = entry_id
    while (later := successors.get(at)) is not None:
        count, at = count + 1, later
    return count


def relink_around(deleted: Entry, successor: Entry) -> Entry:
    """Close the gap a Deleted copy leaves: its successor now follows the copy before it."""
    return replace(successor, migrated_from_id=deleted.migrated_from_id)


def delete_entry(
    entry: Entry, *, successor: Entry | None, nested_notes: list[Entry]
) -> list[Entry]:
    """Delete an Entry: the Entries that pointed at it, changed to store first.

    Its Nested Notes stand alone again, and the copy migrated or scheduled
    from it re-links to the copy before it, closing the Migration Chain.
    """
    changed = [un_nest_note(note) for note in nested_notes]
    if successor is not None:
        changed.append(relink_around(entry, successor))
    return changed


def move_event(event: Entry, nested_notes: list[Entry], *, on: date) -> tuple[Entry, list[Entry]]:
    """Move an Event on a Daily Log to another day, with its Nested Notes.

    An Event just changes its date: it leaves no marker and no Migration Chain.
    """
    if event.type is not EntryType.EVENT:
        raise MigrationError("only an Event moves by changing its date")
    daily_log_day(event)
    return _onto_daily_log(event, on), [_onto_daily_log(note, on) for note in nested_notes]


def _onto_daily_log(entry: Entry, day: date) -> Entry:
    return replace(entry, location=Location.DAY, day=day, month=None)


# Daily Migration: reviewing the Open Tasks left on earlier days, to complete,
# migrate, schedule or cancel each. It is optional: nothing happens to a Task
# until it is decided, so it can be skipped and done any time later.


@dataclass(frozen=True)
class AnchorGroup:
    """Open Tasks sharing an Anchor; None for the untimed ones at the top of a day."""

    anchor: Entry | None
    tasks: list[Entry]


@dataclass(frozen=True)
class MigrationDay:
    """An earlier day's Open Tasks, grouped under their Anchors in Daily Log order."""

    day: date
    groups: list[AnchorGroup]


def _is_open_task(entry: Entry) -> bool:
    return entry.type is EntryType.TASK and entry.state is TaskState.OPEN


def daily_migration(entries: list[Entry], *, planning: date) -> list[MigrationDay]:
    """The Open Tasks a Daily Migration reviews: those on every Daily Log before
    the day being planned, oldest day first.

    Entries are given in each Daily Log's manual order. Each day's Open Tasks
    are grouped under their Anchor, so a missed block is dealt with together;
    an Open Timed Task leads its own group.
    """
    by_day: dict[date, list[Entry]] = {}
    for entry in entries:
        if entry.location is Location.DAY and entry.day is not None and entry.day < planning:
            by_day.setdefault(entry.day, []).append(entry)
    review = []
    for day in sorted(by_day):
        groups: list[AnchorGroup] = []
        for entry in arrange_daily_log(by_day[day]):
            if not _is_open_task(entry):
                continue
            leader = entry if entry.time is not None else anchor(by_day[day], entry.id)
            if groups and groups[-1].anchor == leader:
                groups[-1].tasks.append(entry)
            else:
                groups.append(AnchorGroup(anchor=leader, tasks=[entry]))
        if groups:
            review.append(MigrationDay(day=day, groups=groups))
    return review


# Monthly Review: the ritual on the first of the month, dealing with last
# month's leftover Open Tasks and pulling this month's Future Log Entries into
# the new Monthly Log. Like Daily Migration it is about the User's current
# month, so it still works when opened after the first.


@dataclass(frozen=True)
class LeftoverDay:
    """A Daily Log of last month and its Open Tasks, in Daily Log order."""

    day: date
    tasks: list[Entry]


@dataclass(frozen=True)
class WaitingEvent:
    """An undated Future Log Event, with its Nested Notes, waiting for a day:
    an Event belongs on a day, so the pull can't bring it in without one."""

    event: Entry
    notes: list[Entry]


@dataclass(frozen=True)
class MonthlyReview:
    """The month being set up, last month's Open Tasks still to decide, and
    this month's Future Log Entries still to bring in."""

    month: date
    task_list: list[Entry]  # left on last month's task list
    days: list[LeftoverDay]  # left on last month's Daily Logs, oldest day first
    # What the pull brings in, in Future Log order with Nested Notes.
    to_pull: list[Entry]
    needs_a_date: list[WaitingEvent]

    @property
    def last_day(self) -> date:
        return next_month(self.month) - timedelta(days=1)


def monthly_review(entries: list[Entry], *, today: date) -> MonthlyReview:
    """The Monthly Review of the User's current month.

    Entries are given in each Daily Log's manual order, and the task list's
    and Future Log's in the order they were logged. Each leftover is
    completed, migrated, scheduled or cancelled like any Open Task, which
    takes it off the review.
    """
    month = month_of(today)
    last_month = previous_month(month)
    task_list: list[Entry] = []
    by_day: dict[date, list[Entry]] = {}
    for entry in entries:
        if entry.location is Location.MONTH and entry.month == last_month:
            task_list.append(entry)
        elif (
            entry.location is Location.DAY
            and entry.day is not None
            and month_of(entry.day) == last_month
        ):
            by_day.setdefault(entry.day, []).append(entry)
    days = [
        LeftoverDay(day=day, tasks=tasks)
        for day in sorted(by_day)
        if (tasks := [e for e in arrange_daily_log(by_day[day]) if _is_open_task(e)])
    ]
    to_pull, needs_a_date = _waiting_in_future_log(entries, month)
    return MonthlyReview(
        month=month,
        task_list=[e for e in arrange_task_list(task_list) if _is_open_task(e)],
        days=days,
        to_pull=to_pull,
        needs_a_date=needs_a_date,
    )


def _waiting_in_future_log(
    entries: list[Entry], month: date
) -> tuple[list[Entry], list[WaitingEvent]]:
    """A month's Future Log Entries not yet pulled into its Monthly Log, in
    Future Log order: Open Tasks, Events and Notes, with their Nested Notes.
    Decided Tasks stay behind. Split into those the pull brings in and the
    undated Events that wait for a day."""
    waiting = _in_future_log_order(
        [
            entry
            for entry in entries
            if entry.location is Location.FUTURE
            and entry.month == month
            and (entry.type is not EntryType.TASK or entry.state is TaskState.OPEN)
        ],
        month,
    )
    undated = {e.id for e in waiting if e.type is EntryType.EVENT and e.day is None}
    to_pull = [e for e in waiting if e.id not in undated and e.parent_id not in undated]
    needs_a_date = [
        WaitingEvent(event=e, notes=[n for n in waiting if n.parent_id == e.id])
        for e in waiting
        if e.id in undated
    ]
    return to_pull, needs_a_date


@dataclass(frozen=True)
class Pull:
    """This month's Future Log brought into its Monthly Log.

    Tasks are copied (ADR-0001), each original marked Migrated; their Nested
    Notes move onto the copy with move_nested_notes once it is stored. Events
    and Notes have no Task State, so they move, Nested Notes and all.
    """

    migrations: list[Migration]
    moved: list[Entry]


def pull_from_future_log(entries: list[Entry], *, today: date) -> Pull:
    """Pull the User's current month's Future Log Entries into its Monthly Log.

    A dated Entry lands on its day's Daily Log and an undated one on the
    month's task list, except an undated Event, which waits for a day. When
    the review is opened after the first, a Task dated a day already past
    lands on today's Daily Log, since a Task only moves forward. Pulled
    Entries leave the Future Log, so pulling again brings in nothing more.
    """
    month = month_of(today)
    to_pull, _ = _waiting_in_future_log(entries, month)
    migrations: list[Migration] = []
    moved: list[Entry] = []
    for entry in to_pull:
        if entry.parent_id is not None:
            continue  # it moves with its parent
        if entry.type is EntryType.TASK:
            on = None if entry.day is None else max(entry.day, today)
            to = Destination.daily_log(on) if on else Destination.monthly_log(month)
            original = replace(entry, state=TaskState.MIGRATED)
            migrations.append(Migration(original=original, copy=_open_copy(entry, to=to)))
        elif entry.day is not None:
            notes = [note for note in to_pull if note.parent_id == entry.id]
            moved += [_onto_daily_log(e, entry.day) for e in [entry, *notes]]
        else:
            moved.append(replace(entry, location=Location.MONTH, month=month))
    return Pull(migrations=migrations, moved=moved)


def date_waiting_event(
    event: Entry, nested_notes: list[Entry], *, on: date, today: date
) -> tuple[Entry, list[Entry]]:
    """Give an undated Event waiting in the Monthly Review a day this month,
    moving it and its Nested Notes onto that day's Daily Log."""
    month = month_of(today)
    if not (
        event.type is EntryType.EVENT
        and event.location is Location.FUTURE
        and event.month == month
        and event.day is None
    ):
        raise MigrationError("only an undated Event waiting in the Monthly Review needs a day")
    if month_of(on) != month:
        raise DateOutsideMonthError("a waiting Event goes on a day this month")
    return _onto_daily_log(event, on), [_onto_daily_log(note, on) for note in nested_notes]


# Captures and Triage: on the go, raw text is jotted down as a Capture in the
# Inbox, unclassified. A Capture is not an Entry; it becomes one only through
# Triage, which reads its text with the Prefix rules and places it.


class BlankCaptureError(ValueError):
    """Raised when there is no text to capture."""


@dataclass(frozen=True)
class NewCapture:
    """A Capture jotted down but not yet stored."""

    text: str


@dataclass(frozen=True)
class Capture:
    """A stored Capture: raw text waiting in the Inbox."""

    id: int
    text: str


def capture(text: str) -> NewCapture:
    """Keep text jotted down on the go as a Capture: raw, exactly as typed,
    and unclassified until Triage."""
    if not text.strip():
        raise BlankCaptureError("a Capture needs some text")
    return NewCapture(text=text)


def triage_suggestion(capture: Capture) -> ParsedEntry:
    """What Triage suggests a Capture becomes: its text read with the Prefix
    rules, so a Prefix typed on the go isn't wasted. No Prefix suggests a Task."""
    return _read_entry(capture.text)


def triage(
    capture: Capture, *, to: Destination, today: date, text: str | None = None
) -> NewEntry:
    """Turn a Capture into an Entry at a destination: a day's Daily Log, the
    current month's task list, or a later month in the Future Log, optionally
    on a date.

    Its text is read with the Prefix rules, as triage_suggestion suggests;
    text adjusts the suggestion, written the same way. The destination's own
    rules apply, as for an Entry logged there.
    """
    text = capture.text if text is None else text
    if to.location is Location.DAY and to.day is not None:
        return log_entry(text, on=to.day)
    if to.location is Location.MONTH and to.month == month_of(today):
        return log_month_entry(text, month=to.month, today=today)
    if to.location is Location.FUTURE and to.month is not None:
        return log_future_entry(text, month=to.month, today=today, on=to.day)
    raise PlacementError("a Capture goes on a Daily Log, the Monthly Log or the Future Log")
