"""Telemetry on the key journey: logging an Entry on today's Daily Log.

The app exports to in-memory exporters here (the `signals` fixture), in
place of Grafana Cloud, so a test can read every span, metric and log the
journey produced.
"""

import copy
import logging
import socket
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace

import httpx2
import pytest
import uvicorn
from sqlalchemy import create_engine, text

from dots_and_dashes.web import create_app

RELEASE = "registry.fly.io/dots-and-dashes:abc123"


@pytest.fixture
def settings(settings):
    """The app as deployed to prod."""
    return replace(settings, environment="prod", release=RELEASE)


@pytest.fixture
def client(settings, clock, logged_in, signals):
    with logged_in(
        create_app(settings, clock=clock, telemetry=signals.telemetry),
        raise_server_exceptions=False,
    ) as client:
        yield client


def test_every_signal_names_its_environment_and_release(client, signals):
    client.post("/api/entries", json={"text": "buy milk"})

    data = signals.metric_reader.get_metrics_data()
    assert data is not None
    resources = (
        [span.resource for span in signals.spans()]
        + [record.resource for record in signals.logs()]
        + [metrics.resource for metrics in data.resource_metrics]
    )
    expected = {
        "service.name": "dots-and-dashes",
        # Grafana Cloud folds the namespace into job, prod/dots-and-dashes,
        # which the prod-only alert queries select on.
        "service.namespace": "prod",
        "deployment.environment.name": "prod",
        "service.version": RELEASE,
    }
    assert len(resources) > 2
    for resource in resources:
        assert {key: resource.attributes.get(key) for key in expected} == expected


def test_saving_an_entry_traces_the_request_and_the_database_write(client, signals):
    response = client.post("/api/entries", json={"text": "buy milk"})

    assert response.status_code == 201
    request = signals.server_span("POST", "/api/entries")
    assert request.name == "POST /api/entries"
    assert request.attributes and request.attributes["http.response.status_code"] == 201
    inserts = [
        span
        for span in signals.spans()
        if span.parent is not None
        and span.parent.span_id == request.context.span_id
        and span.attributes
        and str(span.attributes.get("db.query.text", "")).startswith("INSERT INTO entries")
    ]
    assert len(inserts) == 1
    assert inserts[0].context.trace_id == request.context.trace_id


@pytest.mark.parametrize(
    ("route", "request_args"),
    [
        ("/api/entries", {"json": {"text": "buy milk"}}),
        ("/entries", {"data": {"text": "buy milk"}, "headers": {"HX-Request": "true"}}),
    ],
)
def test_a_saved_entry_is_counted_and_timed_on_the_request_trace(
    client, signals, route, request_args
):
    response = client.post(route, **request_args)

    assert response.status_code == 201
    trace_id = signals.server_span("POST", route).context.trace_id
    points = signals.points()
    (saves,) = points["entry.saves"]
    assert (dict(saves.attributes), saves.value) == ({"outcome": "saved"}, 1)
    (duration,) = points["entry.save.duration"]
    assert dict(duration.attributes) == {"outcome": "saved"}
    assert duration.count == 1
    assert 0 < duration.sum < 1
    assert [exemplar.trace_id for exemplar in duration.exemplars] == [trace_id]


def test_a_saved_entry_is_logged_on_the_request_trace(client, signals):
    entry = client.post("/api/entries", json={"text": "* call the plumber"}).json()

    trace_id = signals.server_span("POST", "/api/entries").context.trace_id
    (saved,) = [record for record in signals.logs() if record.log_record.body == "Entry saved"]
    assert saved.log_record.trace_id == trace_id
    assert saved.log_record.severity_text == "INFO"
    assert dict(saved.log_record.attributes or {}) == {
        "entry.id": entry["id"],
        "entry.type": "task",
        "entry.text_length": len("call the plumber"),
    }


def test_blank_text_is_counted_as_refused_not_failed(client, signals):
    response = client.post("/api/entries", json={"text": "   "})

    assert response.status_code == 422
    (saves,) = signals.points()["entry.saves"]
    assert (dict(saves.attributes), saves.value) == ({"outcome": "refused"}, 1)


@pytest.fixture
def entries_refuse_writes(database_url):
    """Make Postgres refuse every new Entry, the way a broken database would."""
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE entries ADD CONSTRAINT refuse_all CHECK (false) NOT VALID")
        )
    yield
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE entries DROP CONSTRAINT refuse_all"))
    engine.dispose()


@pytest.mark.failed_requests
def test_a_failed_save_is_counted_traced_and_logged(client, signals, entries_refuse_writes):
    response = client.post("/api/entries", json={"text": "buy milk"})

    assert response.status_code == 500
    request = signals.server_span("POST", "/api/entries")
    assert request.status.status_code.name == "ERROR"
    error_type = "sqlalchemy.exc.IntegrityError"
    assert request.attributes and request.attributes["error.type"] == error_type
    (saves,) = signals.points()["entry.saves"]
    assert (dict(saves.attributes), saves.value) == ({"outcome": "failed"}, 1)
    (failed,) = [r for r in signals.logs() if r.log_record.body == "Entry save failed"]
    assert failed.log_record.trace_id == request.context.trace_id
    assert dict(failed.log_record.attributes or {}) == {
        "http.response.status_code": 500,
        "error.type": error_type,
    }


SECRET = "meet Alex at the hidden cafe"


@pytest.mark.failed_requests
def test_entry_text_never_enters_a_signal_even_when_a_save_fails(
    client, signals, entries_refuse_writes
):
    # A refused write: Postgres quotes the failing row, text and all, in its error.
    client.post("/api/entries", json={"text": f"{SECRET} 1"})
    client.post("/entries", data={"text": f"{SECRET} 2"})
    client.post("/api/captures", json={"text": f"{SECRET} 3"})
    capture = client.post("/capture", data={"text": f"{SECRET} 4"})
    assert capture.status_code == 200  # redirected back to the Capture page

    assert len(signals.spans()) > 4
    assert signals.logs()
    assert "Alex" not in signals.as_text()


def test_saved_entry_and_capture_text_never_enters_a_signal(client, signals):
    entry = client.post("/api/entries", json={"text": f"- {SECRET}"}).json()
    client.post("/entries", data={"text": f"o {SECRET}"}, headers={"HX-Request": "true"})
    capture = client.post("/api/captures", json={"text": SECRET}).json()
    client.post(f"/api/captures/{capture['id']}/triage", json={"to": "day"})
    client.get("/")
    client.get("/inbox")

    recorded = signals.as_text()
    assert "Alex" not in recorded
    # Only its type, length and ID.
    assert '"entry.type": "note"' in recorded
    assert f'"entry.text_length": {len(SECRET)}' in recorded
    assert f'"entry.id": {entry["id"]}' in recorded


# A failure's output as Fly sees it: the app served by uvicorn, the way the
# Dockerfile runs it, whose stdout and stderr become the app's logs.


@dataclass
class Served:
    client: httpx2.Client
    server: uvicorn.Server
    thread: threading.Thread
    capture: pytest.CaptureFixture[str]

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join()

    def output(self) -> str:
        """Everything the server wrote to stdout and stderr, once it has
        stopped: uvicorn logs an error's traceback after the response is sent."""
        self.stop()
        out, err = self.capture.readouterr()
        return out + err


class _CurrentStream(logging.StreamHandler):
    """Writes to sys.stdout or sys.stderr as it is when a line is logged, so
    to the streams capfd is capturing, not those of the test that set it up."""

    def __init__(self, to: str) -> None:
        super().__init__()
        self.to = to

    def emit(self, record: logging.LogRecord) -> None:
        self.stream = getattr(sys, self.to)
        super().emit(record)


def _uvicorn_logging() -> dict:
    """Uvicorn's own logging config, its streams looked up as each line is logged."""
    config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    for handler in config["handlers"].values():
        assert handler.pop("class") == "logging.StreamHandler"
        handler["()"] = _CurrentStream
        handler["to"] = handler.pop("stream").removeprefix("ext://sys.")
    return config


@pytest.fixture
def served(settings, clock, user, password, signals, capfd) -> Iterator[Served]:
    app = create_app(settings, clock=clock, telemetry=signals.telemetry)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_config=_uvicorn_logging()))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]})
    thread.start()
    try:
        while not server.started:
            assert thread.is_alive(), "uvicorn failed to start"
            time.sleep(0.01)
        host, port = sock.getsockname()
        with httpx2.Client(base_url=f"http://{host}:{port}") as client:
            response = client.post("/login", data={"email": user, "password": password})
            assert response.status_code == 303, response.text
            yield Served(client, server, thread, capfd)
    finally:
        server.should_exit = True
        thread.join()
        sock.close()


@pytest.fixture
def journal_refuses_writes(database_url):
    """While in use, Postgres refuses every new Entry and Capture."""
    engine = create_engine(database_url)
    tables = ("entries", "captures")

    @contextmanager
    def refusing():
        with engine.begin() as conn:
            for table in tables:
                conn.execute(
                    text(f"ALTER TABLE {table} ADD CONSTRAINT refuse_all CHECK (false) NOT VALID")
                )
        try:
            yield
        finally:
            with engine.begin() as conn:
                for table in tables:
                    conn.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT refuse_all"))

    yield refusing
    engine.dispose()


# Each save that writes journal text, by its route and request.
FAILED_SAVES: dict[str, tuple[str, Callable[[], dict]]] = {
    "entry-api": ("/api/entries", lambda: {"json": {"text": f"{SECRET} 1"}}),
    "entry-page": (
        "/entries",
        lambda: {"data": {"text": f"{SECRET} 2"}, "headers": {"HX-Request": "true"}},
    ),
    "capture-api": ("/api/captures", lambda: {"json": {"text": f"{SECRET} 3"}}),
    "capture-page": ("/capture", lambda: {"data": {"text": f"{SECRET} 4"}}),
    "triage-api": (
        "/api/captures/{capture_id}/triage",
        lambda: {"json": {"to": "day", "text": f"{SECRET} 5"}},
    ),
    "triage-page": ("/inbox/{capture_id}/triage", lambda: {"data": {"to": "day"}}),
}


@pytest.mark.failed_requests
@pytest.mark.parametrize(("route", "request_args"), FAILED_SAVES.values(), ids=FAILED_SAVES)
def test_a_failed_save_logs_its_error_type_and_trace_but_no_journal_text(
    served, signals, journal_refuses_writes, route, request_args
):
    # The Capture a Triage places: its text is in the failing row too.
    capture = served.client.post("/api/captures", json={"text": f"{SECRET} 6"}).json()
    path = route.format(capture_id=capture["id"])

    with journal_refuses_writes():
        response = served.client.post(path, **request_args())

    # The response the User got before: Starlette's own.
    assert (response.status_code, response.text) == (500, "Internal Server Error")
    assert response.headers["content-type"].startswith("text/plain")
    logs = served.output()
    # Postgres quotes the failing row, text and all, in its error.
    assert "Alex" not in logs
    (span,) = [
        s
        for s in signals.spans()
        if s.attributes
        and s.attributes.get("http.route") == route
        and s.attributes.get("http.response.status_code") == 500
    ]
    trace_id = format(span.context.trace_id, "032x")
    (failed,) = [line for line in logs.splitlines() if trace_id in line]
    assert "error.type=sqlalchemy.exc.IntegrityError" in failed
    # Uvicorn's access log, unchanged: method, path and status, never the body.
    assert f'"POST {path} HTTP/1.1" 500' in logs
