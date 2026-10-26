"""Telemetry: traces, metrics and logs, exported over OTLP to Grafana Cloud.

Every signal recorded during a request carries that request's trace ID: logs
through the active span, metrics through exemplars.

Journal text never enters a signal. Spans, metrics and logs record an
Entry's type, length and ID, and an error's type, never its message: a
database error's message can quote the row it refused.
"""

import time
from collections.abc import Collection
from typing import Any

from opentelemetry import trace
from opentelemetry._logs import SeverityNumber
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, LogRecordExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import Span, SpanKind, Status, StatusCode, use_span
from opentelemetry.util.re import parse_env_headers
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.pool import PoolProxiedConnection, QueuePool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from dots_and_dashes import journal
from dots_and_dashes.settings import Settings

SCOPE = "dots_and_dashes"
# Seconds; dense around the 1s p95 save latency alert.
SAVE_DURATION_BUCKETS = [0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 1, 1.5, 2.5, 5, 10]


def resource_for(settings: Settings) -> Resource:
    """What every signal says about where it came from.

    The namespace is the environment, so Grafana Cloud's job label reads
    prod/dots-and-dashes or dev/dots-and-dashes: alerts select prod by job.
    """
    return Resource.create(
        {
            "service.name": settings.service_name,
            "service.namespace": settings.environment,
            "service.version": settings.release,
            "deployment.environment.name": settings.environment,
        }
    )


class Telemetry:
    """The app's tracer, meter and logger, and the exporters they feed.

    With no exporters, signals are recorded and dropped: the app runs the
    same with telemetry unconfigured.
    """

    def __init__(
        self,
        *,
        span_exporter: SpanExporter | None = None,
        metric_reader: MetricReader | None = None,
        log_exporter: LogRecordExporter | None = None,
        resource: Resource | None = None,
    ) -> None:
        resource = resource or Resource.create({"service.name": "dots-and-dashes"})
        self.tracer_provider = TracerProvider(resource=resource)
        if span_exporter is not None:
            self.tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
        self.meter_provider = MeterProvider(
            resource=resource, metric_readers=[metric_reader] if metric_reader is not None else []
        )
        self.logger_provider = LoggerProvider(resource=resource)
        if log_exporter is not None:
            self.logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))

        self.tracer = self.tracer_provider.get_tracer(SCOPE)
        self.logger = self.logger_provider.get_logger(SCOPE)
        meter = self.meter_provider.get_meter(SCOPE)
        # The key journey's save metrics, which the save failure and save
        # latency alerts are written against (docs/runbooks/README.md).
        self.entry_saves = meter.create_counter(
            "entry.saves",
            description="Entry saves on the key journey, by outcome: saved, refused or failed",
        )
        self.entry_save_duration = meter.create_histogram(
            "entry.save.duration",
            unit="s",
            description="How long an Entry save request took, by outcome",
            explicit_bucket_boundaries_advisory=SAVE_DURATION_BUCKETS,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "Telemetry":
        """Export to the OTLP endpoint the settings name, or nowhere without one."""
        resource = resource_for(settings)
        if not settings.otlp_endpoint:
            return cls(resource=resource)
        endpoint = settings.otlp_endpoint.rstrip("/")
        headers = dict(parse_env_headers(settings.otlp_headers, liberal=True))
        return cls(
            span_exporter=OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces", headers=headers),
            metric_reader=PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics", headers=headers)
            ),
            log_exporter=OTLPLogExporter(endpoint=f"{endpoint}/v1/logs", headers=headers),
            resource=resource,
        )

    def force_flush(self) -> None:
        self.tracer_provider.force_flush()
        self.logger_provider.force_flush()

    def log(self, severity: SeverityNumber, body: str, attributes: dict[str, Any]) -> None:
        """A structured log on the current span's trace."""
        self.logger.emit(
            severity_number=severity,
            severity_text=severity.name,
            body=body,
            attributes=attributes,
        )

    def entry_saved(self, entry: journal.Entry) -> None:
        """Record the saved Entry on the request's span and log it: its ID,
        type and text length, never its text."""
        attributes = {
            "entry.id": entry.id,
            "entry.type": entry.type.value,
            "entry.text_length": len(entry.text),
        }
        trace.get_current_span().set_attributes(attributes)
        self.log(SeverityNumber.INFO, "Entry saved", attributes)

    def create_engine(self, url: str, **kwargs: Any) -> Engine:
        """A SQLAlchemy engine that traces each wait for a pooled connection
        and each database statement, as children of the request's span."""
        engine = create_engine(url, poolclass=_traced_pool(self.tracer), **kwargs)
        tracer = self.tracer

        @event.listens_for(engine, "before_cursor_execute")
        def start(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
            span = tracer.start_span(
                statement.split(maxsplit=1)[0] if statement else "SQL",
                kind=SpanKind.CLIENT,
                # The statement holds placeholders; the values are sent apart.
                attributes={"db.system.name": "postgresql", "db.query.text": statement},
            )
            conn.info.setdefault(_SPANS, []).append(span)

        @event.listens_for(engine, "after_cursor_execute")
        def end(conn: Any, *args: Any) -> None:
            if spans := conn.info.get(_SPANS):
                spans.pop().end()

        @event.listens_for(engine, "handle_error")
        def fail(context: Any) -> None:
            spans = context.connection.info.get(_SPANS) if context.connection else None
            if spans:
                span = spans.pop()
                _record_error(span, context.original_exception)
                span.end()

        return engine


def _traced_pool(tracer: trace.Tracer) -> type[QueuePool]:
    """A connection pool that traces each checkout: the wait for a free
    connection, which is how an exhausted pool shows in a trace."""

    class TracedQueuePool(QueuePool):
        def __init__(
            self, creator: Any, pool_size: int = 5, max_overflow: int = 10, **kwargs: Any
        ) -> None:
            super().__init__(creator, pool_size=pool_size, max_overflow=max_overflow, **kwargs)
            self.max_connections = pool_size + max_overflow

        def connect(self) -> PoolProxiedConnection:
            span = tracer.start_span(
                "db.connection.checkout",
                kind=SpanKind.CLIENT,
                attributes={
                    "db.system.name": "postgresql",
                    # The most connections the app may hold, and how many it
                    # held when this checkout began: equal means a wait.
                    "db.client.connection.max": self.max_connections,
                    "db.client.connection.used": self.checkedout(),
                },
            )
            with use_span(
                span, end_on_exit=True, record_exception=False, set_status_on_exception=False
            ):
                try:
                    return super().connect()
                except Exception as exc:
                    _record_error(span, exc)
                    raise

    return TracedQueuePool


# Where a connection keeps the spans of its statements in flight.
_SPANS = "dots_and_dashes.telemetry.spans"


def _error_type(exc: BaseException) -> str:
    return f"{type(exc).__module__}.{type(exc).__qualname__}"


def _record_error(span: Span, exc: BaseException) -> None:
    """Mark a span failed with the error's type only: its message may quote journal text."""
    span.set_attribute("error.type", _error_type(exc))
    span.set_status(Status(StatusCode.ERROR))


class RequestTelemetry:
    """ASGI middleware: a server span per HTTP request, and the save metrics
    for the requests that save an Entry on the key journey."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        telemetry: Telemetry,
        entry_saves: Collection[tuple[str, str]] = (),
    ) -> None:
        self.app = app
        self.telemetry = telemetry
        # The (method, route) pairs that save an Entry on the key journey.
        self.entry_saves = entry_saves

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        span = self.telemetry.tracer.start_span(
            method, kind=SpanKind.SERVER, attributes={"http.request.method": method}
        )
        status = 500
        error: Exception | None = None
        started = time.perf_counter()

        async def send_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        with use_span(
            span, end_on_exit=True, record_exception=False, set_status_on_exception=False
        ):
            try:
                await self.app(scope, receive, send_status)
            except Exception as exc:
                status, error = 500, exc
                _record_error(span, exc)
                raise
            finally:
                route = getattr(scope.get("route"), "path", None)
                if route:
                    span.update_name(f"{method} {route}")
                    span.set_attribute("http.route", route)
                span.set_attribute("http.response.status_code", status)
                if status >= 500:
                    span.set_status(Status(StatusCode.ERROR))
                if (method, route) in self.entry_saves:
                    self._entry_save(status, time.perf_counter() - started, error)

    def _entry_save(self, status: int, seconds: float, error: Exception | None) -> None:
        outcome = "failed" if status >= 500 else "refused" if status >= 400 else "saved"
        self.telemetry.entry_saves.add(1, {"outcome": outcome})
        self.telemetry.entry_save_duration.record(seconds, {"outcome": outcome})
        if outcome == "failed":
            self.telemetry.log(
                SeverityNumber.ERROR,
                "Entry save failed",
                {"http.response.status_code": status}
                | ({"error.type": _error_type(error)} if error else {}),
            )
