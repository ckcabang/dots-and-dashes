"""The chaos switch: staging an incident on purpose, and seeing it in telemetry.

Injected save failures and latency must look, in the save metrics and
traces, like the real incidents the alerts and runbooks are written for.
"""

from dataclasses import replace

import pytest

from dots_and_dashes.web import create_app


@pytest.fixture
def start(clock, logged_in, signals):
    """Start a client on the app with these settings, exporting to `signals`."""

    def start_with(settings):
        app = create_app(settings, clock=clock, telemetry=signals.telemetry)
        return logged_in(app, raise_server_exceptions=False)

    return start_with


def test_an_injected_failure_fails_the_save_and_is_counted_as_failed(settings, start, signals):
    with start(replace(settings, chaos_save_error_rate=1.0)) as client:
        response = client.post("/api/entries", json={"text": "buy milk"})

        assert response.status_code == 500
        assert client.get("/api/daily-logs/today").json()["entries"] == []
    (saves,) = signals.points()["entry.saves"]
    assert (dict(saves.attributes), saves.value) == ({"outcome": "failed"}, 1)


def test_the_error_rate_is_read_from_the_environment_and_fails_that_share_of_saves(
    settings, clock, logged_in, signals, monkeypatch
):
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("CHAOS_SAVE_ERROR_RATE", "0.25")
    app = create_app(clock=clock, telemetry=signals.telemetry)

    with logged_in(app, raise_server_exceptions=False) as client:
        statuses = [
            client.post("/api/entries", json={"text": f"entry {n}"}).status_code
            for n in range(4)
        ] + [
            client.post(
                "/entries", data={"text": f"entry {n}"}, headers={"HX-Request": "true"}
            ).status_code
            for n in range(4)
        ]

    # Every fourth save fails, from the page and the API alike.
    assert statuses == [201, 201, 201, 500, 201, 201, 201, 500]
    counted = {
        point.attributes["outcome"]: point.value for point in signals.points()["entry.saves"]
    }
    assert counted == {"saved": 6, "failed": 2}


def test_injected_latency_slows_the_save_and_shows_in_its_duration(settings, start, signals):
    with start(replace(settings, chaos_save_latency_ms=300)) as client:
        response = client.post("/api/entries", json={"text": "buy milk"})

    assert response.status_code == 201
    (duration,) = signals.points()["entry.save.duration"]
    assert dict(duration.attributes) == {"outcome": "saved"}
    assert duration.sum >= 0.3
