"""Monthly Review: last month's leftover Open Tasks, and pulling this month's Future Log in."""

from datetime import date, time

from dots_and_dashes import journal

TASK, EVENT, NOTE = journal.EntryType.TASK, journal.EntryType.EVENT, journal.EntryType.NOTE
OPEN, COMPLETED = journal.TaskState.OPEN, journal.TaskState.COMPLETED
MIGRATED = journal.TaskState.MIGRATED
DAY, MONTH, FUTURE = journal.Location.DAY, journal.Location.MONTH, journal.Location.FUTURE

OCTOBER, NOVEMBER = date(2026, 10, 1), date(2026, 11, 1)
# The first of the month, the day the Monthly Review is meant for.
FIRST = date(2026, 11, 1)


def _entry(
    id: int,
    text: str,
    *,
    type: journal.EntryType = TASK,
    state: journal.TaskState | None = OPEN,
    location: journal.Location = DAY,
    day: date | None = None,
    month: date | None = None,
    at: time | None = None,
    parent_id: int | None = None,
) -> journal.Entry:
    return journal.Entry(
        id=id,
        type=type,
        state=state if type is TASK else None,
        priority=False,
        inspiration=False,
        time=at,
        text=text,
        day=day,
        location=location,
        month=month,
        parent_id=parent_id,
    )


def _future(id: int, text: str, *, on: date | None = None, **kwargs) -> journal.Entry:
    return _entry(id, text, location=FUTURE, month=NOVEMBER, day=on, **kwargs)


def _texts(entries: list[journal.Entry]) -> list[str]:
    return [entry.text for entry in entries]


def test_the_monthly_review_lists_last_months_open_tasks_from_its_daily_logs_and_task_list():
    entries = [
        _entry(1, "pay rent", location=MONTH, month=OCTOBER),
        _entry(2, "file taxes", location=MONTH, month=OCTOBER, state=COMPLETED),
        _entry(3, "write report", day=date(2026, 10, 20)),
        _entry(4, "o dentist", type=EVENT, day=date(2026, 10, 20)),
        _entry(5, "call mum", day=date(2026, 10, 3)),
        _entry(6, "water plants", day=date(2026, 10, 3), state=MIGRATED),
    ]

    review = journal.monthly_review(entries, today=FIRST)

    assert review.month == NOVEMBER
    assert _texts(review.task_list) == ["pay rent"]
    assert [(d.day, _texts(d.tasks)) for d in review.days] == [
        (date(2026, 10, 3), ["call mum"]),
        (date(2026, 10, 20), ["write report"]),
    ]


def test_the_monthly_review_leaves_out_tasks_from_other_months():
    entries = [
        _entry(1, "september task", day=date(2026, 9, 30)),
        _entry(2, "november task", day=date(2026, 11, 1)),
        _entry(3, "september list", location=MONTH, month=date(2026, 9, 1)),
        _entry(4, "november list", location=MONTH, month=NOVEMBER),
    ]

    review = journal.monthly_review(entries, today=FIRST)

    assert (review.task_list, review.days) == ([], [])


def test_the_monthly_review_opened_after_the_first_still_reviews_last_month():
    entries = [_entry(1, "write report", day=date(2026, 10, 20))]

    review = journal.monthly_review(entries, today=date(2026, 11, 12))

    assert review.month == NOVEMBER
    assert [_texts(d.tasks) for d in review.days] == [["write report"]]


def test_in_january_the_monthly_review_reviews_december():
    entries = [_entry(1, "buy presents", location=MONTH, month=date(2026, 12, 1))]

    review = journal.monthly_review(entries, today=date(2027, 1, 1))

    assert _texts(review.task_list) == ["buy presents"]


def _where(entry: journal.Entry | journal.NewEntry):
    return (entry.location, entry.day, entry.month)


def test_pulling_an_undated_task_copies_it_onto_this_months_task_list_marked_migrated():
    task = _future(1, "renew passport")

    [migration] = journal.pull_from_future_log([task], today=FIRST).migrations

    assert migration.original.state is MIGRATED
    assert _where(migration.copy) == (MONTH, None, NOVEMBER)
    assert (migration.copy.state, migration.copy.migrated_from_id) == (OPEN, 1)


def test_pulling_a_dated_task_copies_it_onto_its_day_marked_migrated_with_its_time():
    task = _future(1, "flu jab", on=date(2026, 11, 9), at=time(9, 30))

    [migration] = journal.pull_from_future_log([task], today=FIRST).migrations

    assert migration.original.state is MIGRATED
    assert _where(migration.copy) == (DAY, date(2026, 11, 9), None)
    assert migration.copy.time == time(9, 30)


def test_opened_after_the_first_a_task_dated_earlier_this_month_goes_on_the_task_list():
    passed = _future(1, "flu jab", on=date(2026, 11, 3))
    due_today = _future(2, "pay rent", on=date(2026, 11, 12))

    pull = journal.pull_from_future_log([passed, due_today], today=date(2026, 11, 12))

    assert [_where(m.copy) for m in pull.migrations] == [
        (MONTH, None, NOVEMBER),
        (DAY, date(2026, 11, 12), None),
    ]


def test_pulling_a_dated_event_moves_it_onto_its_day_with_its_nested_notes():
    wedding = _future(1, "wedding", type=EVENT, on=date(2026, 11, 14))
    note = _future(2, "bring a gift", type=NOTE, parent_id=1)

    pull = journal.pull_from_future_log([wedding, note], today=FIRST)

    assert pull.migrations == []
    assert [(e.id, *_where(e), e.parent_id) for e in pull.moved] == [
        (1, DAY, date(2026, 11, 14), None, None),
        (2, DAY, date(2026, 11, 14), None, 1),
    ]


def test_pulling_a_standalone_note_moves_it_onto_its_day_or_the_task_list():
    dated = _future(1, "half term starts", type=NOTE, on=date(2026, 11, 2))
    undated = _future(2, "quiet month at work", type=NOTE)

    pull = journal.pull_from_future_log([dated, undated], today=FIRST)

    assert [(e.id, *_where(e)) for e in pull.moved] == [
        (1, DAY, date(2026, 11, 2), None),
        (2, MONTH, None, NOVEMBER),
    ]


def test_an_undated_event_waits_in_the_review_for_a_date():
    party = _future(1, "leaving party", type=EVENT)

    pull = journal.pull_from_future_log([party], today=FIRST)
    review = journal.monthly_review([party], today=FIRST)

    assert (pull.migrations, pull.moved) == ([], [])
    assert _texts(review.needs_a_date) == ["leaving party"]


def test_only_this_months_open_tasks_events_and_notes_are_pulled():
    entries = [
        _future(1, "decided already", state=COMPLETED),
        _future(2, "pulled already", state=MIGRATED),
        _entry(3, "december task", location=FUTURE, month=date(2026, 12, 1)),
        _future(4, "renew passport"),
    ]

    pull = journal.pull_from_future_log(entries, today=FIRST)
    review = journal.monthly_review(entries, today=FIRST)

    assert [m.original.id for m in pull.migrations] == [4]
    assert _texts(review.to_pull) == ["renew passport"]


def test_the_review_lists_what_the_pull_will_bring_in_with_nested_notes():
    entries = [
        _future(1, "wedding", type=EVENT, on=date(2026, 11, 14)),
        _future(2, "bring a gift", type=NOTE, parent_id=1),
        _future(3, "renew passport", on=date(2026, 11, 3)),
        _future(4, "leaving party", type=EVENT),
    ]

    review = journal.monthly_review(entries, today=FIRST)

    assert _texts(review.to_pull) == ["renew passport", "wedding", "bring a gift"]
    assert _texts(review.needs_a_date) == ["leaving party"]


def test_pulling_twice_pulls_nothing_more():
    task = _future(1, "renew passport")
    [migration] = journal.pull_from_future_log([task], today=FIRST).migrations

    again = journal.pull_from_future_log([migration.original], today=FIRST)

    assert (again.migrations, again.moved) == ([], [])


def test_an_undated_future_log_event_moves_onto_the_day_it_is_given():
    party = _future(1, "leaving party", type=EVENT)

    moved, _ = journal.move_event(party, [], on=date(2026, 11, 20))

    assert _where(moved) == (DAY, date(2026, 11, 20), None)
