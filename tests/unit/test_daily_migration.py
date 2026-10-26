"""Daily Migration: reviewing Open Tasks from earlier days, the night before or in the morning."""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from dots_and_dashes import journal

LOS_ANGELES = ZoneInfo("America/Los_Angeles")


def _at(local: str) -> datetime:
    """An instant given as Los Angeles wall-clock time, as the injected clock would give it in UTC."""
    return datetime.fromisoformat(local).replace(tzinfo=LOS_ANGELES).astimezone(UTC)


@pytest.mark.parametrize(
    ("now", "planning"),
    [
        pytest.param("2026-10-25 00:00", date(2026, 10, 25), id="just after midnight"),
        pytest.param("2026-10-25 07:30", date(2026, 10, 25), id="morning"),
        pytest.param("2026-10-25 17:59", date(2026, 10, 25), id="just before 18:00"),
        pytest.param("2026-10-25 18:00", date(2026, 10, 26), id="from 18:00"),
        pytest.param("2026-10-25 23:59", date(2026, 10, 26), id="late evening"),
    ],
)
def test_daily_migration_in_the_evening_plans_tomorrow_and_otherwise_today(now, planning):
    assert journal.daily_migration_planning(_at(now), LOS_ANGELES) == planning


def test_whether_it_is_evening_is_read_in_the_users_timezone():
    # 02:00 UTC on 26 Oct is 19:00 on 25 Oct in Los Angeles: the evening before the 26th.
    now = datetime(2026, 10, 26, 2, 0, tzinfo=UTC)

    assert journal.is_night_before(now, LOS_ANGELES)
    assert not journal.is_night_before(now, ZoneInfo("Europe/London"))


TASK, EVENT, NOTE = journal.EntryType.TASK, journal.EntryType.EVENT, journal.EntryType.NOTE
OPEN, COMPLETED = journal.TaskState.OPEN, journal.TaskState.COMPLETED
PLANNING = date(2026, 10, 25)


def _entry(
    id: int,
    text: str,
    *,
    day: date | None = date(2026, 10, 24),
    at: time | None = None,
    type: journal.EntryType = TASK,
    state: journal.TaskState | None = OPEN,
    location: journal.Location = journal.Location.DAY,
    month: date | None = None,
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


def _tasks(review: list[journal.MigrationDay]) -> list[tuple[date, str]]:
    return [(day.day, task.text) for day in review for group in day.groups for task in group.tasks]


def test_daily_migration_lists_open_tasks_from_every_earlier_day_oldest_first():
    entries = [
        _entry(1, "file taxes", day=date(2026, 10, 24)),
        _entry(2, "call mum", day=date(2026, 9, 2)),
        _entry(3, "buy milk", day=date(2026, 10, 20)),
    ]

    review = journal.daily_migration(entries, planning=PLANNING)

    assert _tasks(review) == [
        (date(2026, 9, 2), "call mum"),
        (date(2026, 10, 20), "buy milk"),
        (date(2026, 10, 24), "file taxes"),
    ]


def test_daily_migration_leaves_out_what_needs_no_decision():
    entries = [
        _entry(1, "still open"),
        _entry(2, "sent invoice", state=COMPLETED),
        _entry(3, "moved on", state=journal.TaskState.MIGRATED),
        _entry(4, "learn banjo", state=journal.TaskState.CANCELLED),
        _entry(5, "dentist", type=EVENT, at=time(9, 0)),
        _entry(6, "felt tired", type=NOTE),
        _entry(7, "already planned", day=PLANNING),
        _entry(8, "later on", day=date(2026, 10, 28)),
        _entry(9, "this month", day=None, location=journal.Location.MONTH, month=date(2026, 10, 1)),
        _entry(10, "next year", day=None, location=journal.Location.FUTURE, month=date(2027, 1, 1)),
    ]

    review = journal.daily_migration(entries, planning=PLANNING)

    assert _tasks(review) == [(date(2026, 10, 24), "still open")]


def test_the_night_before_todays_open_tasks_are_from_an_earlier_day():
    entries = [_entry(1, "write report", day=PLANNING)]

    review = journal.daily_migration(entries, planning=date(2026, 10, 26))

    assert _tasks(review) == [(PLANNING, "write report")]


def test_daily_migration_is_empty_when_nothing_is_left_open():
    assert journal.daily_migration([_entry(1, "sent invoice", state=COMPLETED)], planning=PLANNING) == []


def _grouped(review: list[journal.MigrationDay]) -> list[tuple[date, str | None, list[str]]]:
    return [
        (day.day, group.anchor.text if group.anchor else None, [task.text for task in group.tasks])
        for day in review
        for group in day.groups
    ]


def test_open_tasks_are_grouped_under_their_anchor_in_daily_log_order():
    # In manual order; the Daily Log shows the 09:00 block before the 14:00 one.
    day = date(2026, 10, 24)
    entries = [
        _entry(1, "water plants", day=day),
        _entry(2, "team offsite", day=day, type=EVENT, at=time(14, 0)),
        _entry(3, "book room", day=day),
        _entry(4, "send agenda", day=day, state=COMPLETED),
        _entry(5, "print slides", day=day),
        _entry(6, "standup", day=day, type=EVENT, at=time(9, 0)),
        _entry(7, "update board", day=day),
        _entry(8, "gym", day=day, type=EVENT, at=time(18, 0)),
        _entry(9, "pack bag", day=day, state=COMPLETED),
    ]

    review = journal.daily_migration(entries, planning=PLANNING)

    assert _grouped(review) == [
        (day, None, ["water plants"]),
        (day, "standup", ["update board"]),
        (day, "team offsite", ["book room", "print slides"]),
    ]


def test_an_open_timed_task_leads_its_own_group():
    day = date(2026, 10, 24)
    entries = [
        _entry(1, "review PR", day=day, at=time(10, 0)),
        _entry(2, "reply to comments", day=day),
    ]

    review = journal.daily_migration(entries, planning=PLANNING)

    [group] = review[0].groups
    assert group.anchor == entries[0]
    assert [task.text for task in group.tasks] == ["review PR", "reply to comments"]
