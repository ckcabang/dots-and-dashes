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
