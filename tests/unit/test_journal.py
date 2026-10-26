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


@pytest.mark.parametrize(
    ("month", "has_one"),
    [
        (date(2026, 10, 1), True),
        (date(2025, 3, 1), True),
        (date(2026, 11, 1), False),
        (date(2027, 1, 1), False),
    ],
)
def test_only_the_current_and_past_months_have_a_monthly_log(month, has_one):
    assert journal.has_monthly_log(month, today=date(2026, 10, 25)) is has_one


def test_in_december_january_is_the_first_month_of_the_future_log():
    today = date(2026, 12, 31)

    assert journal.has_monthly_log(date(2026, 12, 1), today=today)
    assert not journal.has_monthly_log(date(2027, 1, 1), today=today)
    assert journal.next_month(date(2026, 12, 1)) == date(2027, 1, 1)


def test_text_logged_on_a_monthly_log_goes_on_that_months_task_list():
    entry = journal.log_month_entry(
        "*. renew passport", month=date(2026, 10, 1), today=date(2026, 10, 25)
    )

    assert entry == journal.NewEntry(
        type=journal.EntryType.TASK,
        state=journal.TaskState.OPEN,
        priority=True,
        inspiration=False,
        time=None,
        text="renew passport",
        day=None,
        location=journal.Location.MONTH,
        month=date(2026, 10, 1),
    )


def test_a_past_months_task_list_can_take_entries():
    entry = journal.log_month_entry(
        "- look back", month=date(2026, 9, 1), today=date(2026, 10, 25)
    )

    assert (entry.location, entry.month) == (journal.Location.MONTH, date(2026, 9, 1))


def test_a_month_after_the_current_one_has_no_task_list_to_log_on():
    with pytest.raises(journal.NoMonthlyLogError):
        journal.log_month_entry(
            "renew passport", month=date(2026, 11, 1), today=date(2026, 10, 25)
        )


def test_an_event_needs_a_date_so_it_cannot_go_on_a_months_task_list():
    with pytest.raises(journal.EventNeedsDateError):
        journal.log_month_entry(
            "o conference", month=date(2026, 10, 1), today=date(2026, 10, 25)
        )


def test_a_monthly_log_entry_needs_text():
    with pytest.raises(journal.BlankEntryError):
        journal.log_month_entry(". ", month=date(2026, 10, 1), today=date(2026, 10, 25))


def test_text_logged_on_the_future_log_goes_under_its_month():
    entry = journal.log_future_entry(
        "o Sam's wedding", month=date(2027, 3, 1), today=date(2026, 10, 25)
    )

    assert entry == journal.NewEntry(
        type=journal.EntryType.EVENT,
        state=None,
        priority=False,
        inspiration=False,
        time=None,
        text="Sam's wedding",
        day=None,
        location=journal.Location.FUTURE,
        month=date(2027, 3, 1),
    )


def test_a_future_log_entry_can_carry_a_specific_date_in_its_month():
    entry = journal.log_future_entry(
        "renew passport",
        month=date(2027, 3, 1),
        on=date(2027, 3, 3),
        today=date(2026, 10, 25),
    )

    assert (entry.day, entry.month) == (date(2027, 3, 3), date(2027, 3, 1))


def test_a_future_log_date_must_fall_in_its_month():
    with pytest.raises(journal.DateOutsideMonthError):
        journal.log_future_entry(
            "renew passport",
            month=date(2027, 3, 1),
            on=date(2027, 4, 3),
            today=date(2026, 10, 25),
        )


@pytest.mark.parametrize("month", [date(2026, 10, 1), date(2026, 9, 1)])
def test_the_future_log_only_holds_months_after_the_current_one(month):
    with pytest.raises(journal.NotAFutureMonthError):
        journal.log_future_entry("renew passport", month=month, today=date(2026, 10, 25))


def test_in_december_january_entries_go_in_the_future_log():
    entry = journal.log_future_entry(
        "file taxes", month=date(2027, 1, 1), today=date(2026, 12, 31)
    )

    assert entry.month == date(2027, 1, 1)


def _on_day(id: int, text: str, *, day: date) -> journal.Entry:
    new = journal.log_entry(text, on=day)
    return journal.Entry(
        id=id,
        type=new.type,
        state=new.state,
        priority=new.priority,
        inspiration=new.inspiration,
        time=new.time,
        text=new.text,
        day=new.day,
    )


def test_a_monthly_logs_calendar_lists_every_day_with_that_days_events():
    dentist = _on_day(1, "o 9am dentist", day=date(2027, 2, 3))
    call = _on_day(2, "call bank", day=date(2027, 2, 3))
    party = _on_day(3, "o party", day=date(2027, 2, 28))
    lunch = _on_day(4, "o lunch", day=date(2027, 2, 3))

    calendar = journal.monthly_calendar(date(2027, 2, 1), [dentist, call, party, lunch])

    assert len(calendar) == 28
    assert calendar[0] == journal.CalendarDay(day=date(2027, 2, 1), events=[])
    assert calendar[2] == journal.CalendarDay(day=date(2027, 2, 3), events=[dentist, lunch])
    assert calendar[27] == journal.CalendarDay(day=date(2027, 2, 28), events=[party])


def test_a_calendar_leaves_out_events_from_other_months():
    stray = _on_day(1, "o party", day=date(2027, 3, 1))

    calendar = journal.monthly_calendar(date(2027, 2, 1), [stray])

    assert all(day.events == [] for day in calendar)


def _in_future_log(id: int, text: str, *, month: date, on: date | None = None) -> journal.Entry:
    new = journal.log_future_entry(text, month=month, on=on, today=date(2026, 10, 25))
    return journal.Entry(
        id=id,
        type=new.type,
        state=new.state,
        priority=new.priority,
        inspiration=new.inspiration,
        time=new.time,
        text=new.text,
        day=new.day,
        location=new.location,
        month=new.month,
    )


def test_the_future_log_groups_entries_into_the_months_after_the_current_one():
    wedding = _in_future_log(1, "o wedding", month=date(2027, 1, 1))
    taxes = _in_future_log(2, "file taxes", month=date(2026, 11, 1))
    trip = _in_future_log(3, "o trip", month=date(2027, 9, 1))

    future_log = journal.future_log([wedding, taxes, trip], today=date(2026, 10, 25))

    assert [(bucket.month, bucket.entries) for bucket in future_log] == [
        (date(2026, 11, 1), [taxes]),
        (date(2026, 12, 1), []),
        (date(2027, 1, 1), [wedding]),
        (date(2027, 2, 1), []),
        (date(2027, 3, 1), []),
        (date(2027, 4, 1), []),
        (date(2027, 9, 1), [trip]),
    ]


def test_dated_future_log_entries_come_first_in_date_order():
    undated = _in_future_log(1, "plan trip", month=date(2026, 11, 1))
    late = _in_future_log(2, "o party", month=date(2026, 11, 1), on=date(2026, 11, 20))
    early = _in_future_log(3, "o dentist", month=date(2026, 11, 1), on=date(2026, 11, 2))

    future_log = journal.future_log([undated, late, early], today=date(2026, 10, 25))

    assert future_log[0].entries == [early, late, undated]


def test_once_its_month_arrives_an_entry_is_no_longer_in_the_future_log():
    taxes = _in_future_log(1, "file taxes", month=date(2026, 11, 1))

    future_log = journal.future_log([taxes], today=date(2026, 11, 1))

    assert future_log[0].month == date(2026, 12, 1)
    assert all(bucket.entries == [] for bucket in future_log)
