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
