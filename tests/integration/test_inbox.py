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
