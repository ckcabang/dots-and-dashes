from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from dots_and_dashes.web import create_app


@pytest.fixture
def app_client(settings, clock):
    """Start a fresh app instance against the test database.

    Opening a second client proves an Entry outlived the first app's process
    state, so it can only have come back from Postgres.
    """

    @contextmanager
    def start():
        with TestClient(create_app(settings, clock=clock)) as client:
            yield client

    return start


def test_a_task_created_through_the_api_is_on_todays_daily_log(app_client):
    with app_client() as client:
        created = client.post("/api/entries", json={"text": "buy milk"})

    assert created.status_code == 201

    with app_client() as client:
        daily_log = client.get("/api/daily-logs/today").json()

    assert daily_log["date"] == "2026-10-25"
    assert [
        (entry["type"], entry["state"], entry["text"])
        for entry in daily_log["entries"]
    ] == [("task", "open", "buy milk")]


def test_quick_entry_on_todays_daily_log_page_survives_a_reload(app_client):
    with app_client() as client:
        page = client.get("/")
        submitted = client.post("/entries", data={"text": "buy milk"})

    assert "2026-10-25" in page.text
    assert submitted.status_code == 200
    assert "buy milk" in submitted.text

    with app_client() as client:
        reloaded = client.get("/")

    assert "buy milk" in reloaded.text


def test_blank_text_is_refused_and_logs_nothing(app_client):
    with app_client() as client:
        refused = client.post("/api/entries", json={"text": "   "})
        daily_log = client.get("/api/daily-logs/today").json()

    assert refused.status_code == 422
    assert daily_log["entries"] == []


def test_quick_entry_from_htmx_returns_just_the_new_task(app_client):
    with app_client() as client:
        added = client.post(
            "/entries", data={"text": "buy milk"}, headers={"HX-Request": "true"}
        )

    assert added.status_code == 201
    assert added.text.lstrip().startswith("<li")
    assert "buy milk" in added.text


def test_a_future_dates_daily_log_can_be_opened(app_client):
    with app_client() as client:
        page = client.get("/days/2026-10-31")
        daily_log = client.get("/api/daily-logs/2026-10-31")

    assert page.status_code == 200
    assert 'datetime="2026-10-31"' in page.text
    assert daily_log.json() == {"date": "2026-10-31", "entries": []}


def test_a_daily_log_links_to_the_previous_and_next_day(app_client):
    with app_client() as client:
        page = client.get("/days/2026-11-01")

    assert 'href="/days/2026-10-31"' in page.text
    assert 'href="/days/2026-11-02"' in page.text


def test_choosing_a_date_opens_its_daily_log(app_client):
    with app_client() as client:
        chosen = client.get(
            "/days", params={"date": "2026-12-25"}, follow_redirects=False
        )

    assert chosen.status_code == 303
    assert chosen.headers["location"] == "/days/2026-12-25"


def test_a_date_that_does_not_exist_has_no_daily_log(app_client):
    with app_client() as client:
        page = client.get("/days/2026-02-30")

    assert page.status_code == 422


def test_quick_entry_lands_on_the_daily_log_being_viewed(app_client):
    with app_client() as client:
        page = client.get("/days/2026-10-31")
        submitted = client.post(
            "/entries", data={"text": "pack bags", "day": "2026-10-31"}
        )
        viewed = client.get("/api/daily-logs/2026-10-31").json()
        today = client.get("/api/daily-logs/today").json()

    assert 'name="day" value="2026-10-31"' in page.text
    assert "pack bags" in submitted.text
    assert [entry["text"] for entry in viewed["entries"]] == ["pack bags"]
    assert today["entries"] == []


def test_an_entry_created_through_the_api_can_go_on_any_day(app_client):
    with app_client() as client:
        created = client.post(
            "/api/entries", json={"text": "pack bags", "day": "2026-10-31"}
        )
        viewed = client.get("/api/daily-logs/2026-10-31").json()

    assert created.json()["day"] == "2026-10-31"
    assert [entry["text"] for entry in viewed["entries"]] == ["pack bags"]
