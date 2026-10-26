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
make test       # unit, integration and browser tests (T=path for some only)
make test-unit  # one suite: also test-integration, test-browser
make lint       # ruff, and a single Alembic head
make typecheck  # mypy
make check      # lint, typecheck, then test
```

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs `make check` on every pull request.

`make test` builds and starts a Compose project of its own for this checkout (`dots-and-dashes-test-<hash of the path>`, its own volume, host ports the OS picks), so your dev journal is never touched and worktrees can test side by side. Integration tests run against a `dots_and_dashes_test` database on its Postgres, which they create and migrate. Browser tests drive its app container. `make test T=tests/unit` runs some tests only. To run the suites against something else, set `TEST_DATABASE_URL` (a SQLAlchemy URL naming a `*_test` database) and `BASE_URL` and run `uv run pytest`. `make test-logs` shows the stack's logs; `make test-down` stops it and deletes its volume.

| Suite | Path | Seam |
|---|---|---|
| Unit | `tests/unit` | The Journal domain module (`journal.py`), which is pure: no I/O |
| Integration | `tests/integration` | The HTTP app in-process, against a real Postgres |
| Browser | `tests/browser` | Playwright driving the app container of the test Compose stack |

New migrations: `DATABASE_URL=… uv run alembic revision --autogenerate -m "…"`.
