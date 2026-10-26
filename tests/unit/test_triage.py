"""Captures and Triage: turning a Capture from the Inbox into an Entry."""

from datetime import date, time

import pytest

from dots_and_dashes import journal

TODAY = date(2026, 10, 25)


def _capture(text: str) -> journal.Capture:
    return journal.Capture(id=1, text=text)


def test_triage_suggests_the_type_signifiers_and_time_the_prefix_gives():
    suggestion = journal.triage_suggestion(_capture("*o 9am dentist"))

    assert suggestion == journal.ParsedEntry(
        type=journal.EntryType.EVENT,
        priority=True,
        inspiration=False,
        time=time(9, 0),
        text="dentist",
    )


def test_a_capture_with_no_prefix_suggests_a_plain_task():
    suggestion = journal.triage_suggestion(_capture("call the plumber"))

    assert suggestion == journal.ParsedEntry(
        type=journal.EntryType.TASK,
        priority=False,
        inspiration=False,
        time=None,
        text="call the plumber",
    )


def test_a_capture_keeps_its_raw_text_unclassified():
    assert journal.capture("o 9am dentist ") == journal.NewCapture(text="o 9am dentist ")


@pytest.mark.parametrize("text", ["", "   "])
def test_a_blank_capture_is_refused(text):
    with pytest.raises(journal.BlankCaptureError):
        journal.capture(text)


def test_triage_places_a_capture_on_a_days_daily_log_as_suggested():
    entry = journal.triage(
        _capture("*o 9am dentist"),
        to=journal.Destination.daily_log(date(2026, 10, 28)),
        today=TODAY,
    )

    assert entry == journal.NewEntry(
        type=journal.EntryType.EVENT,
        state=None,
        priority=True,
        inspiration=False,
        time=time(9, 0),
        text="dentist",
        day=date(2026, 10, 28),
    )


def test_an_adjusted_suggestion_is_read_with_the_prefix_rules_instead():
    entry = journal.triage(
        _capture("o 9am dentist"),
        text="!. 10:30 book the dentist",
        to=journal.Destination.daily_log(TODAY),
        today=TODAY,
    )

    assert (entry.type, entry.state, entry.priority, entry.inspiration) == (
        journal.EntryType.TASK,
        journal.TaskState.OPEN,
        False,
        True,
    )
    assert (entry.time, entry.text) == (time(10, 30), "book the dentist")


def test_an_adjusted_suggestion_with_no_text_left_is_refused():
    with pytest.raises(journal.BlankEntryError):
        journal.triage(
            _capture("dentist"), text="o ", to=journal.Destination.daily_log(TODAY), today=TODAY
        )


def test_triage_places_a_capture_on_the_current_months_task_list():
    entry = journal.triage(
        _capture("* renew passport"),
        to=journal.Destination.monthly_log(TODAY),
        today=TODAY,
    )

    assert (entry.location, entry.month, entry.day) == (
        journal.Location.MONTH,
        date(2026, 10, 1),
        None,
    )
    assert (entry.type, entry.priority, entry.text) == (
        journal.EntryType.TASK,
        True,
        "renew passport",
    )


@pytest.mark.parametrize("month", [date(2026, 9, 1), date(2026, 11, 1)])
def test_a_capture_goes_only_on_the_current_months_task_list(month):
    # The refusal says how to proceed: a month left in the field picks another month.
    reason = "only on the current month's task list: clear the Future Log month"
    with pytest.raises(journal.PlacementError, match=reason):
        journal.triage(
            _capture("renew passport"), to=journal.Destination.monthly_log(month), today=TODAY
        )


def test_an_event_cannot_be_triaged_onto_the_months_task_list():
    with pytest.raises(journal.EventNeedsDateError):
        journal.triage(
            _capture("o conference"), to=journal.Destination.monthly_log(TODAY), today=TODAY
        )


@pytest.mark.parametrize("on", [None, date(2027, 3, 3)])
def test_triage_places_a_capture_in_the_future_log_with_an_optional_date(on):
    entry = journal.triage(
        _capture("o conference"),
        to=journal.Destination.future_log(date(2027, 3, 1), on=on),
        today=TODAY,
    )

    assert (entry.location, entry.month, entry.day, entry.type) == (
        journal.Location.FUTURE,
        date(2027, 3, 1),
        on,
        journal.EntryType.EVENT,
    )


def test_a_capture_goes_in_the_future_log_only_under_a_later_month():
    with pytest.raises(journal.NotAFutureMonthError):
        journal.triage(
            _capture("plan trip"), to=journal.Destination.future_log(TODAY), today=TODAY
        )


def test_a_future_log_date_must_fall_in_its_month():
    with pytest.raises(journal.DateOutsideMonthError):
        journal.triage(
            _capture("plan trip"),
            to=journal.Destination.future_log(date(2027, 3, 1), on=date(2027, 4, 2)),
            today=TODAY,
        )


@pytest.mark.parametrize(
    ("raw", "offered"),
    [
        ("*o 9am dentist", "*o 09:00 dentist"),
        ("call the plumber", "call the plumber"),
        (".5 miles run", ".5 miles run"),
    ],
)
def test_the_suggestion_is_offered_as_typed_so_it_can_be_adjusted(raw, offered):
    assert journal.as_typed(journal.triage_suggestion(_capture(raw))) == offered
