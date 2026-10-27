"""The chaos switch: staging an incident on purpose, and seeing it in telemetry.

Injected save failures and latency must look, in the save metrics and
traces, like the real incidents the alerts and runbooks are written for.
"""

from concurrent.futures import ThreadPoolExecutor
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


@pytest.mark.failed_requests
def test_an_injected_failure_fails_the_save_and_is_counted_as_failed(settings, start, signals):
    with start(replace(settings, chaos_save_error_rate=1.0)) as client:
        response = client.post("/api/entries", json={"text": "buy milk"})

        assert response.status_code == 500
        assert client.get("/api/daily-logs/today").json()["entries"] == []
    (saves,) = signals.points()["entry.saves"]
    assert (saves.attributes["outcome"], saves.value) == ("failed", 1)
    # The runbook names this type, so a staged failure is told from a real one.
    error_type = "dots_and_dashes.chaos.InjectedSaveFailure"
    request = signals.server_span("POST", "/api/entries")
    assert request.attributes and request.attributes["error.type"] == error_type
    (failed,) = [r for r in signals.logs() if r.log_record.body == "Entry save failed"]
    assert failed.log_record.attributes and failed.log_record.attributes["error.type"] == error_type


@pytest.mark.failed_requests
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
    assert duration.attributes["outcome"] == "saved"
    assert duration.sum >= 0.3


def seconds(span) -> float:
    return (span.end_time - span.start_time) / 1e9


def test_the_pool_size_is_read_from_the_environment_and_a_save_traces_its_checkout(
    settings, clock, logged_in, signals, monkeypatch
):
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("DB_POOL_SIZE", "3")
    app = create_app(clock=clock, telemetry=signals.telemetry)

    with logged_in(app) as client:
        client.post("/api/entries", json={"text": "buy milk"})

    request = signals.server_span("POST", "/api/entries")
    (checkout, *_) = [
        span
        for span in signals.spans()
        if span.name == "db.connection.checkout"
        and span.parent is not None
        and span.parent.span_id == request.context.span_id
    ]
    assert checkout.context.trace_id == request.context.trace_id
    assert checkout.attributes and checkout.attributes["db.client.connection.max"] == 3


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("CHAOS_SAVE_ERROR_RATE", "abc"),
        ("CHAOS_SAVE_ERROR_RATE", "1.5"),
        ("CHAOS_SAVE_LATENCY_MS", "x"),
        ("CHAOS_SAVE_LATENCY_MS", "-1"),
        ("DB_POOL_SIZE", "x"),
        ("DB_POOL_SIZE", "0"),
    ],
)
def test_a_bad_switch_value_stops_the_app_starting_and_names_the_switch(
    settings, monkeypatch, name, value
):
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        create_app()


def test_an_exhausted_pool_shows_as_a_long_connection_checkout(settings, start, signals):
    # One connection, held for 300ms by each slow save: the second save waits.
    with start(replace(settings, db_pool_size=1, chaos_save_latency_ms=300)) as client:
        with ThreadPoolExecutor(2) as pool:
            responses = list(
                pool.map(
                    lambda n: client.post("/api/entries", json={"text": f"entry {n}"}),
                    range(2),
                )
            )

    assert [response.status_code for response in responses] == [201, 201]
    waits = [span for span in signals.spans() if span.name == "db.connection.checkout"]
    longest = max(waits, key=seconds)
    assert seconds(longest) >= 0.2
    # It began with every connection in use.
    assert longest.attributes and dict(longest.attributes) == {
        "db.system.name": "postgresql",
        "db.client.connection.max": 1,
        "db.client.connection.used": 1,
    }
