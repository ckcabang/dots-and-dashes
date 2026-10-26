"""Migration and Scheduling: moving a Task forward by copying it (ADR-0001)."""

from dataclasses import replace
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from dots_and_dashes import journal

TASK, EVENT, NOTE = journal.EntryType.TASK, journal.EntryType.EVENT, journal.EntryType.NOTE
OPEN = journal.TaskState.OPEN
MIGRATED, SCHEDULED = journal.TaskState.MIGRATED, journal.TaskState.SCHEDULED
Destination = journal.Destination

# The day being planned in most tests: Sunday 25 October 2026.
PLANNING = date(2026, 10, 25)


def _task(
    id: int = 1,
    text: str = "write report",
    *,
    day: date | None = date(2026, 10, 24),
    at: time | None = None,
    location: journal.Location = journal.Location.DAY,
    month: date | None = None,
    type: journal.EntryType = TASK,
    state: journal.TaskState | None = OPEN,
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


def _where(entry: journal.Entry | journal.NewEntry):
    return (entry.location, entry.day, entry.month)


def test_migrating_to_the_day_being_planned_marks_the_original_migrated():
    task = _task(day=date(2026, 10, 24))

    migration = journal.migrate(task, to=Destination.daily_log(PLANNING), planning=PLANNING)

    assert migration.original == _task(day=date(2026, 10, 24), state=MIGRATED)
    assert migration.copy == journal.NewEntry(
        type=TASK,
        state=OPEN,
        priority=False,
        inspiration=False,
        time=None,
        text="write report",
        day=PLANNING,
        location=journal.Location.DAY,
        month=None,
        migrated_from_id=1,
    )


@pytest.mark.parametrize(
    ("destination", "marked"),
    [
        pytest.param(Destination.daily_log(PLANNING), MIGRATED, id="the day being planned"),
        pytest.param(Destination.monthly_log(date(2026, 10, 1)), MIGRATED, id="this month"),
        pytest.param(Destination.daily_log(date(2026, 10, 28)), SCHEDULED, id="later this month"),
        pytest.param(Destination.future_log(date(2026, 12, 1)), SCHEDULED, id="a later month"),
        pytest.param(
            Destination.future_log(date(2027, 3, 1), on=date(2027, 3, 3)),
            SCHEDULED,
            id="a date in a later month",
        ),
    ],
)
def test_the_destination_decides_whether_a_task_is_migrated_or_scheduled(destination, marked):
    migration = journal.migrate(_task(), to=destination, planning=PLANNING)

    assert migration.original.state is marked
    assert migration.copy.state is OPEN
    assert _where(migration.copy) == (destination.location, destination.day, destination.month)


@pytest.mark.parametrize(
    "destination",
    [
        pytest.param(Destination.daily_log(date(2026, 10, 24)), id="a day before"),
        pytest.param(Destination.daily_log(date(2026, 11, 2)), id="a day next month"),
        pytest.param(Destination.monthly_log(date(2026, 9, 1)), id="a past month"),
        pytest.param(Destination.monthly_log(date(2026, 11, 1)), id="a later month's list"),
        pytest.param(Destination.future_log(date(2026, 10, 1)), id="this month's Future Log"),
        pytest.param(
            Destination.future_log(date(2026, 12, 1), on=date(2027, 1, 4)),
            id="a date outside its month",
        ),
    ],
)
def test_a_task_cannot_move_to_the_past_or_skip_the_future_log(destination):
    with pytest.raises(journal.MigrationError):
        journal.migrate(_task(day=date(2026, 10, 20)), to=destination, planning=PLANNING)


def test_a_task_on_a_later_day_cannot_be_migrated_back_to_the_day_being_planned():
    # It was Scheduled there; Migrating only carries a Task forward.
    with pytest.raises(journal.MigrationError):
        journal.migrate(
            _task(day=date(2026, 10, 28)), to=Destination.daily_log(PLANNING), planning=PLANNING
        )


def test_a_task_cannot_be_migrated_to_where_it_already_is():
    with pytest.raises(journal.MigrationError):
        journal.migrate(
            _task(day=PLANNING), to=Destination.daily_log(PLANNING), planning=PLANNING
        )


LOS_ANGELES = ZoneInfo("America/Los_Angeles")


def test_in_the_morning_the_day_being_planned_is_today():
    # 15:00 UTC on 25 Oct is 08:00 in Los Angeles.
    morning = datetime(2026, 10, 25, 15, 0, tzinfo=UTC)

    assert journal.daily_migration_planning(morning, LOS_ANGELES).day == date(2026, 10, 25)


def test_the_night_before_the_day_being_planned_is_tomorrow():
    # 05:00 UTC on 26 Oct is still 22:00 on 25 Oct in Los Angeles.
    evening = datetime(2026, 10, 26, 5, 0, tzinfo=UTC)

    planning = journal.daily_migration_planning(evening, LOS_ANGELES).day

    assert planning == date(2026, 10, 26)


def test_the_night_before_migrating_to_tomorrow_marks_a_task_migrated_not_scheduled():
    evening = datetime(2026, 10, 26, 5, 0, tzinfo=UTC)
    planning = journal.daily_migration_planning(evening, LOS_ANGELES).day
    todays_task = _task(day=date(2026, 10, 25))

    tomorrow = journal.migrate(
        todays_task, to=Destination.daily_log(date(2026, 10, 26)), planning=planning
    )
    day_after = journal.migrate(
        todays_task, to=Destination.daily_log(date(2026, 10, 27)), planning=planning
    )

    assert tomorrow.original.state is MIGRATED
    assert day_after.original.state is SCHEDULED


def test_planning_today_in_the_evening_migrating_to_tomorrow_schedules_a_task():
    evening = datetime(2026, 10, 26, 5, 0, tzinfo=UTC)
    planning = journal.daily_migration_planning(evening, LOS_ANGELES, night_before=False).day

    migration = journal.migrate(
        _task(day=date(2026, 10, 25)),
        to=Destination.daily_log(date(2026, 10, 26)),
        planning=planning,
    )

    assert migration.original.state is SCHEDULED


def test_a_migrated_timed_task_keeps_its_time_and_signifiers():
    task = replace(_task(at=time(14, 30)), priority=True, inspiration=True)

    migration = journal.migrate(task, to=Destination.daily_log(PLANNING), planning=PLANNING)

    copy = migration.copy
    assert (copy.time, copy.priority, copy.inspiration) == (time(14, 30), True, True)


@pytest.mark.parametrize(
    "state", [journal.TaskState.COMPLETED, journal.TaskState.CANCELLED, MIGRATED, SCHEDULED]
)
def test_only_an_open_task_can_be_migrated(state):
    with pytest.raises(journal.TaskStateError):
        journal.migrate(
            _task(state=state), to=Destination.daily_log(PLANNING), planning=PLANNING
        )


@pytest.mark.parametrize("type", [EVENT, NOTE])
def test_events_and_notes_are_never_migrated(type):
    with pytest.raises(journal.MigrationError):
        journal.migrate(
            _task(type=type), to=Destination.daily_log(PLANNING), planning=PLANNING
        )


def test_migrated_and_scheduled_tasks_cannot_be_reopened():
    with pytest.raises(journal.TaskStateError):
        journal.reopen(_task(state=MIGRATED))


@pytest.mark.parametrize(
    ("destination", "marked"),
    [
        pytest.param(Destination.daily_log(date(2027, 1, 1)), MIGRATED, id="New Year's Day"),
        pytest.param(Destination.monthly_log(date(2027, 1, 1)), MIGRATED, id="January"),
        pytest.param(Destination.daily_log(date(2027, 1, 9)), SCHEDULED, id="later in January"),
        pytest.param(Destination.future_log(date(2027, 2, 1)), SCHEDULED, id="February"),
    ],
)
def test_planning_new_years_day_on_new_years_eve_rolls_over_into_january(destination, marked):
    new_years_eve = datetime(2027, 1, 1, 6, 0, tzinfo=UTC)  # 22:00 on 31 Dec in LA
    planning = journal.daily_migration_planning(new_years_eve, LOS_ANGELES).day

    migration = journal.migrate(
        _task(day=date(2026, 12, 31)), to=destination, planning=planning
    )

    assert migration.original.state is marked


def test_in_december_january_is_a_later_month_in_the_future_log():
    december = date(2026, 12, 15)

    migration = journal.migrate(
        _task(day=december), to=Destination.future_log(date(2027, 1, 1)), planning=december
    )

    assert migration.original.state is SCHEDULED
    assert _where(migration.copy) == (journal.Location.FUTURE, None, date(2027, 1, 1))


@pytest.mark.parametrize(
    ("day", "destination"),
    [
        pytest.param(date(2026, 10, 30), Destination.daily_log(date(2026, 10, 30)), id="this month"),
        pytest.param(
            date(2027, 1, 4),
            Destination.future_log(date(2027, 1, 1), on=date(2027, 1, 4)),
            id="a later month",
        ),
    ],
)
def test_a_task_scheduled_to_a_date_lands_on_its_daily_log_or_in_the_future_log(day, destination):
    assert journal.schedule_destination(day, planning=PLANNING) == destination


def test_nested_notes_move_to_the_new_copy_and_the_original_keeps_only_its_marker():
    task = _task(1, day=date(2026, 10, 24))
    notes = [
        _task(2, "draft is in the shared folder", type=NOTE, parent_id=1),
        _task(3, "ask Sam for numbers", type=NOTE, parent_id=1),
    ]
    migration = journal.migrate(
        task, to=Destination.future_log(date(2026, 12, 1), on=date(2026, 12, 3)), planning=PLANNING
    )
    copy = journal.Entry(id=9, **migration.copy.__dict__)

    moved = journal.move_nested_notes(notes, to=copy)

    assert [(note.id, note.parent_id) for note in moved] == [(2, 9), (3, 9)]
    assert {_where(note) for note in moved} == {
        (journal.Location.FUTURE, date(2026, 12, 3), date(2026, 12, 1))
    }
    assert [note.text for note in moved] == ["draft is in the shared folder", "ask Sam for numbers"]


# A Migration Chain as links: each copy's id to the id it was migrated from.
# Here 1 was migrated to 2, 2 to 3 and 3 to 4; 7 was never migrated.
CHAIN = {2: 1, 3: 2, 4: 3}


@pytest.mark.parametrize("entry_id", [1, 2, 3, 4])
def test_every_copy_in_a_migration_chain_shows_how_often_the_task_was_moved(entry_id):
    assert journal.migration_count(entry_id, CHAIN) == 3


def test_a_task_never_migrated_has_no_migration_count():
    assert journal.migration_count(7, CHAIN) == 0


def test_migrations_and_schedulings_both_count():
    original = _task(1, day=date(2026, 10, 20))
    migrated = journal.migrate(original, to=Destination.daily_log(PLANNING), planning=PLANNING)
    second = journal.Entry(id=2, **migrated.copy.__dict__)
    scheduled = journal.migrate(
        second, to=Destination.daily_log(date(2026, 10, 29)), planning=PLANNING
    )
    third = journal.Entry(id=3, **scheduled.copy.__dict__)

    links = {copy.id: copy.migrated_from_id for copy in [second, third]}

    assert (migrated.original.state, scheduled.original.state) == (MIGRATED, SCHEDULED)
    assert journal.migration_count(3, links) == 2


def test_deleting_a_copy_mid_chain_links_the_next_copy_to_the_one_before():
    middle = _task(2, state=MIGRATED)
    middle = replace(middle, migrated_from_id=1)
    successor = replace(_task(3, day=PLANNING), migrated_from_id=2)

    relinked = journal.relink_around(middle, successor)

    assert relinked.migrated_from_id == 1
    assert journal.migration_count(3, {3: 1}) == 1


def test_deleting_the_start_of_a_chain_makes_the_next_copy_its_start():
    original = _task(1, state=MIGRATED)
    successor = replace(_task(2, day=PLANNING), migrated_from_id=1)

    assert journal.relink_around(original, successor).migrated_from_id is None


def test_an_event_moves_by_changing_its_date_with_no_marker_or_chain():
    dinner = _task(1, "dinner with Ana", type=EVENT, at=time(19, 0))
    note = _task(2, "book a table", type=NOTE, parent_id=1)

    moved, notes = journal.move_event(dinner, [note], on=date(2026, 10, 30))

    assert moved == replace(dinner, day=date(2026, 10, 30))
    assert [(n.day, n.parent_id) for n in notes] == [(date(2026, 10, 30), 1)]


def test_only_an_event_moves_by_changing_its_date():
    with pytest.raises(journal.MigrationError):
        journal.move_event(_task(), [], on=date(2026, 10, 30))


def test_moved_nested_notes_sit_under_their_copy_on_a_monthly_logs_task_list():
    october = date(2026, 10, 1)
    on_list = dict(day=None, location=journal.Location.MONTH, month=october)
    # The notes were logged before the copy they moved to.
    entries = [
        _task(2, "draft is in the shared folder", type=NOTE, parent_id=5, **on_list),
        _task(4, "pay rent", **on_list),
        _task(5, "write report", **on_list),
        _task(6, "book dentist", **on_list),
    ]

    assert [e.text for e in journal.arrange_task_list(entries)] == [
        "pay rent",
        "write report",
        "draft is in the shared folder",
        "book dentist",
    ]


def test_moved_nested_notes_sit_under_their_copy_in_the_future_log():
    december = date(2026, 12, 1)
    in_future = dict(location=journal.Location.FUTURE, month=december)
    entries = [
        _task(2, "draft is in the shared folder", type=NOTE, parent_id=5, day=None, **in_future),
        _task(4, "wedding", type=EVENT, day=date(2026, 12, 12), **in_future),
        _task(5, "write report", day=date(2026, 12, 3), **in_future),
    ]

    bucket = journal.future_log(entries, today=PLANNING)[1]

    assert [e.text for e in bucket.entries] == [
        "write report",
        "draft is in the shared folder",
        "wedding",
    ]
