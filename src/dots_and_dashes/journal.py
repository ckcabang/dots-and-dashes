"""The Journal domain module: every bullet journal rule, with no I/O."""

from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from enum import StrEnum


class EntryType(StrEnum):
    TASK = "task"


class TaskState(StrEnum):
    OPEN = "open"


class BlankEntryError(ValueError):
    """Raised when there is no text to log."""


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
