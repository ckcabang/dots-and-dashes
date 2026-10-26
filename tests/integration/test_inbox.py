"""Captures, the Inbox and Triage. Today is 2026-10-25 (see conftest)."""

import pytest

from dots_and_dashes.web import create_app


@pytest.fixture
def client(settings, clock, logged_in):
    with logged_in(create_app(settings, clock=clock)) as client:
        yield client


def test_a_capture_waits_in_the_inbox_unclassified(client):
    captured = client.post("/api/captures", json={"text": "o 9am dentist"})

    assert captured.status_code == 201
    inbox = client.get("/api/inbox").json()
    assert inbox["count"] == 1
    [capture] = inbox["captures"]
    assert capture["text"] == "o 9am dentist"
    assert client.get("/api/daily-logs/today").json()["entries"] == []


def _capture(client, text: str) -> int:
    return client.post("/api/captures", json={"text": text}).json()["id"]


def _texts(entries):
    return [entry["text"] for entry in entries]


def test_triage_places_a_capture_on_a_days_daily_log_and_empties_the_inbox(client):
    capture_id = _capture(client, "*o 9am dentist")

    triaged = client.post(
        f"/api/captures/{capture_id}/triage", json={"to": "day", "date": "2026-10-28"}
    )

    assert triaged.status_code == 201
    [entry] = client.get("/api/daily-logs/2026-10-28").json()["entries"]
    assert (entry["type"], entry["priority"], entry["time"], entry["text"]) == (
        "event",
        True,
        "09:00:00",
        "dentist",
    )
    assert triaged.json() == entry
    assert client.get("/api/inbox").json() == {"count": 0, "captures": []}


def test_triage_places_a_capture_on_the_current_months_task_list(client):
    capture_id = _capture(client, "* renew passport")

    triaged = client.post(f"/api/captures/{capture_id}/triage", json={"to": "month"})

    assert triaged.status_code == 201
    [entry] = client.get("/api/monthly-logs/2026-10").json()["tasks"]
    assert (entry["text"], entry["priority"], entry["state"]) == ("renew passport", True, "open")
    assert client.get("/api/inbox").json()["count"] == 0


@pytest.mark.parametrize("on", [None, "2027-03-03"])
def test_triage_places_a_capture_in_the_future_log_with_an_optional_date(client, on):
    capture_id = _capture(client, "o conference")

    triaged = client.post(
        f"/api/captures/{capture_id}/triage", json={"to": "future", "month": "2027-03", "date": on}
    )

    assert triaged.status_code == 201
    future_log = client.get("/api/future-log").json()
    [march] = [bucket for bucket in future_log["months"] if bucket["month"] == "2027-03"]
    [entry] = march["entries"]
    assert (entry["type"], entry["text"], entry["day"]) == ("event", "conference", on)
    assert client.get("/api/inbox").json()["count"] == 0


def test_the_inbox_shows_what_triage_suggests_for_each_capture(client):
    _capture(client, "!- 2:30pm idea for the garden")

    [capture] = client.get("/api/inbox").json()["captures"]

    assert capture["suggestion"] == {
        "type": "note",
        "priority": False,
        "inspiration": True,
        "time": "14:30:00",
        "text": "idea for the garden",
        "typed": "!- 14:30 idea for the garden",
    }


def test_an_adjusted_suggestion_is_what_gets_placed(client):
    capture_id = _capture(client, "o 9am dentist")

    client.post(
        f"/api/captures/{capture_id}/triage",
        json={"to": "day", "text": "*. book the dentist"},
    )

    [entry] = client.get("/api/daily-logs/today").json()["entries"]
    assert (entry["type"], entry["priority"], entry["time"], entry["text"]) == (
        "task",
        True,
        None,
        "book the dentist",
    )


def test_a_refused_triage_leaves_the_capture_in_the_inbox(client):
    capture_id = _capture(client, "o conference")

    refused = client.post(f"/api/captures/{capture_id}/triage", json={"to": "month"})

    assert refused.status_code == 422
    assert client.get("/api/monthly-logs/2026-10").json()["tasks"] == []
    assert client.get("/api/inbox").json()["count"] == 1


def test_a_blank_capture_is_refused(client):
    refused = client.post("/api/captures", json={"text": "  "})

    assert refused.status_code == 422
    assert client.get("/api/inbox").json()["count"] == 0


def test_a_capture_can_be_deleted(client):
    kept = _capture(client, "call the plumber")
    deleted = _capture(client, "asdfgh")

    response = client.delete(f"/api/captures/{deleted}")

    assert response.status_code == 204
    inbox = client.get("/api/inbox").json()
    assert [capture["id"] for capture in inbox["captures"]] == [kept]
    assert client.get("/api/daily-logs/today").json()["entries"] == []


def test_another_users_inbox_is_out_of_reach(settings, clock, logged_in, create_user):
    app = create_app(settings, clock=clock)
    with logged_in(app) as client:
        capture_id = _capture(client, "my secret")
    other = create_user("canary@example.com", canary=True)

    with logged_in(app, other) as canary:
        assert canary.get("/api/inbox").json() == {"count": 0, "captures": []}
        assert canary.delete(f"/api/captures/{capture_id}").status_code == 404
        refused = canary.post(f"/api/captures/{capture_id}/triage", json={"to": "day"})
        assert refused.status_code == 404
