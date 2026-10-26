"""Fixtures for the integration suite.

They run against a real Postgres named by TEST_DATABASE_URL, which
`make test` sets to its test Compose stack. The test database is created if
missing and rebuilt with Alembic once per run.
"""

import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk._logs import ReadableLogRecord
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import create_engine, make_url, text

from dots_and_dashes import cli
from dots_and_dashes.settings import Settings
from dots_and_dashes.telemetry import Telemetry, resource_for

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")

# 03:00 UTC on 26 Oct is still 25 Oct in the User's Los Angeles, so tests
# that see 2026-10-25 as "today" prove the User's timezone is applied.
NOW = datetime(2026, 10, 26, 3, 0, tzinfo=UTC)
TIMEZONE = ZoneInfo("America/Los_Angeles")


def _create_database_if_missing(url: str) -> None:
    target = make_url(url)
    admin = create_engine(
        target.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": target.database},
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    admin.dispose()


ALEMBIC_INI = Path(__file__).parents[2] / "alembic.ini"


@pytest.fixture(scope="session")
def database_url() -> str:
    if not TEST_DATABASE_URL:
        pytest.exit("Set TEST_DATABASE_URL, or run the tests with `make test`")
    # The schema is dropped below, so never run against a non-test database.
    database = make_url(TEST_DATABASE_URL).database or ""
    if not database.endswith("_test"):
        pytest.exit(f"TEST_DATABASE_URL must name a *_test database, not {database!r}")
    _create_database_if_missing(TEST_DATABASE_URL)
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()

    config = Config(ALEMBIC_INI)
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(config, "head")
    return TEST_DATABASE_URL


@pytest.fixture
def settings(database_url: str) -> Settings:
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE entries, captures, users RESTART IDENTITY"))
    engine.dispose()
    return Settings(database_url=database_url)


PASSWORD = "correct horse battery staple"
EMAIL = "me@example.com"


@pytest.fixture
def create_user(settings, monkeypatch):
    """Create a User the way the operator does: with the CLI, the password from a secret."""

    def create(email: str, *, timezone: str = TIMEZONE.key, canary: bool = False) -> str:
        monkeypatch.setenv("DATABASE_URL", settings.database_url)
        monkeypatch.setenv("USER_PASSWORD", PASSWORD)
        cli.main(
            ["create-user", "--email", email, "--timezone", timezone]
            + (["--canary"] if canary else [])
        )
        return email

    return create


@pytest.fixture
def user(create_user) -> str:
    """The User, in Los Angeles: their email."""
    return create_user(EMAIL)


@pytest.fixture
def logged_in(user):
    """Start a client on an app, logged in as the User or another User's email."""

    @contextmanager
    def start(app: FastAPI, email: str = user, **client_args):
        with TestClient(app, **client_args) as client:
            response = client.post("/login", data={"email": email, "password": PASSWORD})
            assert response.status_code in (200, 303), response.text
            yield client

    return start


@pytest.fixture
def clock():
    return lambda: NOW


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
def signals(settings) -> Signals:
    span_exporter = InMemorySpanExporter()
    metric_reader = InMemoryMetricReader()
    log_exporter = InMemoryLogRecordExporter()
    telemetry = Telemetry(
        span_exporter=span_exporter,
        metric_reader=metric_reader,
        log_exporter=log_exporter,
        resource=resource_for(settings),
    )
    return Signals(telemetry, span_exporter, metric_reader, log_exporter)
