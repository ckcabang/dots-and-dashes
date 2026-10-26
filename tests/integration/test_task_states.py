from contextlib import contextmanager

import pytest

from dots_and_dashes.web import create_app


@pytest.fixture
def client(settings, clock, logged_in):
    with logged_in(create_app(settings, clock=clock)) as client:
        yield client


@pytest.fixture
def app_client(settings, clock, logged_in):
    """A fresh app instance, so what it shows can only have come from Postgres."""

    @contextmanager
    def start():
        with logged_in(create_app(settings, clock=clock)) as client:
            yield client

    return start


def _todays_entries(client):
    return [
        (entry["id"], entry["state"], entry["text"])
        for entry in client.get("/api/daily-logs/today").json()["entries"]
    ]


def _log(client, text="buy milk"):
    return client.post("/api/entries", json={"text": text}).json()["id"]


def test_a_completed_task_shows_completed_on_the_daily_log(client, app_client):
    task = _log(client)

    completed = client.post(f"/api/entries/{task}/complete")

    assert completed.status_code == 200
    assert completed.json()["state"] == "completed"
    with app_client() as fresh:
        assert _todays_entries(fresh) == [(task, "completed", "buy milk")]


def test_a_cancelled_task_can_be_reopened(client):
    task = _log(client)

    client.post(f"/api/entries/{task}/cancel")
    assert _todays_entries(client) == [(task, "cancelled", "buy milk")]

    reopened = client.post(f"/api/entries/{task}/reopen")

    assert reopened.status_code == 200
    assert _todays_entries(client) == [(task, "open", "buy milk")]


def test_a_task_state_change_that_is_not_allowed_is_refused(client):
    task = _log(client)

    refused = client.post(f"/api/entries/{task}/reopen")

    assert refused.status_code == 409
    assert _todays_entries(client) == [(task, "open", "buy milk")]


def test_an_edited_entry_keeps_its_place_and_task_state(client, app_client):
    task = _log(client)
    client.post(f"/api/entries/{task}/complete")

    edited = client.patch(f"/api/entries/{task}", json={"text": "buy oat milk"})

    assert edited.status_code == 200
    with app_client() as fresh:
        assert _todays_entries(fresh) == [(task, "completed", "buy oat milk")]


def test_an_entry_cannot_be_edited_to_blank(client):
    task = _log(client)

    refused = client.patch(f"/api/entries/{task}", json={"text": " "})

    assert refused.status_code == 422
    assert _todays_entries(client) == [(task, "open", "buy milk")]


def test_delete_removes_an_entry_for_good(client, app_client):
    kept = _log(client, "buy milk")
    deleted = _log(client, "logged by mistake")

    response = client.delete(f"/api/entries/{deleted}")

    assert response.status_code == 204
    with app_client() as fresh:
        assert _todays_entries(fresh) == [(kept, "open", "buy milk")]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/entries/999/complete"),
        ("post", "/api/entries/999/cancel"),
        ("post", "/api/entries/999/reopen"),
        ("delete", "/api/entries/999"),
        ("post", "/entries/999/complete"),
        ("delete", "/entries/999"),
    ],
)
def test_acting_on_an_entry_that_does_not_exist_is_not_found(client, method, path):
    assert client.request(method, path).status_code == 404


@pytest.mark.parametrize("path", ["/api/entries/{id}/finish", "/entries/{id}/finish"])
def test_a_task_state_change_that_does_not_exist_is_refused_not_an_entry_not_found(client, path):
    task = _log(client)

    refused = client.post(path.format(id=task))

    assert refused.status_code == 422
    assert _todays_entries(client) == [(task, "open", "buy milk")]


def test_editing_an_entry_that_does_not_exist_is_not_found(client):
    assert client.patch("/api/entries/999", json={"text": "x"}).status_code == 404


def test_the_daily_log_page_acts_on_an_entry_and_returns_it_redrawn(client):
    task = _log(client)
    htmx = {"HX-Request": "true"}

    completed = client.post(f"/entries/{task}/complete", headers=htmx)
    edited = client.post(f"/entries/{task}", data={"text": "buy oat milk"}, headers=htmx)
    deleted = client.delete(f"/entries/{task}", headers=htmx)

    assert completed.status_code == 200
    assert completed.text.lstrip().startswith("<li")
    assert 'data-state="completed"' in completed.text
    assert "buy oat milk" in edited.text
    assert deleted.status_code == 200
    assert deleted.text == ""
    assert _todays_entries(client) == []
