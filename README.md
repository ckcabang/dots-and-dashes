# Dots & Dashes

A personal, keyboard-first bullet journal. See [`CONTEXT.md`](CONTEXT.md) for the domain language and [`_docs/plan.md`](_docs/plan.md) for the plan.

## Run it

```sh
docker compose up --build
```

This starts Postgres and the app, applies the Alembic migrations, and serves the journal at <http://localhost:8000>, behind a login.

There is no sign-up page. Create the User, and the Canary User for monitoring, from the command line, with the password from a secret (the `USER_PASSWORD` environment variable, or the one `--password-env` names) or typed at a prompt:

```sh
docker compose exec app dots-and-dashes create-user --email me@example.com --timezone America/Los_Angeles
docker compose exec -e CANARY_PASSWORD app dots-and-dashes create-user --email canary@example.com --timezone UTC --canary --password-env CANARY_PASSWORD
```

Each User's timezone (an IANA name) decides their "today". A login lasts 30 days, in a session cookie signed with `SESSION_SECRET`. Set it wherever the app is deployed; without it each app process makes its own, so a restart logs everyone out. Set `SECURE_COOKIES=on` where the app is served over HTTPS, so the cookie is never sent in the clear. Entries logged before Users existed belong to the first User created who isn't the Canary User.

On a phone, `/capture` saves raw text as a Capture in the Inbox; on desktop the Daily Log shows the Inbox count, and `/inbox` (`i` from the Daily Log) Triages each Capture into an Entry from the keyboard.

Feature flags are environment variables too, off unless set to `1`, `true`, `yes` or `on`: `FLAG_MONTHLY_REVIEW` turns on the Monthly Review (`/monthly-review`). With a flag off its pages are hidden and its routes answer 404.

Telemetry goes over OTLP to Grafana Cloud when `OTEL_EXPORTER_OTLP_ENDPOINT` (the stack's OTLP gateway, `https://otlp-gateway-<zone>.grafana.net/otlp`) and `OTEL_EXPORTER_OTLP_HEADERS` (`Authorization=Basic <base64 of instance-id:token>`) are set; without them the app runs the same and exports nothing. `DEPLOYMENT_ENVIRONMENT` (`dev`, `prod`) and the Machine's `FLY_IMAGE_REF` label every signal. Every request is a trace, with a span per database statement; logging an Entry (`POST /entries`, `POST /api/entries`) also counts `entry.saves` by `outcome` (`saved`, `refused`, `failed`), times it in `entry.save.duration` (seconds, with exemplars linking to the trace) and logs `Entry saved` or `Entry save failed` on the same trace. No signal carries Entry or Capture text: only an Entry's type, text length and ID, and an error's type, never its message.

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

## Deploy

Dev, <https://dots-and-dashes-dev.fly.dev>, always runs `main`: every merge runs [`.github/workflows/deploy-dev.yml`](.github/workflows/deploy-dev.yml), which builds an image tagged with the commit (`registry.fly.io/dots-and-dashes-dev:<sha>`) and deploys it. The release command applies the Alembic migrations before any Machine moves to the new image. Run the workflow from the Actions tab to redeploy `main` by hand, for instance after changing a Fly secret.

Dev is two Fly apps in `iad`: `dots-and-dashes-dev` ([`fly.dev.toml`](fly.dev.toml)) and its own Postgres, `dots-and-dashes-dev-db` ([`fly.dev-db.toml`](fly.dev-db.toml), [ADR-0003](docs/adr/0003-self-run-postgres-on-fly.md)), which has no public IP and is reached at `dots-and-dashes-dev-db.flycast`. Both stop when idle and start on the next request. `DATABASE_URL`, `SESSION_SECRET` and `FLAG_MONTHLY_REVIEW` are Fly secrets (`flyctl secrets list -a dots-and-dashes-dev`), and the workflow deploys with the `FLY_API_TOKEN` GitHub secret, a deploy token for the dev app only.

To set dev up from nothing (apps, volume, secrets, token, first deploy and your User), run the wizard. It needs [`flyctl`](https://fly.io/docs/flyctl/install/) and `gh`, and is safe to re-run:

```sh
scripts/provision-dev
```
