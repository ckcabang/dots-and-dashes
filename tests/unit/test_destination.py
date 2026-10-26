"""Choosing a Destination from what the User asked, for Migration and Triage alike.

The day being planned is 2026-10-25: for Triage that is today.
"""

from datetime import date

import pytest

from dots_and_dashes import journal

Destination = journal.Destination
PLANNING = date(2026, 10, 25)


@pytest.mark.parametrize(
    ("to", "on", "month", "destination"),
    [
        pytest.param(
            "day", date(2026, 10, 28), None, Destination.daily_log(date(2026, 10, 28)), id="a day"
        ),
        pytest.param("day", None, None, Destination.daily_log(PLANNING), id="the day planned"),
        pytest.param(
            "month",
            None,
            None,
            Destination.monthly_log(date(2026, 10, 1)),
            id="the month planned",
        ),
        pytest.param(
            "month",
            None,
            date(2026, 9, 1),
            Destination.monthly_log(date(2026, 9, 1)),
            id="a month named",
        ),
        pytest.param(
            "future",
            None,
            date(2027, 3, 1),
            Destination.future_log(date(2027, 3, 1)),
            id="a future month",
        ),
        pytest.param(
            "future",
            date(2027, 3, 3),
            date(2027, 3, 1),
            Destination.future_log(date(2027, 3, 1), on=date(2027, 3, 3)),
            id="a future month on a date",
        ),
        pytest.param(
            "date",
            date(2027, 1, 4),
            None,
            Destination.future_log(date(2027, 1, 1), on=date(2027, 1, 4)),
            id="scheduled to a date",
        ),
    ],
)
def test_the_destination_is_what_the_user_asked_for(to, on, month, destination):
    assert journal.destination(to, on=on, month=month, planning=PLANNING) == destination


def test_the_future_log_needs_a_month():
    with pytest.raises(journal.PlacementError, match="the Future Log needs a month"):
        journal.destination("future", on=date(2027, 3, 3), month=None, planning=PLANNING)


def test_scheduling_needs_a_date():
    with pytest.raises(journal.PlacementError, match="scheduling needs a date"):
        journal.destination("date", on=None, month=None, planning=PLANNING)
