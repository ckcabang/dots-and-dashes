"""A cold start of Postgres: dev's database Machine stops when idle, and for its
first seconds after Fly starts it again, Fly's proxy refuses the connection and
then Postgres answers "the database system is starting up" (#95). The app and
the release command wait it out, for a bounded time, instead of failing."""

import psycopg
import pytest
from fastapi.testclient import TestClient

from dots_and_dashes import persistence
from dots_and_dashes.web import create_app

STARTING_UP = 'connection failed: FATAL:  the database system is starting up'
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
