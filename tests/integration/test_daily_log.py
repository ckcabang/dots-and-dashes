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


def _log_texts(client, *texts: str) -> dict[str, int]:
    ids = {}
    for text in texts:
        created = client.post("/api/entries", json={"text": text})
        assert created.status_code == 201
        ids[created.json()["text"]] = created.json()["id"]
    return ids


def _todays_texts(client) -> list[str]:
    daily_log = client.get("/api/daily-logs/today").json()
    return [entry["text"] for entry in daily_log["entries"]]


def test_a_new_untimed_entry_goes_to_the_bottom_of_the_daily_log_texts(app_client):
    with app_client() as client:
        _log_texts(client, ". 9am standup", ". 7am gym", "prep notes")

        assert _todays_texts(client) == ["gym", "standup", "prep notes"]


def test_a_dragged_untimed_entry_stays_where_it_was_dropped(app_client):
    with app_client() as client:
        ids = _log_texts(client, "buy milk", ". 9am standup", ". 12:00 lunch", "book a table")
        moved = client.post(f"/api/entries/{ids['buy milk']}/move", json={"to": 1})

    assert moved.status_code == 200

    with app_client() as client:
        assert _todays_texts(client) == ["standup", "buy milk", "lunch", "book a table"]


def test_a_timed_entry_cannot_be_dragged(app_client):
    with app_client() as client:
        ids = _log_texts(client, ". 9am standup", ". 12:00 lunch")
        refused = client.post(f"/api/entries/{ids['lunch']}/move", json={"to": 0})

        assert refused.status_code == 422
        assert _todays_texts(client) == ["standup", "lunch"]


def test_changing_a_timed_entrys_time_takes_its_anchored_entries_along(app_client):
    with app_client() as client:
        ids = _log_texts(client, ". 9am standup", "prep notes", ". 12:00 lunch")
        changed = client.post(
            f"/api/entries/{ids['standup']}/time", json={"time": "14:00"}
        )

    assert changed.status_code == 200

    with app_client() as client:
        assert _todays_texts(client) == ["lunch", "standup", "prep notes"]
        daily_log = client.get("/api/daily-logs/today").json()
        assert daily_log["entries"][1]["time"] == "14:00:00"


def test_moving_an_entry_from_the_page_returns_the_reordered_daily_log_texts(app_client):
    with app_client() as client:
        ids = _log_texts(client, ". 9am standup", "prep notes", ". 12:00 lunch")
        moved = client.post(
            f"/entries/{ids['prep notes']}/move",
            data={"to": "2"},
            headers={"HX-Request": "true"},
        )

    assert moved.status_code == 200
    text = moved.text
    assert text.index("standup") < text.index("lunch") < text.index("prep notes")


def _log(client, *texts: str) -> list[int]:
    return [client.post("/api/entries", json={"text": text}).json()["id"] for text in texts]


def _layout(client) -> list[tuple[str, str | None]]:
    """Today's Daily Log as (text, parent's text) pairs, in display order."""
    entries = client.get("/api/daily-logs/today").json()["entries"]
    texts = {entry["id"]: entry["text"] for entry in entries}
    return [(entry["text"], texts.get(entry["parent_id"])) for entry in entries]


def test_a_note_nested_under_a_task_shows_under_it_and_moves_with_it(app_client):
    with app_client() as client:
        _, dentist, card = _log(client, "o 9am standup", ". 3pm dentist", "- bring card")
        nested = client.post(f"/api/entries/{card}/nest")
        _log(client, "o 10am coffee")

    assert nested.status_code == 200
    assert nested.json()["parent_id"] == dentist

    with app_client() as client:
        assert _layout(client) == [
            ("standup", None),
            ("coffee", None),
            ("dentist", None),
            ("bring card", "dentist"),
        ]


def test_a_nested_note_can_be_un_nested(app_client):
    with app_client() as client:
        _, card = _log(client, ". dentist", "- bring card")
        client.post(f"/api/entries/{card}/nest")
        un_nested = client.post(f"/api/entries/{card}/un-nest")

    assert un_nested.status_code == 200

    with app_client() as client:
        assert _layout(client) == [("dentist", None), ("bring card", None)]


def test_a_note_cannot_nest_under_a_note_and_a_task_cannot_nest(app_client):
    with app_client() as client:
        _, card, cab = _log(client, "- the cafe opens at 7", "- and closes at 3", ". book a cab")
        under_note = client.post(f"/api/entries/{card}/nest")
        task = client.post(f"/api/entries/{cab}/nest")
        layout = _layout(client)

    assert (under_note.status_code, task.status_code) == (422, 422)
    assert all(parent is None for _, parent in layout)


def test_nesting_an_entry_that_does_not_exist_is_not_found(app_client):
    with app_client() as client:
        assert client.post("/api/entries/999/nest").status_code == 404


def test_nesting_from_the_page_returns_the_daily_log_with_the_note_indented(app_client):
    with app_client() as client:
        _, card = _log(client, ". dentist", "- bring card")
        fragment = client.post(f"/entries/{card}/nest", headers={"HX-Request": "true"})
        page = client.get("/")

    assert fragment.status_code == 200
    for html in (fragment.text, page.text):
        assert html.index("dentist") < html.index("bring card")
        assert html.count('entry--nested"') == 1
