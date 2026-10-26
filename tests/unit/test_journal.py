from dataclasses import replace
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from dots_and_dashes import journal


def test_text_logged_on_a_day_becomes_an_open_task_on_that_day():
    entry = journal.log_entry("buy milk", on=date(2026, 10, 25))

    assert entry == journal.NewEntry(
        type=journal.EntryType.TASK,
        state=journal.TaskState.OPEN,
        text="buy milk",
        day=date(2026, 10, 25),
    )


def test_whitespace_around_logged_text_is_not_part_of_the_entry():
    entry = journal.log_entry("  buy milk \n", on=date(2026, 10, 25))

    assert entry.text == "buy milk"


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_blank_text_cannot_be_logged(text):
    with pytest.raises(journal.BlankEntryError):
        journal.log_entry(text, on=date(2026, 10, 25))


def test_today_is_the_date_in_the_users_timezone():
    now = datetime(2026, 10, 26, 3, 0, tzinfo=UTC)

    assert journal.today(now, ZoneInfo("America/Los_Angeles")) == date(2026, 10, 25)
    assert journal.today(now, ZoneInfo("Asia/Manila")) == date(2026, 10, 26)


def _open_task(text: str = "buy milk") -> journal.Entry:
    return journal.Entry(
        id=7,
        type=journal.EntryType.TASK,
        state=journal.TaskState.OPEN,
        text=text,
        day=date(2026, 10, 25),
    )


def test_completing_an_open_task_marks_it_completed():
    completed = journal.complete(_open_task())

    assert completed == replace(_open_task(), state=journal.TaskState.COMPLETED)


def test_cancelling_an_open_task_marks_it_cancelled():
    cancelled = journal.cancel(_open_task())

    assert cancelled == replace(_open_task(), state=journal.TaskState.CANCELLED)


@pytest.mark.parametrize("act", [journal.complete, journal.cancel])
def test_a_completed_or_cancelled_task_can_be_reopened(act):
    reopened = journal.reopen(act(_open_task()))

    assert reopened == _open_task()


def test_an_open_task_cannot_be_reopened():
    with pytest.raises(journal.TaskStateError):
        journal.reopen(_open_task())


@pytest.mark.parametrize(
    ("first", "then"),
    [
        (journal.complete, journal.complete),
        (journal.complete, journal.cancel),
        (journal.cancel, journal.cancel),
        (journal.cancel, journal.complete),
    ],
)
def test_only_an_open_task_can_be_completed_or_cancelled(first, then):
    with pytest.raises(journal.TaskStateError):
        then(first(_open_task()))


@pytest.mark.parametrize("act", [journal.complete, journal.cancel, journal.reopen])
def test_an_entry_without_a_task_state_cannot_change_state(act):
    # Only Tasks have a Task State; Events and Notes have none.
    stateless = replace(_open_task(), state=None)

    with pytest.raises(journal.TaskStateError):
        act(stateless)


def test_editing_an_entry_replaces_its_text_and_keeps_its_place():
    edited = journal.edit_entry(_open_task("buy milk"), "  buy oat milk ")

    assert edited == _open_task("buy oat milk")


def test_editing_a_task_keeps_its_task_state():
    edited = journal.edit_entry(journal.complete(_open_task()), "buy oat milk")

    assert edited.state == journal.TaskState.COMPLETED


def test_an_entry_cannot_be_edited_to_blank():
    with pytest.raises(journal.BlankEntryError):
        journal.edit_entry(_open_task(), "  ")


def test_an_entry_is_offered_for_editing_as_it_would_be_typed():
    # Editing re-reads the text with the Prefix rules, so typing back what
    # is offered leaves the Entry unchanged.
    entry = journal.complete(_open_task("buy milk"))

    assert journal.edit_entry(entry, journal.as_typed(entry)) == entry
