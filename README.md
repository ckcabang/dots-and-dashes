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
```

`make test` starts the Compose `db` service and runs every suite against a `dots_and_dashes_test` database, which it creates and migrates. To use a different Postgres, set `TEST_DATABASE_URL` (a SQLAlchemy URL such as `postgresql+psycopg://user:pass@host:5432/dbname`); `make test` then skips Docker.

| Suite | Path | Seam |
|---|---|---|
| Unit | `tests/unit` | The Journal domain module (`journal.py`), which is pure: no I/O |
| Integration | `tests/integration` | The HTTP app in-process, against a real Postgres |
| Browser | `tests/browser` | Playwright driving the app served on a local port |

New migrations: `DATABASE_URL=… uv run alembic revision --autogenerate -m "…"`.
