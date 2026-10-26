"""The Journal domain module: every bullet journal rule, with no I/O."""

from dataclasses import dataclass, fields, replace
from datetime import date, datetime, tzinfo
from enum import StrEnum


class EntryType(StrEnum):
    TASK = "task"


class TaskState(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class BlankEntryError(ValueError):
    """Raised when there is no text to log."""


class TaskStateError(ValueError):
    """Raised when an Entry cannot move to the Task State asked for."""


@dataclass(frozen=True)
class NewEntry:
    """An Entry that has been logged but not yet stored."""

    type: EntryType
    state: TaskState | None  # only Tasks have a Task State
    text: str
    day: date


@dataclass(frozen=True)
class Entry:
    """A stored Entry on a Daily Log."""

    id: int
    type: EntryType
    state: TaskState | None  # only Tasks have a Task State
    text: str
    day: date


def log_entry(text: str, *, on: date) -> NewEntry:
    """Turn text typed into a Daily Log's input box into an Entry on that day."""
    text = text.strip()
    if not text:
        raise BlankEntryError("an Entry needs some text")
    return NewEntry(type=EntryType.TASK, state=TaskState.OPEN, text=text, day=on)


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

    Editing offers this text, so it must spell out the Prefix (type,
    Signifiers, time) that log_entry would read back into the same Entry.
    """
    return entry.text


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
