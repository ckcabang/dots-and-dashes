"""Captures, the Inbox and Triage. Today is 2026-10-25 (see conftest)."""

import pytest

from dots_and_dashes.web import create_app


@pytest.fixture
def client(settings, clock, logged_in):
    with logged_in(create_app(settings, clock=clock)) as client:
        yield client


def test_a_capture_waits_in_the_inbox_unclassified(client):
    captured = client.post("/api/captures", json={"text": "o 9am dentist"})

    assert captured.status_code == 201, captured.text
    inbox = _read(client, "/api/inbox")
    assert inbox["count"] == 1
    [capture] = inbox["captures"]
    assert capture["text"] == "o 9am dentist"
    assert _read(client, "/api/daily-logs/today")["entries"] == []


def _read(client, path: str):
    """GET a JSON page, failing on its status with the body, not later on a missing key."""
    response = client.get(path)
    assert response.status_code == 200, response.text
    return response.json()


def _capture(client, text: str) -> int:
    captured = client.post("/api/captures", json={"text": text})
    assert captured.status_code == 201, captured.text
    return captured.json()["id"]


def _texts(entries):
    return [entry["text"] for entry in entries]


def test_triage_places_a_capture_on_a_days_daily_log_and_empties_the_inbox(client):
    capture_id = _capture(client, "*o 9am dentist")

    triaged = client.post(
        f"/api/captures/{capture_id}/triage", json={"to": "day", "date": "2026-10-28"}
    )

    assert triaged.status_code == 201, triaged.text
    [entry] = _read(client, "/api/daily-logs/2026-10-28")["entries"]
    assert (entry["type"], entry["priority"], entry["time"], entry["text"]) == (
        "event",
        True,
        "09:00:00",
        "dentist",
    )
    assert triaged.json() == entry
    assert _read(client, "/api/inbox") == {"count": 0, "captures": []}


def test_triage_places_a_capture_on_the_current_months_task_list(client):
    capture_id = _capture(client, "* renew passport")

    triaged = client.post(f"/api/captures/{capture_id}/triage", json={"to": "month"})

    assert triaged.status_code == 201, triaged.text
    [entry] = _read(client, "/api/monthly-logs/2026-10")["tasks"]
    assert (entry["text"], entry["priority"], entry["state"]) == ("renew passport", True, "open")
    assert _read(client, "/api/inbox")["count"] == 0


@pytest.mark.parametrize("on", [None, "2027-03-03"])
def test_triage_places_a_capture_in_the_future_log_with_an_optional_date(client, on):
    capture_id = _capture(client, "o conference")

    triaged = client.post(
        f"/api/captures/{capture_id}/triage", json={"to": "future", "month": "2027-03", "date": on}
    )

    assert triaged.status_code == 201, triaged.text
    future_log = _read(client, "/api/future-log")
    [march] = [bucket for bucket in future_log["months"] if bucket["month"] == "2027-03"]
    [entry] = march["entries"]
    assert (entry["type"], entry["text"], entry["day"]) == ("event", "conference", on)
    assert _read(client, "/api/inbox")["count"] == 0


def test_triage_to_a_date_lands_on_its_daily_log_this_month_or_in_the_future_log(client):
    soon = _capture(client, "o dentist")
    later = _capture(client, "o conference")

    for capture_id, on in [(soon, "2026-10-28"), (later, "2027-03-03")]:
        triaged = client.post(
            f"/api/captures/{capture_id}/triage", json={"to": "date", "date": on}
        )
        assert triaged.status_code == 201

    assert _texts(client.get("/api/daily-logs/2026-10-28").json()["entries"]) == ["dentist"]
    future_log = client.get("/api/future-log").json()
    [march] = [bucket for bucket in future_log["months"] if bucket["month"] == "2027-03"]
    assert [(e["text"], e["day"]) for e in march["entries"]] == [("conference", "2027-03-03")]


def test_the_inbox_shows_what_triage_suggests_for_each_capture(client):
    _capture(client, "!- 2:30pm idea for the garden")

    [capture] = _read(client, "/api/inbox")["captures"]

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

    triaged = client.post(
        f"/api/captures/{capture_id}/triage",
        json={"to": "day", "text": "*. book the dentist"},
    )

    assert triaged.status_code == 201, triaged.text
    [entry] = _read(client, "/api/daily-logs/today")["entries"]
    assert (entry["type"], entry["priority"], entry["time"], entry["text"]) == (
        "task",
        True,
        None,
        "book the dentist",
    )


def test_a_refused_triage_leaves_the_capture_in_the_inbox(client):
    capture_id = _capture(client, "o conference")

    refused = client.post(f"/api/captures/{capture_id}/triage", json={"to": "month"})

    assert refused.status_code == 422, refused.text
    assert _read(client, "/api/monthly-logs/2026-10")["tasks"] == []
    assert _read(client, "/api/inbox")["count"] == 1


def test_a_blank_capture_is_refused(client):
    refused = client.post("/api/captures", json={"text": "  "})

    assert refused.status_code == 422, refused.text
    assert _read(client, "/api/inbox")["count"] == 0


def test_a_capture_can_be_deleted(client):
    kept = _capture(client, "call the plumber")
    deleted = _capture(client, "asdfgh")

    response = client.delete(f"/api/captures/{deleted}")

    assert response.status_code == 204, response.text
    inbox = _read(client, "/api/inbox")
    assert [capture["id"] for capture in inbox["captures"]] == [kept]
    assert _read(client, "/api/daily-logs/today")["entries"] == []


def test_the_mobile_capture_page_saves_raw_text_to_the_inbox(client):
    page = client.get("/capture")
    assert page.status_code == 200, page.text
    assert 'name="viewport"' in page.text

    submitted = client.post("/capture", data={"text": "o 9am dentist"}, follow_redirects=False)

    assert submitted.status_code == 303, submitted.text
    assert submitted.headers["location"] == "/capture?captured=1"
    assert _texts(_read(client, "/api/inbox")["captures"]) == ["o 9am dentist"]
    assert _read(client, "/api/daily-logs/today")["entries"] == []


def test_the_daily_log_shows_the_inbox_count(client):
    _capture(client, "call the plumber")
    _capture(client, "o 9am dentist")

    page = client.get("/")

    assert page.status_code == 200, page.text
    assert 'href="/inbox"' in page.text
    assert "Inbox (2)" in page.text


def test_the_inbox_page_offers_the_oldest_capture_to_triage_with_its_suggestion(client):
    _capture(client, "*o 9am dentist")
    _capture(client, "call the plumber")

    page = client.get("/inbox")

    assert page.status_code == 200, page.text
    assert 'value="*o 09:00 dentist"' in page.text
    assert "Event" in page.text
    assert "call the plumber" in page.text


def test_triage_from_the_page_reads_empty_optional_fields_as_unset(client):
    to_day = _capture(client, "o 9am dentist")
    to_future = _capture(client, "conference")

    placed = client.post(
        f"/inbox/{to_day}/triage",
        data={"text": "o 9am dentist", "to": "day", "date": "", "month": ""},
        follow_redirects=False,
    )
    placed_in_the_future = client.post(
        f"/inbox/{to_future}/triage",
        data={"text": "o conference", "to": "future", "date": "", "month": "2027-03"},
        follow_redirects=False,
    )

    assert placed.status_code == 303, placed.text
    assert placed_in_the_future.status_code == 303, placed_in_the_future.text
    assert placed.headers["location"] == "/inbox"
    assert _texts(_read(client, "/api/daily-logs/today")["entries"]) == ["dentist"]
    future_log = _read(client, "/api/future-log")
    [march] = [bucket for bucket in future_log["months"] if bucket["month"] == "2027-03"]
    assert _texts(march["entries"]) == ["conference"]
    assert _read(client, "/api/inbox")["count"] == 0


def test_a_refused_triage_from_the_page_says_why_and_keeps_the_adjustment(client):
    capture_id = _capture(client, "conference")

    refused = client.post(
        f"/inbox/{capture_id}/triage",
        data={"text": "o big conference", "to": "month", "date": "", "month": ""},
    )

    assert refused.status_code == 422, refused.text
    assert 'role="alert"' in refused.text
    assert 'value="o big conference"' in refused.text
    assert _read(client, "/api/inbox")["count"] == 1


@pytest.mark.parametrize(
    ("to", "on", "month", "reason"),
    [
        pytest.param("day", "2026-02-30", "", "'2026-02-30' is not a date", id="date"),
        pytest.param("future", "", "2026-13", "'2026-13' is not a month", id="month"),
    ],
)
def test_triage_from_the_page_refuses_an_impossible_date_or_month(client, to, on, month, reason):
    capture_id = _capture(client, "conference")

    refused = client.post(
        f"/inbox/{capture_id}/triage",
        data={"text": "o big conference", "to": to, "date": on, "month": month},
    )

    assert refused.status_code == 422, refused.text
    assert refused.headers["content-type"].startswith("text/html")
    assert f'<p role="alert">{reason.replace("\'", "&#39;")}</p>' in refused.text
    assert 'value="o big conference"' in refused.text
    assert f'value="{on}"' in refused.text
    assert f'value="{month}"' in refused.text
    assert _read(client, "/api/inbox")["count"] == 1


@pytest.mark.parametrize(
    "placing",
    [
        pytest.param({"to": "day", "date": "2026-02-30"}, id="date"),
        pytest.param({"to": "future", "month": "2026-13"}, id="month"),
    ],
)
def test_the_api_refuses_an_impossible_triage_date_or_month(client, placing):
    capture_id = _capture(client, "conference")

    refused = client.post(f"/api/captures/{capture_id}/triage", json=placing)

    assert refused.status_code == 422, refused.text
    assert "detail" in refused.json()
    assert _read(client, "/api/inbox")["count"] == 1


def test_a_capture_is_deleted_from_the_page(client):
    capture_id = _capture(client, "asdfgh")

    deleted = client.post(f"/inbox/{capture_id}/delete", follow_redirects=False)

    assert deleted.status_code == 303, deleted.text
    assert deleted.headers["location"] == "/inbox"
    assert _read(client, "/api/inbox")["count"] == 0


def test_another_users_inbox_is_out_of_reach(settings, clock, logged_in, create_user):
    app = create_app(settings, clock=clock)
    with logged_in(app) as client:
        capture_id = _capture(client, "my secret")
    other = create_user("canary@example.com", canary=True)

    with logged_in(app, other) as canary:
        assert _read(canary, "/api/inbox") == {"count": 0, "captures": []}
        deleted = canary.delete(f"/api/captures/{capture_id}")
        assert deleted.status_code == 404, deleted.text
        refused = canary.post(f"/api/captures/{capture_id}/triage", json={"to": "day"})
        assert refused.status_code == 404, refused.text
