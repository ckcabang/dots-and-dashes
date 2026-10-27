from dataclasses import replace
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


def _open_task(text: str = "buy milk") -> journal.Entry:
    return _stored(7, text)


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


def test_day_progress_counts_completed_tasks_against_open_and_completed_ones():
    def task(id, state):
        return replace(_stored(id, "task"), state=state)

    daily_log = [
        task(1, journal.TaskState.COMPLETED),
        task(2, journal.TaskState.OPEN),
        task(3, journal.TaskState.MIGRATED),
        task(4, journal.TaskState.SCHEDULED),
        task(5, journal.TaskState.CANCELLED),
        replace(_stored(6, "lunch"), type=journal.EntryType.EVENT, state=None),
    ]

    progress = journal.day_progress(daily_log)

    assert (progress.completed, progress.total) == (1, 2)
    assert not progress.all_completed


def test_a_day_is_all_completed_when_every_counted_task_is():
    daily_log = [
        journal.complete(_open_task()),
        journal.cancel(_stored(8, "call bank")),
    ]

    assert journal.day_progress(daily_log).all_completed


def test_a_day_with_no_open_or_completed_tasks_has_no_progress_to_show():
    progress = journal.day_progress([journal.cancel(_open_task())])

    assert progress.total == 0
    assert not progress.all_completed


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


def test_editing_reads_the_prefix_for_signifiers_and_time():
    edited = journal.edit_entry(_open_task(), "*!. 2:30pm buy oat milk")

    assert edited == replace(
        _open_task("buy oat milk"), priority=True, inspiration=True, time=time(14, 30)
    )


def test_editing_a_task_into_a_note_drops_its_task_state():
    edited = journal.edit_entry(journal.complete(_open_task()), "- milk is in the fridge")

    assert (edited.type, edited.state) == (journal.EntryType.NOTE, None)


def test_editing_an_event_into_a_task_makes_it_an_open_task():
    event = replace(_open_task("dinner"), type=journal.EntryType.EVENT, state=None)

    edited = journal.edit_entry(event, ". book dinner")

    assert (edited.type, edited.state) == (journal.EntryType.TASK, journal.TaskState.OPEN)


@pytest.mark.parametrize(
    "entry",
    [
        _open_task("buy milk"),
        _open_task(".5 miles run"),
        _open_task("- not a Note"),
        _open_task("9am is not a time here"),
        _open_task("*not a Signifier"),
        replace(_open_task("standup"), time=time(9, 0)),
        replace(_open_task("call mum"), priority=True),
        replace(
            _open_task("dinner with Sam"),
            type=journal.EntryType.EVENT,
            state=None,
            inspiration=True,
            time=time(19, 30),
        ),
        replace(_open_task("the cafe opens at 7"), type=journal.EntryType.NOTE, state=None),
    ],
    ids=lambda entry: f"{entry.type}:{entry.text}",
)
def test_editing_without_changes_leaves_the_entry_as_it_was(entry):
    assert journal.edit_entry(entry, journal.as_typed(entry)) == entry


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


@pytest.mark.parametrize(
    ("month", "previous"),
    [
        (date(2026, 10, 1), date(2026, 9, 1)),
        (date(2026, 3, 1), date(2026, 2, 1)),
        (date(2027, 1, 1), date(2026, 12, 1)),
    ],
)
def test_the_month_before_a_month_rolls_january_back_into_december(month, previous):
    assert journal.previous_month(month) == previous


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


def _day(*entries: tuple[str, time | None]) -> list[journal.Entry]:
    """A Daily Log's Entries in their manual order."""
    return [_stored(id, text, at) for id, (text, at) in enumerate(entries, start=1)]


def _by_text(entries: list[journal.Entry], text: str) -> journal.Entry:
    return next(entry for entry in entries if entry.text == text)


def test_an_untimed_entry_is_anchored_to_the_nearest_timed_entry_above_it():
    daily_log = _day(
        ("standup", time(9, 30)),
        ("prep notes", None),
        ("lunch", time(12, 0)),
        ("book a table", None),
        ("call back", None),
    )

    assert journal.anchor(daily_log, _by_text(daily_log, "prep notes").id) == (
        _by_text(daily_log, "standup")
    )
    assert journal.anchor(daily_log, _by_text(daily_log, "call back").id) == (
        _by_text(daily_log, "lunch")
    )


def test_untimed_entries_at_the_top_of_the_day_have_no_anchor():
    daily_log = _day(("buy milk", None), ("standup", time(9, 30)))

    assert journal.anchor(daily_log, _by_text(daily_log, "buy milk").id) is None


def test_a_timed_entry_has_no_anchor():
    daily_log = _day(("standup", time(9, 30)), ("lunch", time(12, 0)))

    assert journal.anchor(daily_log, _by_text(daily_log, "lunch").id) is None


def test_changing_a_timed_entrys_time_moves_its_anchored_entries_with_it():
    daily_log = _day(
        ("buy milk", None),
        ("standup", time(9, 30)),
        ("prep notes", None),
        ("bring slides", None),
        ("lunch", time(12, 0)),
        ("book a table", None),
    )

    changed = journal.change_time(
        daily_log, _by_text(daily_log, "standup").id, to=time(14, 0)
    )

    assert _texts(changed) == [
        "buy milk",
        "lunch",
        "book a table",
        "standup",
        "prep notes",
        "bring slides",
    ]
    assert _by_text(changed, "standup").time == time(14, 0)
    assert journal.anchor(changed, _by_text(changed, "bring slides").id) == (
        _by_text(changed, "standup")
    )


def test_a_timed_entry_moved_to_the_same_time_as_another_goes_after_it():
    daily_log = _day(("standup", time(9, 30)), ("prep", None), ("lunch", time(12, 0)))

    changed = journal.change_time(
        daily_log, _by_text(daily_log, "standup").id, to=time(12, 0)
    )

    assert _texts(changed) == ["lunch", "standup", "prep"]


def test_only_a_timed_entry_can_have_its_time_changed():
    daily_log = _day(("standup", time(9, 30)), ("prep notes", None))

    with pytest.raises(journal.UntimedEntryError):
        journal.change_time(
            daily_log, _by_text(daily_log, "prep notes").id, to=time(10, 0)
        )


def test_dragging_an_untimed_entry_re_anchors_it_to_the_timed_entry_now_above_it():
    daily_log = _day(
        ("standup", time(9, 30)),
        ("prep notes", None),
        ("lunch", time(12, 0)),
        ("book a table", None),
    )

    moved = journal.move_entry(daily_log, _by_text(daily_log, "prep notes").id, to=3)

    assert _texts(moved) == ["standup", "lunch", "book a table", "prep notes"]
    assert journal.anchor(moved, _by_text(moved, "prep notes").id) == (
        _by_text(moved, "lunch")
    )


def test_an_untimed_entry_reordered_among_its_anchors_followers_keeps_its_anchor():
    daily_log = _day(("standup", time(9, 30)), ("prep notes", None), ("bring slides", None))

    moved = journal.move_entry(daily_log, _by_text(daily_log, "bring slides").id, to=1)

    assert _texts(moved) == ["standup", "bring slides", "prep notes"]
    assert journal.anchor(moved, _by_text(moved, "bring slides").id) == (
        _by_text(moved, "standup")
    )


def test_an_untimed_entry_dragged_to_the_top_of_the_day_loses_its_anchor():
    daily_log = _day(("buy milk", None), ("standup", time(9, 30)), ("prep notes", None))

    moved = journal.move_entry(daily_log, _by_text(daily_log, "prep notes").id, to=0)

    assert _texts(moved) == ["prep notes", "buy milk", "standup"]
    assert journal.anchor(moved, _by_text(moved, "prep notes").id) is None


def test_a_move_past_either_end_of_the_daily_log_stops_at_that_end():
    daily_log = _day(("standup", time(9, 30)), ("prep notes", None), ("lunch", time(12, 0)))

    assert _texts(
        journal.move_entry(daily_log, _by_text(daily_log, "prep notes").id, to=99)
    ) == ["standup", "lunch", "prep notes"]
    assert _texts(
        journal.move_entry(daily_log, _by_text(daily_log, "prep notes").id, to=-1)
    ) == ["prep notes", "standup", "lunch"]


def test_a_timed_entry_cannot_be_dragged():
    daily_log = _day(("standup", time(9, 30)), ("lunch", time(12, 0)))

    with pytest.raises(journal.TimedEntryMoveError):
        journal.move_entry(daily_log, _by_text(daily_log, "lunch").id, to=0)


def test_only_an_untimed_entry_on_a_daily_log_that_is_not_a_nested_note_is_draggable():
    untimed = _stored(1, "buy milk", None)

    assert journal.is_draggable(untimed)
    assert not journal.is_draggable(_stored(2, "standup", time(9, 30)))
    assert not journal.is_draggable(replace(untimed, parent_id=3))
    assert not journal.is_draggable(
        replace(untimed, location=journal.Location.MONTH, day=None, month=date(2026, 10, 1))
    )


def test_an_untimed_entry_added_to_a_daily_log_goes_to_the_bottom():
    *daily_log, added = _day(
        ("buy milk", None),
        ("standup", time(9, 30)),
        ("lunch", time(12, 0)),
        ("book a table", None),
        ("call back", None),
    )

    assert _texts(journal.place_on_daily_log(added, daily_log)) == [
        "buy milk",
        "standup",
        "lunch",
        "book a table",
        "call back",
    ]


def test_a_timed_entry_added_to_a_daily_log_slots_in_by_its_time():
    *daily_log, added = _day(
        ("buy milk", None),
        ("standup", time(9, 30)),
        ("prep notes", None),
        ("lunch", time(12, 0)),
        ("dentist", time(10, 0)),
    )

    assert _texts(journal.place_on_daily_log(added, daily_log)) == [
        "buy milk",
        "standup",
        "prep notes",
        "dentist",
        "lunch",
    ]


def _logged(
    id: int,
    type: journal.EntryType,
    text: str,
    at: time | None = None,
    parent_id: int | None = None,
) -> journal.Entry:
    return journal.Entry(
        id=id,
        type=type,
        state=journal.TaskState.OPEN if type is journal.EntryType.TASK else None,
        priority=False,
        inspiration=False,
        time=at,
        text=text,
        day=date(2026, 10, 25),
        parent_id=parent_id,
    )


TASK, EVENT, NOTE = journal.EntryType.TASK, journal.EntryType.EVENT, journal.EntryType.NOTE


@pytest.mark.parametrize("parent_type", [TASK, EVENT])
def test_a_note_nests_under_the_task_or_event_above_it(parent_type):
    parent = _logged(1, parent_type, "dentist")
    note = _logged(2, NOTE, "bring insurance card")

    nested = journal.nest_note(note, [parent, note])

    assert nested.parent_id == 1


def test_a_note_below_a_nested_note_nests_under_the_same_parent():
    task = _logged(1, TASK, "dentist")
    card = _logged(2, NOTE, "bring insurance card", parent_id=1)
    note = _logged(3, NOTE, "ask about the bill")

    nested = journal.nest_note(note, [task, card, note])

    assert nested.parent_id == 1


def test_a_note_cannot_nest_under_a_note():
    idea = _logged(1, NOTE, "the cafe opens at 7")
    note = _logged(2, NOTE, "and closes at 3")

    with pytest.raises(journal.NestingError):
        journal.nest_note(note, [idea, note])


@pytest.mark.parametrize("type", [TASK, EVENT])
def test_only_notes_can_nest(type):
    task = _logged(1, TASK, "dentist")
    entry = _logged(2, type, "book a cab")

    with pytest.raises(journal.NestingError):
        journal.nest_note(entry, [task, entry])


def test_a_note_at_the_top_of_its_daily_log_has_nothing_to_nest_under():
    note = _logged(1, NOTE, "slept badly")
    task = _logged(2, TASK, "dentist")

    with pytest.raises(journal.NestingError):
        journal.nest_note(note, [note, task])


def test_a_nested_note_can_be_un_nested():
    note = _logged(2, NOTE, "bring insurance card", parent_id=1)

    assert journal.un_nest_note(note).parent_id is None


def test_nested_notes_sit_under_their_parent_and_move_with_it():
    logged = [
        _logged(1, EVENT, "dinner", time(19, 0)),
        _logged(2, TASK, "standup", time(9, 30)),
        _logged(3, NOTE, "book a table", parent_id=1),
        _logged(4, TASK, "buy milk"),
        _logged(5, NOTE, "ask about blockers", parent_id=2),
        _logged(6, NOTE, "bring flowers", parent_id=1),
    ]

    assert _texts(journal.arrange_daily_log(logged)) == [
        "standup",
        "ask about blockers",
        "buy milk",
        "dinner",
        "book a table",
        "bring flowers",
    ]


def test_a_nested_notes_time_does_not_make_it_an_anchor():
    logged = [
        _logged(1, TASK, "dentist", time(15, 0)),
        _logged(2, NOTE, "9am call to confirm", time(9, 0), parent_id=1),
        _logged(3, TASK, "pick up prescription"),
    ]

    assert _texts(journal.arrange_daily_log(logged)) == [
        "dentist",
        "9am call to confirm",
        "pick up prescription",
    ]


def test_changing_a_timed_entrys_time_takes_nested_notes_along_with_its_followers():
    daily_log = [
        _logged(1, EVENT, "standup", time(9, 30)),
        _logged(2, NOTE, "room 4", parent_id=1),
        _logged(3, TASK, "prep notes"),
        _logged(4, NOTE, "use last week's", parent_id=3),
        _logged(5, EVENT, "lunch", time(12, 0)),
    ]

    changed = journal.change_time(daily_log, 1, to=time(14, 0))

    assert _texts(changed) == ["lunch", "standup", "room 4", "prep notes", "use last week's"]


def test_a_dragged_task_takes_its_nested_notes_and_never_lands_inside_another_tasks():
    daily_log = [
        _logged(1, TASK, "buy milk"),
        _logged(2, NOTE, "oat", parent_id=1),
        _logged(3, EVENT, "standup", time(9, 30)),
        _logged(4, TASK, "prep notes"),
        _logged(5, NOTE, "use last week's", parent_id=4),
    ]

    # Index 2 of the rest of the Daily Log is between "prep notes" and its Nested Note.
    moved = journal.move_entry(daily_log, 1, to=2)

    assert _texts(moved) == ["standup", "prep notes", "use last week's", "buy milk", "oat"]
    assert journal.anchor(moved, 1) == daily_log[2]


def test_a_nested_note_moves_only_with_its_parent():
    daily_log = [_logged(1, TASK, "buy milk"), _logged(2, NOTE, "oat", parent_id=1)]

    with pytest.raises(journal.NestedNoteMoveError):
        journal.move_entry(daily_log, 2, to=0)


def test_editing_a_nested_note_keeps_it_nested():
    note = _logged(2, NOTE, "bring card", parent_id=1)

    assert journal.edit_entry(note, "- bring insurance card").parent_id == 1


def test_editing_a_nested_note_into_a_task_un_nests_it():
    note = _logged(2, NOTE, "bring card", parent_id=1)

    edited = journal.edit_entry(note, ". bring card")

    assert (edited.type, edited.parent_id) == (TASK, None)


def test_a_parent_edited_into_a_note_lets_its_nested_notes_stand_alone():
    # Notes don't nest under Notes, and nesting is one level deep.
    task = _logged(1, TASK, "dentist")
    notes = [_logged(2, NOTE, "bring card", parent_id=1), _logged(3, NOTE, "9am", parent_id=1)]

    edited = journal.edit_entry(task, "- dentist was fine")

    assert [note.parent_id for note in journal.notes_released_by_edit(edited, notes)] == [
        None,
        None,
    ]


@pytest.mark.parametrize("text", [". dentist at 3", "o dentist"])
def test_a_parent_still_a_task_or_event_after_an_edit_keeps_its_nested_notes(text):
    task = _logged(1, TASK, "dentist")
    notes = [_logged(2, NOTE, "bring card", parent_id=1)]

    assert journal.notes_released_by_edit(journal.edit_entry(task, text), notes) == []


def test_deleting_a_parent_lets_its_nested_notes_stand_alone():
    task = _logged(1, TASK, "dentist")
    note = _logged(2, NOTE, "bring card", parent_id=1)

    assert journal.delete_entry(task, successor=None, nested_notes=[note]) == [
        replace(note, parent_id=None)
    ]


def test_deleting_a_copy_mid_chain_re_links_its_successor_to_the_copy_before_it():
    middle = replace(_logged(2, TASK, "write report"), migrated_from_id=1)
    successor = replace(_logged(3, TASK, "write report"), migrated_from_id=2)

    assert journal.delete_entry(middle, successor=successor, nested_notes=[]) == [
        replace(successor, migrated_from_id=1)
    ]


def test_a_daily_log_entry_is_on_its_days_daily_log():
    entry = _on_day(1, "- idea", day=date(2026, 10, 25))

    assert journal.daily_log_day(entry) == date(2026, 10, 25)


def test_monthly_and_future_log_entries_are_not_on_a_daily_log():
    dated = _in_future_log(1, "o wedding", month=date(2027, 3, 1), on=date(2027, 3, 3))

    with pytest.raises(journal.NotOnADailyLogError):
        journal.daily_log_day(dated)


def _on_monthly_log(id: int, text: str, *, month: date) -> journal.Entry:
    new = journal.log_month_entry(text, month=month, today=date(2026, 10, 25))
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


def test_editing_a_monthly_log_entry_keeps_it_on_that_months_task_list():
    task = _on_monthly_log(1, "pay rent", month=date(2026, 10, 1))

    edited = journal.edit_entry(task, "* pay rent and bills")

    assert (edited.location, edited.month, edited.day) == (
        journal.Location.MONTH,
        date(2026, 10, 1),
        None,
    )
    assert (edited.text, edited.priority) == ("pay rent and bills", True)


def test_a_monthly_log_entry_cannot_be_edited_into_an_event():
    task = _on_monthly_log(1, "pay rent", month=date(2026, 10, 1))

    with pytest.raises(journal.EventNeedsDateError):
        journal.edit_entry(task, "o pay rent")


def test_editing_a_future_log_entry_keeps_its_month_and_date():
    task = _in_future_log(1, "book flights", month=date(2027, 3, 1), on=date(2027, 3, 3))

    edited = journal.edit_entry(task, "book flights to Lisbon")

    assert (edited.location, edited.month, edited.day) == (
        journal.Location.FUTURE,
        date(2027, 3, 1),
        date(2027, 3, 3),
    )


def test_an_undated_future_log_entry_can_be_edited_into_an_event():
    task = _in_future_log(1, "wedding", month=date(2027, 3, 1))

    edited = journal.edit_entry(task, "o wedding")

    assert (edited.type, edited.state, edited.location, edited.day) == (
        EVENT,
        None,
        journal.Location.FUTURE,
        None,
    )


def test_completing_a_monthly_log_task_keeps_it_on_the_monthly_log():
    task = _on_monthly_log(1, "pay rent", month=date(2026, 10, 1))

    completed = journal.complete(task)

    assert (completed.location, completed.month) == (journal.Location.MONTH, date(2026, 10, 1))
