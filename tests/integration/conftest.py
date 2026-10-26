"""Fixtures for the integration suite.

They run against a real Postgres named by TEST_DATABASE_URL, which
`make test` sets to its test Compose stack. The test database is created if
missing and rebuilt with Alembic once per run.
"""

import logging
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, text

from dots_and_dashes import cli, telemetry
from dots_and_dashes.settings import Settings

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "failed_requests: the test expects the app to fail a request with a 500"
    )


class _FailedRequests(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


@pytest.fixture(autouse=True)
def no_failed_requests(request: pytest.FixtureRequest):
    """Fail a test during which the app answered an unhandled error with a 500.

    The app answers it itself, so the server never logs its traceback; a test
    whose setup calls don't check their status would otherwise pass on one.
    """
    failed = _FailedRequests()
    logger = logging.getLogger(telemetry.__name__)
    logger.addHandler(failed)
    yield
    logger.removeHandler(failed)
    if failed.lines and not request.node.get_closest_marker("failed_requests"):
        pytest.fail("The app failed a request:\n" + "\n".join(failed.lines))

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
def password() -> str:
    """Every User's password, for logging in without the `logged_in` fixture."""
    return PASSWORD


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
