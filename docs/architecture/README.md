# Architecture

## Modules

All code is in `src/dots_and_dashes/`:

- **Journal** (`journal.py`): the domain. Pure: plain values in and out, with the clock and timezone passed in. The Prefix parser, Anchoring, Migration and Scheduling rules, and Monthly Review selection live here.
- **Persistence** (`persistence.py`): maps Journal values to Postgres tables through SQLAlchemy. Schema changes are Alembic migrations in `migrations/versions/`.
- **Web** (`web.py`): thin FastAPI routes that parse the request, call the Journal, persist and render. Pages are server-rendered Jinja templates (`templates/`) with HTMX and a little vanilla JS for the keyboard.
- **Accounts** (`accounts.py`): the User and the Canary User, and argon2 password hashing. `cli.py` is the only way a User is made (`dots-and-dashes create-user`; docker-compose.yml runs it with `--if-missing` on every start to give a local stack its User, and Fly's release command never does); there is no sign-up route. A login is a signed session cookie lasting 30 days, and every journal page and API route refuses a request without one. Each request's database session is scoped to its User, so Persistence reads and writes only that User's Entries and Captures; a session with no User reads none.
- **Telemetry** (`telemetry.py`): the tracer, meter and logger, exported over OTLP when configured. ASGI middleware makes a span per request and counts and times the Entry saves of the key journey; a traced connection pool adds a span per connection checkout (the wait for a free connection), and SQLAlchemy events a span per statement. It records an error's type, never its message, and an Entry's type, length and ID, never its text. The middleware also answers a request that raises, with Starlette's plain 500, and writes one stderr line with the error type and trace ID in place of uvicorn's traceback, which would quote the failing row into Fly's logs. Tests hand `create_app` a `Telemetry` with in-memory exporters.
- **Settings** (`settings.py`): operations config read from environment variables. Feature flags and the chaos switch are environment variables too, so they can change without a code deploy. The chaos switch itself (`chaos.py`) fails or slows Entry saves on purpose, to stage an incident; it stays out of the Journal.

Rules belong in the Journal. If a route or a query starts deciding domain behaviour, move the decision into `journal.py` where a unit test can reach it.

## Test seams

Exactly three, each testing behaviour through a public interface:

1. **Journal (unit, `tests/unit`)**: domain rules with an injected clock and timezone, no I/O. `tests/unit/test_templates.py` beside them is a build check, not a seam: every template compiles.
2. **HTTP API (integration, `tests/integration`)**: the app in-process against a real Postgres.
3. **Browser (`tests/browser`)**: Playwright driving the app container for the key journeys.

`make test` runs all three against a Compose stack of the checkout's own (see `README.md`).

## Where it runs

- **Local**: `docker compose up` (app + Postgres).
- **Hosting**: Fly.io, two apps, `dots-and-dashes-dev` and `dots-and-dashes` (prod), each with its own self-run Postgres Machine (ADR-0003). Alembic migrations run as the release command, `dots-and-dashes migrate`.
- **CI/CD**: GitHub Actions. CI runs `make check` on every PR. A merge to `main` deploys to dev (`deploy-dev.yml`, `fly.dev.toml`; set up with `scripts/provision-dev`); prod deploys and rollbacks are a manual `workflow_dispatch` with an image tag (`deploy-prod.yml`, `fly.prod.toml`; set up with `scripts/provision-prod`; `docs/runbooks/deploy.md`). Both run `dots-and-dashes migrate` as the release command.
- **Telemetry**: OpenTelemetry to Grafana Cloud. Traces, metrics and logs share a trace ID. Entry and Capture text never enters a signal: record type, length and IDs instead. Fly's logs count too: the app writes a failed request as its error type and trace ID only, and the Postgres Machines run with `log_error_verbosity=terse` and no statement or bind values on error (`[processes]` in `fly.*-db.toml`), so a refused row's `DETAIL: Failing row contains (...)` is never logged. Terse still logs Postgres's primary message, which for a type error such as `invalid input syntax` can quote the value; the app never binds journal text to a typed column.
- **Canary**: a Canary User exercises the key journey (log an Entry on today's Daily Log) every minute, so the save failure and save latency alerts have traffic to fire on.
