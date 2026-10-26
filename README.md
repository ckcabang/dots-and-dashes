# Dots & Dashes

A personal, keyboard-first bullet journal. See [`CONTEXT.md`](CONTEXT.md) for the domain language and [`_docs/plan.md`](_docs/plan.md) for the plan.

## Run it

```sh
docker compose up --build
```

This starts Postgres and the app, applies the Alembic migrations, and serves today's Daily Log at <http://localhost:8000>. "Today" uses the `JOURNAL_TIMEZONE` environment variable (an IANA name, default `UTC`), for example `JOURNAL_TIMEZONE=America/Los_Angeles docker compose up`.

## Develop

Requires [uv](https://docs.astral.sh/uv/) and Docker.

```sh
make setup      # install Python 3.12 dependencies and Playwright's Chromium
make test       # unit, integration and browser tests
make typecheck  # mypy
make check      # typecheck, then test
```

`make test` builds and starts a separate Compose project, `dots-and-dashes-test` (Postgres on port 55432, app on 58000, its own volume), so your dev journal is never touched. Integration tests run against a `dots_and_dashes_test` database on that Postgres, which they create and migrate. Browser tests drive the stack's app container. To point the suites elsewhere, set `TEST_DATABASE_URL` (a SQLAlchemy URL naming a `*_test` database) and `BASE_URL`. Stop the stack with `COMPOSE_PROJECT_NAME=dots-and-dashes-test docker compose down`.

| Suite | Path | Seam |
|---|---|---|
| Unit | `tests/unit` | The Journal domain module (`journal.py`), which is pure: no I/O |
| Integration | `tests/integration` | The HTTP app in-process, against a real Postgres |
| Browser | `tests/browser` | Playwright driving the app container of the test Compose stack |

New migrations: `DATABASE_URL=… uv run alembic revision --autogenerate -m "…"`.
