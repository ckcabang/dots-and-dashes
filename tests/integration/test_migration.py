"""Migrating and Scheduling Tasks over HTTP. Today is 2026-10-25.

Most tests run at 07:00, so the day being planned is today. The shared clock
(see conftest) reads 20:00, the night before, which plans tomorrow.
"""

from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from dots_and_dashes.web import create_app

# 07:00 on 2026-10-25 in Los Angeles.
MORNING = datetime(2026, 10, 25, 14, 0, tzinfo=UTC)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings, clock=lambda: MORNING)) as client:
        yield client


@pytest.fixture
def evening(settings, clock):
    with TestClient(create_app(settings, clock=clock)) as client:
        yield client


@pytest.fixture
def app_client(settings):
    """A fresh app instance, so what it shows can only have come from Postgres."""

    @contextmanager
    def start():
        with TestClient(create_app(settings, clock=lambda: MORNING)) as client:
            yield client

    return start


def _log(client, text="write report", day="2026-10-24"):
    return client.post("/api/entries", json={"text": text, "day": day}).json()["id"]


def _daily_log(client, day):
    return [
        (entry["state"], entry["text"], entry["migration_count"])
        for entry in client.get(f"/api/daily-logs/{day}").json()["entries"]
    ]


def test_a_task_migrated_to_today_is_copied_there_and_the_original_marked_migrated(
    client, app_client
):
    task = _log(client, "write report", day="2026-10-24")

    migrated = client.post(f"/api/entries/{task}/migrate", json={"to": "day", "date": "2026-10-25"})

    assert migrated.status_code == 200
    assert migrated.json()["original"]["state"] == "migrated"
    assert migrated.json()["copy"]["migrated_from_id"] == task
    with app_client() as fresh:
        assert _daily_log(fresh, "2026-10-24") == [("migrated", "write report", 1)]
        assert _daily_log(fresh, "2026-10-25") == [("open", "write report", 1)]


def test_the_night_before_a_task_migrated_to_tomorrow_is_marked_migrated(evening):
    task = _log(evening, day="2026-10-25")

    migrated = evening.post(f"/api/entries/{task}/migrate", json={"to": "day"})

    assert migrated.json()["original"]["state"] == "migrated"
    assert _daily_log(evening, "2026-10-26") == [("open", "write report", 1)]


def test_without_a_date_a_task_migrates_to_the_day_being_planned(client):
    task = _log(client, day="2026-10-20")

    migrated = client.post(f"/api/entries/{task}/migrate", json={"to": "day"})

    assert migrated.json()["original"]["state"] == "migrated"
    assert _daily_log(client, "2026-10-25") == [("open", "write report", 1)]


def test_in_the_morning_todays_task_is_already_on_the_day_being_planned(client):
    task = _log(client, day="2026-10-25")

    refused = client.post(f"/api/entries/{task}/migrate", json={"to": "day"})

    assert refused.status_code == 422
    assert _daily_log(client, "2026-10-25") == [("open", "write report", 0)]
    assert _daily_log(client, "2026-10-26") == []


def test_a_task_on_a_later_day_is_not_migrated_back_to_the_day_being_planned(client):
    task = _log(client, day="2026-10-28")

    refused = client.post(f"/api/entries/{task}/migrate", json={"to": "day"})

    assert refused.status_code == 422
    assert _daily_log(client, "2026-10-28") == [("open", "write report", 0)]
    assert _daily_log(client, "2026-10-25") == []


def test_the_user_can_plan_today_in_the_evening(evening):
    task = _log(evening, day="2026-10-24")

    migrated = evening.post(f"/api/entries/{task}/migrate", json={"to": "day", "plan": "today"})

    assert migrated.json()["original"]["state"] == "migrated"
    assert _daily_log(evening, "2026-10-25") == [("open", "write report", 1)]


def test_without_a_month_a_task_migrates_to_the_planned_days_task_list(evening):
    task = _log(evening, day="2026-10-24")

    migrated = evening.post(f"/api/entries/{task}/migrate", json={"to": "month"})

    assert migrated.json()["original"]["state"] == "migrated"
    tasks = evening.get("/api/monthly-logs/2026-10").json()["tasks"]
    assert [(t["state"], t["text"]) for t in tasks] == [("open", "write report")]


def test_a_task_scheduled_into_the_future_log_waits_under_its_month(client):
    task = _log(client, ". 10:00 renew passport")

    scheduled = client.post(
        f"/api/entries/{task}/migrate",
        json={"to": "future", "month": "2027-03", "date": "2027-03-03"},
    )

    assert scheduled.json()["original"]["state"] == "scheduled"
    march = next(
        bucket
        for bucket in client.get("/api/future-log").json()["months"]
        if bucket["month"] == "2027-03"
    )
    [copy] = march["entries"]
    assert (copy["text"], copy["time"], copy["day"], copy["state"]) == (
        "renew passport",
        "10:00:00",
        "2027-03-03",
        "open",
    )


def test_a_task_migrated_to_the_monthly_log_is_on_its_task_list(client):
    task = _log(client)

    client.post(f"/api/entries/{task}/migrate", json={"to": "month", "month": "2026-10"})

    tasks = client.get("/api/monthly-logs/2026-10").json()["tasks"]
    assert [(t["state"], t["text"]) for t in tasks] == [("open", "write report")]


def test_nested_notes_move_to_the_new_copy(client):
    task = _log(client, "write report")
    note = _log(client, "- draft is in the shared folder")
    client.post(f"/api/entries/{note}/nest")

    migrated = client.post(f"/api/entries/{task}/migrate", json={"to": "day", "date": "2026-10-25"})

    copy = migrated.json()["copy"]["id"]
    assert _daily_log(client, "2026-10-24") == [("migrated", "write report", 1)]
    today = client.get("/api/daily-logs/2026-10-25").json()["entries"]
    assert [(e["text"], e["parent_id"]) for e in today] == [
        ("write report", None),
        ("draft is in the shared folder", copy),
    ]


def test_each_copy_shows_the_migration_count_of_its_chain(client):
    task = _log(client, day="2026-10-20")
    second = client.post(
        f"/api/entries/{task}/migrate", json={"to": "day", "date": "2026-10-25"}
    ).json()["copy"]["id"]
    client.post(f"/api/entries/{second}/migrate", json={"to": "day", "date": "2026-10-29"})

    assert _daily_log(client, "2026-10-20") == [("migrated", "write report", 2)]
    assert _daily_log(client, "2026-10-25") == [("scheduled", "write report", 2)]
    assert _daily_log(client, "2026-10-29") == [("open", "write report", 2)]


def test_deleting_a_copy_mid_chain_re_links_the_chain_around_it(client):
    task = _log(client, day="2026-10-20")
    second = client.post(
        f"/api/entries/{task}/migrate", json={"to": "day", "date": "2026-10-25"}
    ).json()["copy"]["id"]
    third = client.post(
        f"/api/entries/{second}/migrate", json={"to": "day", "date": "2026-10-29"}
    ).json()["copy"]["id"]

    assert client.delete(f"/api/entries/{second}").status_code == 204

    assert _daily_log(client, "2026-10-20") == [("migrated", "write report", 1)]
    [last] = client.get("/api/daily-logs/2026-10-29").json()["entries"]
    assert (last["id"], last["migrated_from_id"], last["migration_count"]) == (third, task, 1)


@pytest.mark.parametrize("text", ["o dinner", "- slept badly"])
def test_events_and_notes_are_never_migrated(client, text):
    entry = _log(client, text)

    refused = client.post(
        f"/api/entries/{entry}/migrate", json={"to": "day", "date": "2026-10-25"}
    )

    assert refused.status_code == 422
    assert client.get("/api/daily-logs/2026-10-25").json()["entries"] == []


def test_a_task_cannot_be_migrated_into_the_past(client):
    task = _log(client)

    refused = client.post(f"/api/entries/{task}/migrate", json={"to": "day", "date": "2026-10-24"})

    assert refused.status_code == 422


def test_a_completed_task_cannot_be_migrated(client):
    task = _log(client)
    client.post(f"/api/entries/{task}/complete")

    refused = client.post(f"/api/entries/{task}/migrate", json={"to": "day", "date": "2026-10-25"})

    assert refused.status_code == 409


def test_an_event_moves_by_changing_its_date(client):
    dinner = _log(client, "o 7pm dinner")

    moved = client.post(f"/api/entries/{dinner}/date", json={"date": "2026-10-30"})

    assert moved.status_code == 200
    assert client.get("/api/daily-logs/2026-10-24").json()["entries"] == []
    [event] = client.get("/api/daily-logs/2026-10-30").json()["entries"]
    assert (event["id"], event["state"], event["migration_count"]) == (dinner, None, 0)


def test_the_daily_log_page_migrates_a_task_and_shows_its_marker(client):
    task = _log(client)
    htmx = {"HX-Request": "true"}

    migrated = client.post(
        f"/entries/{task}/migrate", data={"to": "day", "date": "2026-10-25"}, headers=htmx
    )
    scheduled = client.post(
        f"/entries/{_log(client, 'pay rent')}/migrate",
        data={"to": "date", "date": "2027-01-04"},
        headers=htmx,
    )

    assert migrated.status_code == 200
    assert 'data-state="migrated"' in migrated.text
    assert "&gt;&gt;1" in migrated.text
    assert 'data-state="scheduled"' in scheduled.text
    page = client.get("/days/2026-10-24").text
    assert page.count('class="state-marker"') == 2
    assert ">&gt;</span>" in page and ">&lt;</span>" in page
    january = client.get("/api/future-log").json()["months"][2]
    assert [(e["text"], e["day"]) for e in january["entries"]] == [("pay rent", "2027-01-04")]
