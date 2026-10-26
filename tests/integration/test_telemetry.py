"""Telemetry on the key journey: logging an Entry on today's Daily Log.

The app exports to in-memory exporters here, in place of Grafana Cloud, so a
test can read every span, metric and log the journey produced.
"""

from dataclasses import dataclass

import pytest
from opentelemetry.sdk._logs import ReadableLogRecord
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import create_engine, text

from dots_and_dashes.telemetry import Telemetry
from dots_and_dashes.web import create_app


@dataclass
class Signals:
    """Everything the app exported, read back after a flush."""

    telemetry: Telemetry
    span_exporter: InMemorySpanExporter
    metric_reader: InMemoryMetricReader
    log_exporter: InMemoryLogRecordExporter

    def spans(self) -> list[ReadableSpan]:
        self.telemetry.force_flush()
        return list(self.span_exporter.get_finished_spans())

    def server_span(self, method: str, route: str) -> ReadableSpan:
        (span,) = [
            s
            for s in self.spans()
            if s.attributes
            and s.attributes.get("http.request.method") == method
            and s.attributes.get("http.route") == route
        ]
        return span

    def logs(self) -> list[ReadableLogRecord]:
        self.telemetry.force_flush()
        return list(self.log_exporter.get_finished_logs())

    def points(self) -> dict[str, list]:
        """Each metric's data points, by metric name. Exemplars come with
        the first collection after a measurement only, so collect once."""
        data = self.metric_reader.get_metrics_data()
        assert data is not None
        return {
            metric.name: list(metric.data.data_points)
            for resource in data.resource_metrics
            for scope in resource.scope_metrics
            for metric in scope.metrics
        }

    def as_text(self) -> str:
        """Every signal, serialized the way an exporter would see it."""
        data = self.metric_reader.get_metrics_data()
        return "\n".join(
            [span.to_json() for span in self.spans()]
            + [record.to_json() for record in self.logs()]
            + [data.to_json() if data else ""]
        )


@pytest.fixture
def signals() -> Signals:
    span_exporter = InMemorySpanExporter()
    metric_reader = InMemoryMetricReader()
    log_exporter = InMemoryLogRecordExporter()
    telemetry = Telemetry(
        span_exporter=span_exporter, metric_reader=metric_reader, log_exporter=log_exporter
    )
    return Signals(telemetry, span_exporter, metric_reader, log_exporter)


@pytest.fixture
def client(settings, clock, logged_in, signals):
    with logged_in(
        create_app(settings, clock=clock, telemetry=signals.telemetry),
        raise_server_exceptions=False,
    ) as client:
        yield client


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
