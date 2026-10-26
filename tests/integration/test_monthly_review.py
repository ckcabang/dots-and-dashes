"""Monthly Review over HTTP, behind the FLAG_MONTHLY_REVIEW feature flag.

Entries are logged with the shared clock, on 2026-10-25 in Los Angeles (see
conftest), and the Monthly Review is opened in November.
"""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from dots_and_dashes.settings import Settings
from dots_and_dashes.web import create_app

# 09:00 on 1 and 12 November 2026 in Los Angeles.
FIRST = datetime(2026, 11, 1, 17, 0, tzinfo=UTC)
TWELFTH = datetime(2026, 11, 12, 17, 0, tzinfo=UTC)


@pytest.fixture
def flagged(settings):
    return replace(settings, monthly_review=True)


@pytest.fixture
def october(flagged, clock, logged_in):
    with logged_in(create_app(flagged, clock=clock)) as client:
        yield client


@pytest.fixture
def november(flagged, logged_in):
    with logged_in(create_app(flagged, clock=lambda: FIRST)) as client:
        yield client


def _log(client, text, day="2026-10-20"):
    return client.post("/api/entries", json={"text": text, "day": day}).json()["id"]


def _log_future(client, text, on=None):
    body = {"text": text, "month": "2026-11", **({"date": on} if on else {})}
    return client.post("/api/future-log/entries", json=body).json()["id"]


def _texts(entries):
    return [entry["text"] for entry in entries]


def test_with_the_flag_off_the_monthly_review_is_hidden_and_unavailable(settings, logged_in):
    with logged_in(create_app(settings, clock=lambda: FIRST)) as client:
        monthly_log = client.get("/months/2026-11").text
        responses = [
            client.get("/monthly-review"),
            client.post("/monthly-review/pull"),
            client.get("/api/monthly-review"),
            client.post("/api/monthly-review/pull"),
        ]

    assert 'href="/monthly-review"' not in monthly_log
    assert [r.status_code for r in responses] == [404, 404, 404, 404]


def test_with_the_flag_on_the_monthly_log_links_to_the_monthly_review(november):
    monthly_log = november.get("/months/2026-11").text
    page = november.get("/monthly-review")

    assert 'href="/monthly-review"' in monthly_log
    assert page.status_code == 200


def test_the_flag_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://unused/unused_test")
    monkeypatch.delenv("FLAG_MONTHLY_REVIEW", raising=False)
    assert not Settings.from_env().monthly_review
    for on in ["1", "true", "on"]:
        monkeypatch.setenv("FLAG_MONTHLY_REVIEW", on)
        assert Settings.from_env().monthly_review
    monkeypatch.setenv("FLAG_MONTHLY_REVIEW", "0")
    assert not Settings.from_env().monthly_review


def test_the_monthly_review_lists_last_months_open_tasks(october, november):
    _log(october, "write report")
    completed = _log(october, "file taxes")
    october.post(f"/api/entries/{completed}/complete")
    october.post("/api/monthly-logs/2026-10/entries", json={"text": "pay rent"})

    review = november.get("/api/monthly-review").json()

    assert review["month"] == "2026-11"
    assert _texts(review["task_list"]) == ["pay rent"]
    assert [(d["date"], _texts(d["tasks"])) for d in review["days"]] == [
        ("2026-10-20", ["write report"])
    ]


def test_a_leftover_migrated_to_this_months_task_list_leaves_the_review(october, november):
    task = _log(october, "write report")

    november.post(f"/api/entries/{task}/migrate", json={"to": "month"})

    assert november.get("/api/monthly-review").json()["days"] == []
    tasks = november.get("/api/monthly-logs/2026-11").json()["tasks"]
    assert [(t["text"], t["migration_count"]) for t in tasks] == [("write report", 1)]


def test_pulling_brings_this_months_future_log_into_the_monthly_log(october, november):
    _log_future(october, "renew passport")
    _log_future(october, ". 9:30 flu jab", on="2026-11-09")
    wedding = _log_future(october, "o wedding", on="2026-11-14")
    _log_future(october, "o leaving party")
    _log_future(october, "book holiday")
    october.post("/api/future-log/entries", json={"text": "buy presents", "month": "2026-12"})

    before = november.get("/api/monthly-review").json()
    pulled = november.post("/api/monthly-review/pull")
    after = pulled.json()

    assert _texts(before["to_pull"]) == ["flu jab", "wedding", "renew passport", "book holiday"]
    assert pulled.status_code == 200
    assert after["to_pull"] == []
    assert [w["event"]["text"] for w in after["needs_a_date"]] == ["leaving party"]
    tasks = november.get("/api/monthly-logs/2026-11").json()["tasks"]
    assert [(t["text"], t["state"], t["migration_count"]) for t in tasks] == [
        ("renew passport", "open", 1),
        ("book holiday", "open", 1),
    ]
    [jab] = november.get("/api/daily-logs/2026-11-09").json()["entries"]
    assert (jab["text"], jab["time"], jab["state"]) == ("flu jab", "09:30:00", "open")
    [event] = november.get("/api/daily-logs/2026-11-14").json()["entries"]
    assert (event["id"], event["location"]) == (wedding, "day")
    # The Future Log originals are Migrated, so they can no longer be completed.
    assert november.post(f"/api/entries/{jab['migrated_from_id']}/complete").status_code == 409


def test_pulling_again_brings_in_nothing_more(october, november):
    _log_future(october, "renew passport")

    november.post("/api/monthly-review/pull")
    november.post("/api/monthly-review/pull")

    assert _texts(november.get("/api/monthly-logs/2026-11").json()["tasks"]) == [
        "renew passport"
    ]


def test_an_undated_event_is_pulled_once_it_is_given_a_date(october, november):
    party = _log_future(october, "o leaving party")

    moved = november.post(f"/monthly-review/entries/{party}/date", data={"date": "2026-11-20"})

    assert moved.status_code == 200  # redirected back to the review
    assert november.get("/api/monthly-review").json()["needs_a_date"] == []
    assert _texts(november.get("/api/daily-logs/2026-11-20").json()["entries"]) == [
        "leaving party"
    ]


def test_the_monthly_review_still_works_when_opened_after_the_first(october, flagged, logged_in):
    _log(october, "write report")
    _log_future(october, "flu jab", on="2026-11-03")

    with logged_in(create_app(flagged, clock=lambda: TWELFTH)) as twelfth:
        review = twelfth.get("/api/monthly-review").json()
        twelfth.post("/api/monthly-review/pull")
        page = twelfth.get("/monthly-review")
        today = twelfth.get("/api/daily-logs/today").json()["entries"]

    assert [_texts(d["tasks"]) for d in review["days"]] == [["write report"]]
    assert page.status_code == 200 and "write report" in page.text
    # The day it was dated has passed, and a Task only moves forward.
    assert _texts(today) == ["flu jab"]


def test_the_review_page_pulls_and_returns_to_the_review(october, november):
    _log_future(october, "renew passport")

    page = november.get("/monthly-review").text
    pulled = november.post("/monthly-review/pull")

    assert "renew passport" in page and 'action="/monthly-review/pull"' in page
    assert pulled.status_code == 200 and pulled.url.path == "/monthly-review"
    assert _texts(november.get("/api/monthly-logs/2026-11").json()["tasks"]) == [
        "renew passport"
    ]


def test_a_waiting_event_is_given_a_day_this_month_only(october, november):
    party = _log_future(october, "o leaving party")

    page = november.get("/monthly-review").text
    refused = november.post(f"/monthly-review/entries/{party}/date", data={"date": "2026-12-04"})

    assert f'action="/monthly-review/entries/{party}/date"' in page
    assert 'max="2026-11-30"' in page
    assert refused.status_code == 422
    assert len(november.get("/api/monthly-review").json()["needs_a_date"]) == 1


def test_a_future_log_event_is_not_moved_by_changing_its_date_outside_the_review(october):
    party = _log_future(october, "o leaving party")

    refused = october.post(f"/api/entries/{party}/date", json={"date": "2026-11-20"})

    assert refused.status_code == 422
