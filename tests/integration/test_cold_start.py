"""A cold start of Postgres: dev's database Machine stops when idle, and for its
first seconds after Fly starts it again, Fly's proxy refuses the connection and
then Postgres answers "the database system is starting up" (#95). The app and
the release command wait it out, for a bounded time, instead of failing."""

import time
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from dots_and_dashes import cli, persistence
from dots_and_dashes.web import create_app

STARTING_UP = 'connection failed: FATAL:  the database system is starting up'
ALEMBIC_INI = Path(__file__).parents[2] / "alembic.ini"
REFUSED = (
    'connection failed: connection to server at "10.0.0.1", port 5432 failed: '
    "Connection refused"
)


@pytest.fixture
def cold_postgres(monkeypatch):
    """Make the next connections fail as a waking Postgres does, then connect.

    Set `failures` to the errors the next connections fail with, in order.
    """

    class ColdPostgres:
        failures: list[str] = []
        attempts = 0

    real_connect = psycopg.connect

    def connect(*args, **kwargs):
        ColdPostgres.attempts += 1
        if ColdPostgres.failures:
            raise psycopg.OperationalError(ColdPostgres.failures.pop(0))
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(psycopg, "connect", connect)
    return ColdPostgres


def test_logging_in_waits_out_a_cold_start_of_postgres(settings, user, password, cold_postgres):
    cold_postgres.failures = [REFUSED, STARTING_UP]

    with TestClient(create_app(settings), follow_redirects=False) as client:
        response = client.post("/login", data={"email": user, "password": password})

    assert response.status_code == 303
    assert cold_postgres.attempts == 3


def test_the_release_command_waits_out_a_cold_start_of_postgres(
    database_url, monkeypatch, cold_postgres
):
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.chdir(ALEMBIC_INI.parent)
    cold_postgres.failures = [REFUSED, STARTING_UP]

    cli.main(["migrate"])

    assert cold_postgres.attempts > 2
    assert not cold_postgres.failures


@pytest.mark.failed_requests
def test_a_cold_start_longer_than_the_bound_fails_the_request(
    settings, user, password, cold_postgres, monkeypatch
):
    monkeypatch.setattr(persistence, "COLD_START_SECONDS", 1.0)
    cold_postgres.failures = [STARTING_UP] * 100

    started = time.monotonic()
    with TestClient(create_app(settings), follow_redirects=False) as client:
        response = client.post("/login", data={"email": user, "password": password})

    assert response.status_code == 500
    assert 1 < cold_postgres.attempts < 100
    assert time.monotonic() - started < 3


@pytest.mark.failed_requests
def test_a_connection_refused_for_another_reason_fails_at_once(
    settings, user, password, cold_postgres
):
    cold_postgres.failures = [
        'connection failed: FATAL:  password authentication failed for user "dots"'
    ]

    with TestClient(create_app(settings), follow_redirects=False) as client:
        response = client.post("/login", data={"email": user, "password": password})

    assert response.status_code == 500
    assert cold_postgres.attempts == 1
