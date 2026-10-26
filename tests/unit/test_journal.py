from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from dots_and_dashes import journal


def test_text_logged_on_a_day_becomes_an_open_task_on_that_day():
    entry = journal.log_entry("buy milk", on=date(2026, 10, 25))

    assert entry == journal.NewEntry(
        type=journal.EntryType.TASK,
        state=journal.TaskState.OPEN,
        priority=False,
        inspiration=False,
        time=None,
        text="buy milk",
        day=date(2026, 10, 25),
    )


def test_a_logged_entry_takes_its_signifiers_type_and_time_from_the_prefix():
    entry = journal.log_entry("*!o 7pm dinner", on=date(2026, 10, 25))

    assert entry == journal.NewEntry(
        type=journal.EntryType.EVENT,
        state=None,
        priority=True,
        inspiration=True,
        time=time(19, 0),
        text="dinner",
        day=date(2026, 10, 25),
    )


@pytest.mark.parametrize("text", ["- idea", "!- idea"])
def test_only_tasks_have_a_task_state(text):
    assert journal.log_entry(text, on=date(2026, 10, 25)).state is None


def test_whitespace_around_logged_text_is_not_part_of_the_entry():
    entry = journal.log_entry("  buy milk \n", on=date(2026, 10, 25))

    assert entry.text == "buy milk"


@pytest.mark.parametrize("text", ["", "   ", "\n\t", ". ", "*! ", "o 9am", "*!- 14:00  "])
def test_blank_text_cannot_be_logged(text):
    with pytest.raises(journal.BlankEntryError):
        journal.log_entry(text, on=date(2026, 10, 25))


def test_today_is_the_date_in_the_users_timezone():
    now = datetime(2026, 10, 26, 3, 0, tzinfo=UTC)

    assert journal.today(now, ZoneInfo("America/Los_Angeles")) == date(2026, 10, 25)
    assert journal.today(now, ZoneInfo("Asia/Manila")) == date(2026, 10, 26)


@pytest.mark.parametrize(
    ("text", "type", "rest"),
    [
        (". buy milk", journal.EntryType.TASK, "buy milk"),
        ("o dinner with Sam", journal.EntryType.EVENT, "dinner with Sam"),
        ("- the cafe opens at 7", journal.EntryType.NOTE, "the cafe opens at 7"),
        ("buy milk", journal.EntryType.TASK, "buy milk"),
    ],
)
def test_the_prefix_sets_the_entry_type(text, type, rest):
    parsed = journal.read_prefix(text)

    assert (parsed.type, parsed.text) == (type, rest)


@pytest.mark.parametrize("text", [".5 miles run", "oatmeal", "-3 degrees"])
def test_a_type_character_without_a_trailing_space_is_just_text(text):
    parsed = journal.read_prefix(text)

    assert (parsed.type, parsed.text) == (journal.EntryType.TASK, text)


@pytest.mark.parametrize(
    ("text", "priority", "inspiration", "type"),
    [
        ("*. call mom", True, False, journal.EntryType.TASK),
        ("!- call mom", False, True, journal.EntryType.NOTE),
        ("*!o call mom", True, True, journal.EntryType.EVENT),
        ("!*. call mom", True, True, journal.EntryType.TASK),
        (". call mom", False, False, journal.EntryType.TASK),
        ("call mom", False, False, journal.EntryType.TASK),
    ],
)
def test_signifiers_before_the_type_mark_priority_and_inspiration(
    text, priority, inspiration, type
):
    parsed = journal.read_prefix(text)

    assert (parsed.priority, parsed.inspiration, parsed.type, parsed.text) == (
        priority,
        inspiration,
        type,
        "call mom",
    )


@pytest.mark.parametrize(
    ("text", "priority", "inspiration"),
    [("* call mom", True, False), ("*! call mom", True, True)],
)
def test_signifiers_without_a_type_mark_a_task(text, priority, inspiration):
    parsed = journal.read_prefix(text)

    assert (parsed.priority, parsed.inspiration, parsed.type, parsed.text) == (
        priority,
        inspiration,
        journal.EntryType.TASK,
        "call mom",
    )


def test_signifiers_without_a_trailing_space_are_just_text():
    parsed = journal.read_prefix("*nix tips")

    assert (parsed.priority, parsed.text) == (False, "*nix tips")


@pytest.mark.parametrize(
    ("text", "at"),
    [
        (". 14:00 call mom", time(14, 0)),
        (". 09:05 call mom", time(9, 5)),
        (". 9:05 call mom", time(9, 5)),
        ("o 9am call mom", time(9, 0)),
        ("o 7pm call mom", time(19, 0)),
        ("o 2:30pm call mom", time(14, 30)),
        ("o 2:30PM call mom", time(14, 30)),
        ("o 12am call mom", time(0, 0)),
        ("o 12pm call mom", time(12, 0)),
        ("*!o 00:00 call mom", time(0, 0)),
    ],
)
def test_a_time_right_after_the_type_makes_a_timed_entry(text, at):
    parsed = journal.read_prefix(text)

    assert (parsed.time, parsed.text) == (at, "call mom")


@pytest.mark.parametrize(
    "text",
    [
        ". 24:00 call mom",
        ". 14:60 call mom",
        ". 13pm call mom",
        ". 0am call mom",
        ". 2:75pm call mom",
        ". 1400 call mom",
        ". 14:00call mom",
    ],
)
def test_an_invalid_time_is_part_of_the_text(text):
    parsed = journal.read_prefix(text)

    assert (parsed.time, parsed.text) == (None, text.removeprefix(". "))


@pytest.mark.parametrize("text", ["14:00 call mom", "9am call mom"])
def test_a_time_without_a_prefix_is_part_of_the_text(text):
    parsed = journal.read_prefix(text)

    assert (parsed.type, parsed.time, parsed.text) == (journal.EntryType.TASK, None, text)


def test_untimed_entries_have_no_time():
    assert journal.read_prefix(". call mom").time is None


def _stored(id: int, text: str, at: time | None = None) -> journal.Entry:
    return journal.Entry(
        id=id,
        type=journal.EntryType.TASK,
        state=journal.TaskState.OPEN,
        priority=False,
        inspiration=False,
        time=at,
        text=text,
        day=date(2026, 10, 25),
    )


def _texts(entries: list[journal.Entry]) -> list[str]:
    return [entry.text for entry in entries]


def test_timed_entries_on_a_daily_log_are_in_chronological_order():
    logged = [
        _stored(1, "dinner", time(19, 0)),
        _stored(2, "standup", time(9, 30)),
        _stored(3, "lunch", time(12, 0)),
    ]

    assert _texts(journal.daily_log_order(logged)) == ["standup", "lunch", "dinner"]


def test_untimed_entries_logged_before_any_timed_entry_stay_at_the_top():
    logged = [
        _stored(1, "buy milk"),
        _stored(2, "dinner", time(19, 0)),
        _stored(3, "standup", time(9, 30)),
    ]

    assert _texts(journal.daily_log_order(logged)) == ["buy milk", "standup", "dinner"]


def test_an_untimed_entry_stays_after_its_anchor():
    logged = [
        _stored(1, "dinner", time(19, 0)),
        _stored(2, "book a table"),
        _stored(3, "standup", time(9, 30)),
        _stored(4, "prep notes"),
        _stored(5, "bring slides"),
    ]

    assert _texts(journal.daily_log_order(logged)) == [
        "standup",
        "prep notes",
        "bring slides",
        "dinner",
        "book a table",
    ]


def test_timed_entries_at_the_same_time_keep_the_order_they_were_logged():
    logged = [_stored(1, "call mom", time(9, 0)), _stored(2, "call dad", time(9, 0))]

    assert _texts(journal.daily_log_order(logged)) == ["call mom", "call dad"]
