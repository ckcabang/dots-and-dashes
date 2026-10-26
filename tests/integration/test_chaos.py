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
