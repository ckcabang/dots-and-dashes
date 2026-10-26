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


def test_quick_entry_from_htmx_returns_the_daily_log_with_the_new_task(app_client):
    with app_client() as client:
        added = client.post(
            "/entries", data={"text": "buy milk"}, headers={"HX-Request": "true"}
        )

    assert added.status_code == 201
    assert added.text.lstrip().startswith("<li")
    assert "buy milk" in added.text


def test_the_prefix_sets_signifiers_type_and_time_on_todays_daily_log(app_client):
    with app_client() as client:
        for text in ["*!- idea", "o 7pm dinner", "*. 14:00 call mom", ".5 miles run"]:
            assert client.post("/api/entries", json={"text": text}).status_code == 201

    with app_client() as client:
        daily_log = client.get("/api/daily-logs/today").json()

    assert [
        (
            entry["type"],
            entry["state"],
            entry["priority"],
            entry["inspiration"],
            entry["time"],
            entry["text"],
        )
        for entry in daily_log["entries"]
    ] == [
        ("note", None, True, True, None, "idea"),
        ("task", "open", True, False, "14:00:00", "call mom"),
        ("event", None, False, False, "19:00:00", "dinner"),
        ("task", "open", False, False, None, ".5 miles run"),
    ]


def test_the_daily_log_page_shows_signifiers_type_and_time(app_client):
    with app_client() as client:
        client.post("/entries", data={"text": "*!o 2:30pm dentist"})
        page = client.get("/")

    assert 'class="signifier signifier--priority"' in page.text
    assert 'class="signifier signifier--inspiration"' in page.text
    assert "entry--event" in page.text
    assert '<time datetime="14:30">14:30</time>' in page.text
    assert "dentist" in page.text


def _log(client, *texts: str) -> dict[str, int]:
    ids = {}
    for text in texts:
        created = client.post("/api/entries", json={"text": text})
        assert created.status_code == 201
        ids[created.json()["text"]] = created.json()["id"]
    return ids


def _todays_texts(client) -> list[str]:
    daily_log = client.get("/api/daily-logs/today").json()
    return [entry["text"] for entry in daily_log["entries"]]


def test_a_new_untimed_entry_goes_to_the_bottom_of_the_daily_log(app_client):
    with app_client() as client:
        _log(client, ". 9am standup", ". 7am gym", "prep notes")

        assert _todays_texts(client) == ["gym", "standup", "prep notes"]


def test_a_dragged_untimed_entry_stays_where_it_was_dropped(app_client):
    with app_client() as client:
        ids = _log(client, "buy milk", ". 9am standup", ". 12:00 lunch", "book a table")
        moved = client.post(f"/api/entries/{ids['buy milk']}/move", json={"to": 1})

    assert moved.status_code == 200

    with app_client() as client:
        assert _todays_texts(client) == ["standup", "buy milk", "lunch", "book a table"]


def test_a_timed_entry_cannot_be_dragged(app_client):
    with app_client() as client:
        ids = _log(client, ". 9am standup", ". 12:00 lunch")
        refused = client.post(f"/api/entries/{ids['lunch']}/move", json={"to": 0})

        assert refused.status_code == 422
        assert _todays_texts(client) == ["standup", "lunch"]


def test_changing_a_timed_entrys_time_takes_its_anchored_entries_along(app_client):
    with app_client() as client:
        ids = _log(client, ". 9am standup", "prep notes", ". 12:00 lunch")
        changed = client.post(
            f"/api/entries/{ids['standup']}/time", json={"time": "14:00"}
        )

    assert changed.status_code == 200

    with app_client() as client:
        assert _todays_texts(client) == ["lunch", "standup", "prep notes"]
        daily_log = client.get("/api/daily-logs/today").json()
        assert daily_log["entries"][1]["time"] == "14:00:00"


def test_moving_an_entry_from_the_page_returns_the_reordered_daily_log(app_client):
    with app_client() as client:
        ids = _log(client, ". 9am standup", "prep notes", ". 12:00 lunch")
        moved = client.post(
            f"/entries/{ids['prep notes']}/move",
            data={"to": "2"},
            headers={"HX-Request": "true"},
        )

    assert moved.status_code == 200
    text = moved.text
    assert text.index("standup") < text.index("lunch") < text.index("prep notes")
