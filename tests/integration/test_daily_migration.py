"""Daily Migration over HTTP.

The shared clock reads 20:00 on 2026-10-25 in Los Angeles (see conftest): the
evening, so Daily Migration plans the 26th. A morning clock plans the 25th.
"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from dots_and_dashes.web import create_app

# 07:00 on 2026-10-25 in Los Angeles.
MORNING = datetime(2026, 10, 25, 14, 0, tzinfo=UTC)


@pytest.fixture
def client(settings, clock):
    with TestClient(create_app(settings, clock=clock)) as client:
        yield client


@pytest.fixture
def morning(settings):
    with TestClient(create_app(settings, clock=lambda: MORNING)) as client:
        yield client


def _log(client, text, day):
    return client.post("/api/entries", json={"text": text, "day": day}).json()["id"]


def _review(client):
    return client.get("/api/daily-migration").json()


def _grouped(review):
    return [
        (
            day["date"],
            group["anchor"]["text"] if group["anchor"] else None,
            [task["text"] for task in group["tasks"]],
        )
        for day in review["days"]
        for group in day["groups"]
    ]


def test_in_the_evening_daily_migration_reviews_today_and_plans_tomorrow(client):
    _log(client, "call mum", "2026-09-02")
    _log(client, "write report", "2026-10-25")
    _log(client, "already tomorrow", "2026-10-26")

    review = _review(client)

    assert (review["planning"], review["night_before"]) == ("2026-10-26", True)
    assert _grouped(review) == [
        ("2026-09-02", None, ["call mum"]),
        ("2026-10-25", None, ["write report"]),
    ]


def test_in_the_morning_daily_migration_reviews_earlier_days_and_plans_today(client, morning):
    _log(client, "call mum", "2026-10-24")
    _log(client, "write report", "2026-10-25")

    review = _review(morning)

    assert (review["planning"], review["night_before"]) == ("2026-10-25", False)
    assert _grouped(review) == [("2026-10-24", None, ["call mum"])]


def test_open_tasks_are_grouped_under_their_anchor(client):
    for text in ["water plants", "o 14:00 team offsite", "book room", "o 09:00 standup"]:
        _log(client, text, "2026-10-24")
    completed = _log(client, "send agenda", "2026-10-24")
    client.post(f"/api/entries/{completed}/complete")

    assert _grouped(_review(client)) == [
        ("2026-10-24", None, ["water plants"]),
        ("2026-10-24", "team offsite", ["book room"]),
    ]


def test_a_decided_task_leaves_daily_migration(client):
    migrated = _log(client, "write report", "2026-10-24")
    completed = _log(client, "file taxes", "2026-10-24")
    _log(client, "call mum", "2026-10-24")
    planning = _review(client)["planning"]

    client.post(
        f"/api/entries/{migrated}/migrate",
        json={"to": "day", "date": planning, "night_before": True},
    )
    client.post(f"/api/entries/{completed}/complete")

    assert _grouped(_review(client)) == [("2026-10-24", None, ["call mum"])]
    assert [e["text"] for e in client.get(f"/api/daily-logs/{planning}").json()["entries"]] == [
        "write report"
    ]


def test_skipping_daily_migration_changes_nothing(client):
    _log(client, "write report", "2026-10-23")
    _log(client, "o 10:00 dentist", "2026-10-24")
    _log(client, "call mum", "2026-10-24")
    before = {
        day: client.get(f"/api/daily-logs/{day}").json()
        for day in ["2026-10-23", "2026-10-24", "2026-10-25", "2026-10-26"]
    }

    page = client.get("/migration")
    review = _review(client)

    assert page.status_code == 200
    assert "write report" in page.text and "call mum" in page.text
    assert _review(client) == review
    assert {day: client.get(f"/api/daily-logs/{day}").json() for day in before} == before
