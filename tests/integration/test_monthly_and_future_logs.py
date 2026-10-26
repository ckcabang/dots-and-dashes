"""The Monthly Log and the Future Log. Today is 2026-10-25 (see conftest)."""

import pytest

from dots_and_dashes.web import create_app


@pytest.fixture
def client(settings, clock, logged_in):
    with logged_in(create_app(settings, clock=clock)) as client:
        yield client


def _texts(entries):
    return [entry["text"] for entry in entries]


def test_the_monthly_logs_calendar_comes_from_events_on_its_daily_logs(client):
    for text, day in [
        ("o 9am dentist", "2026-10-03"),
        ("call bank", "2026-10-03"),
        ("o party", "2026-10-31"),
        ("o trip", "2026-11-01"),
    ]:
        client.post("/api/entries", json={"text": text, "day": day})

    monthly_log = client.get("/api/monthly-logs/2026-10").json()

    calendar = {day["date"]: _texts(day["events"]) for day in monthly_log["calendar"]}
    assert len(calendar) == 31
    assert calendar["2026-10-03"] == ["dentist"]
    assert calendar["2026-10-31"] == ["party"]
    assert calendar["2026-10-01"] == []
    assert monthly_log["tasks"] == []


def test_entries_added_to_the_monthly_log_are_on_its_task_list_not_a_day(client):
    added = client.post("/api/monthly-logs/2026-10/entries", json={"text": "*. renew passport"})
    client.post("/api/monthly-logs/2026-10/entries", json={"text": "- spend less"})

    assert added.status_code == 201
    assert added.json()["location"] == "month"
    assert added.json()["day"] is None
    monthly_log = client.get("/api/monthly-logs/2026-10").json()
    assert _texts(monthly_log["tasks"]) == ["renew passport", "spend less"]
    assert client.get("/api/daily-logs/today").json()["entries"] == []
    assert client.get("/api/monthly-logs/2026-09").json()["tasks"] == []


def test_an_event_without_a_date_cannot_go_on_the_monthly_log(client):
    refused = client.post("/api/monthly-logs/2026-10/entries", json={"text": "o conference"})

    assert refused.status_code == 422
    assert client.get("/api/monthly-logs/2026-10").json()["tasks"] == []


def test_past_months_have_a_monthly_log_but_later_months_do_not(client):
    assert client.get("/api/monthly-logs/2025-02").status_code == 200
    assert client.get("/months/2025-02").status_code == 200
    assert client.get("/api/monthly-logs/2026-11").status_code == 404
    assert client.get("/months/2026-11").status_code == 404
    refused = client.post("/api/monthly-logs/2026-11/entries", json={"text": "plan"})
    assert refused.status_code == 422


def test_the_monthly_log_page_opens_on_the_current_month(client):
    opened = client.get("/months", follow_redirects=False)

    assert opened.status_code == 303
    assert opened.headers["location"] == "/months/2026-10"


def test_the_monthly_log_page_shows_the_calendar_and_task_list(client):
    client.post("/api/entries", json={"text": "o party", "day": "2026-10-31"})
    submitted = client.post("/months/2026-10/entries", data={"text": "renew passport"})

    assert submitted.status_code == 200  # after the redirect back to the page
    assert "October 2026" in submitted.text
    assert "party" in submitted.text
    assert "renew passport" in submitted.text
    assert 'href="/days/2026-10-31"' in submitted.text
    assert 'href="/months/2026-09"' in submitted.text
    assert 'href="/months/2026-11"' not in submitted.text


def test_entries_added_to_the_future_log_are_grouped_by_month(client):
    wedding = client.post(
        "/api/future-log/entries",
        json={"text": "o wedding", "month": "2027-03", "date": "2027-03-03"},
    )
    client.post("/api/future-log/entries", json={"text": "file taxes", "month": "2026-11"})
    client.post("/api/future-log/entries", json={"text": "o reunion", "month": "2027-06"})

    assert wedding.status_code == 201
    assert wedding.json()["day"] == "2027-03-03"
    future_log = client.get("/api/future-log").json()
    buckets = {bucket["month"]: _texts(bucket["entries"]) for bucket in future_log["months"]}
    assert buckets == {
        "2026-11": ["file taxes"],
        "2026-12": [],
        "2027-01": [],
        "2027-02": [],
        "2027-03": ["wedding"],
        "2027-04": [],
        "2027-06": ["reunion"],
    }
    # A dated Future Log Entry is not on that day's Daily Log yet.
    assert client.get("/api/daily-logs/2027-03-03").json()["entries"] == []


@pytest.mark.parametrize(
    "body",
    [
        {"text": "file taxes", "month": "2026-10"},
        {"text": "file taxes", "month": "2027-03", "date": "2027-04-01"},
    ],
)
def test_the_future_log_refuses_the_current_month_and_dates_outside_the_month(client, body):
    assert client.post("/api/future-log/entries", json=body).status_code == 422


def test_the_future_log_page_adds_entries_with_an_optional_date(client):
    submitted = client.post(
        "/future/entries",
        data={"text": "o wedding", "month": "2027-03", "date": "2027-03-03"},
    )
    client.post("/future/entries", data={"text": "file taxes", "month": "2026-11", "date": ""})

    assert submitted.status_code == 200
    page = client.get("/future").text
    assert "March 2027" in page
    assert "November 2026" in page
    assert "wedding" in page
    assert "file taxes" in page


@pytest.mark.parametrize(
    ("month", "on", "reason"),
    [
        pytest.param("2026-13", "", "'2026-13' is not a month", id="month"),
        pytest.param("2027-02", "2027-02-30", "'2027-02-30' is not a date", id="date"),
    ],
)
def test_the_future_log_page_refuses_an_impossible_month_or_date(client, month, on, reason):
    refused = client.post(
        "/future/entries", data={"text": "o big conference", "month": month, "date": on}
    )

    assert refused.status_code == 422
    assert refused.headers["content-type"].startswith("text/html")
    assert f'<p role="alert">{reason.replace("\'", "&#39;")}</p>' in refused.text
    assert 'value="o big conference"' in refused.text
    assert f'value="{month}"' in refused.text
    assert f'value="{on}"' in refused.text
    assert all(not bucket["entries"] for bucket in client.get("/api/future-log").json()["months"])


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"text": "o big conference", "month": "2026-13"}, id="month"),
        pytest.param(
            {"text": "o big conference", "month": "2027-02", "date": "2027-02-30"}, id="date"
        ),
    ],
)
def test_the_api_refuses_an_impossible_future_log_month_or_date(client, body):
    refused = client.post("/api/future-log/entries", json=body)

    assert refused.status_code == 422
    assert "detail" in refused.json()
    assert all(not bucket["entries"] for bucket in client.get("/api/future-log").json()["months"])


def test_completing_and_editing_a_monthly_log_task_keeps_it_on_the_task_list(client):
    task = client.post("/api/monthly-logs/2026-10/entries", json={"text": "renew passport"}).json()

    completed = client.post(f"/api/entries/{task['id']}/complete")
    edited = client.patch(f"/api/entries/{task['id']}", json={"text": "* renew passports"})

    assert completed.status_code == 200
    assert edited.status_code == 200
    [stored] = client.get("/api/monthly-logs/2026-10").json()["tasks"]
    assert (stored["text"], stored["state"], stored["priority"]) == (
        "renew passports",
        "completed",
        True,
    )
    assert (stored["location"], stored["month"], stored["day"]) == ("month", "2026-10-01", None)
    assert client.get("/api/daily-logs/today").json()["entries"] == []


def test_a_monthly_log_task_cannot_be_edited_into_an_event(client):
    task = client.post("/api/monthly-logs/2026-10/entries", json={"text": "conference"}).json()

    refused = client.patch(f"/api/entries/{task['id']}", json={"text": "o conference"})

    assert refused.status_code == 422
    [stored] = client.get("/api/monthly-logs/2026-10").json()["tasks"]
    assert stored["type"] == "task"


def test_editing_a_future_log_entry_into_an_event_keeps_its_month_and_date(client):
    entry = client.post(
        "/api/future-log/entries",
        json={"text": "wedding", "month": "2027-03", "date": "2027-03-14"},
    ).json()

    edited = client.patch(f"/api/entries/{entry['id']}", json={"text": "o wedding"})

    assert edited.status_code == 200
    assert (edited.json()["type"], edited.json()["state"]) == ("event", None)
    months = client.get("/api/future-log").json()["months"]
    march = next(m for m in months if m["month"] == "2027-03")
    [stored] = march["entries"]
    assert (stored["location"], stored["month"], stored["day"]) == (
        "future",
        "2027-03-01",
        "2027-03-14",
    )


def test_a_note_off_the_daily_log_cannot_be_nested(client):
    client.post("/api/monthly-logs/2026-10/entries", json={"text": "renew passport"})
    note = client.post("/api/monthly-logs/2026-10/entries", json={"text": "- bring photos"}).json()

    assert client.post(f"/api/entries/{note['id']}/nest").status_code == 422
    assert client.post(f"/entries/{note['id']}/nest").status_code == 422


def test_an_entry_off_the_daily_log_cannot_be_reordered(client):
    client.post("/api/monthly-logs/2026-10/entries", json={"text": "renew passport"})
    task = client.post("/api/monthly-logs/2026-10/entries", json={"text": "file taxes"}).json()

    assert client.post(f"/api/entries/{task['id']}/move", json={"to": 0}).status_code == 422
    assert client.post(f"/entries/{task['id']}/move", data={"to": 0}).status_code == 422


def test_monthly_log_tasks_are_not_draggable(client):
    client.post("/api/monthly-logs/2026-10/entries", json={"text": "renew passport"})

    page = client.get("/months/2026-10").text

    assert "renew passport" in page
    assert 'draggable="true"' not in page
