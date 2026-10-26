"""Fixtures shared by the integration and browser suites.

Both run against a real Postgres. Point TEST_DATABASE_URL at one, or let
`make test` start the Compose `db` service, which the default URL targets.
The test database is created if missing and rebuilt with Alembic once per run.
"""

import os
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, make_url, text

from dots_and_dashes.settings import Settings

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://dots:dots@localhost:5432/dots_and_dashes_test",
)

# 03:00 UTC on 26 Oct is still 25 Oct in Los Angeles, so tests that see
# 2026-10-25 as "today" prove the User's timezone is applied.
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


ALEMBIC_INI = Path(__file__).parents[1] / "alembic.ini"


@pytest.fixture(scope="session")
def database_url() -> str:
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
        conn.execute(text("TRUNCATE entries RESTART IDENTITY"))
    engine.dispose()
    return Settings(database_url=database_url, timezone=TIMEZONE)


@pytest.fixture
def clock():
    return lambda: NOW
