# Dots & Dashes

A personal, keyboard-first bullet journal web app, run like a production system: deployed to Fly.io, observable in Grafana Cloud, alerting on user impact, with an On-call agent that fixed three staged incidents itself during the live exercise. Its workflow is now disabled to save API cost ([On-call agent](#on-call-agent)).

- **Prod:** <https://dots-and-dashes.fly.dev> (password login; there is no sign-up page, see [Users on a deployed app](#users-on-a-deployed-app))
- **Dev:** <https://dots-and-dashes-dev.fly.dev>, always running `main`
- **Tracker:** [GitHub Issues](https://github.com/ckcabang/dots-and-dashes/issues), starting from the spec, [#1](https://github.com/ckcabang/dots-and-dashes/issues/1)
- **Course criteria:** [each one mapped to its evidence](#course-criteria-and-evidence)

[`CONTEXT.md`](CONTEXT.md) is the glossary: capitalised terms below (Entry, Daily Log, Migration…) are defined there. [`_docs/plan.md`](_docs/plan.md) is the full plan.

## The problem

I keep my to-dos in a paper bullet journal, and its rituals work: rapid logging through the day, then deciding each night or morning what to complete, migrate, schedule or cancel. But paper is awkward away from my desk, rewriting every Migrated Task by hand is tedious, and nothing shows how many times I've put the same Task off. To-do apps lose what makes the journal useful: past days kept as an honest record, the Migration ritual, and capture that is fast and keyboard-driven.

The app has one real User and very little traffic, yet as a course final project it must run like a production system, with alerts on real user impact and an agent on call. A synthetic Canary User supplies the steady traffic the alerts need.

## What it does

- **Rapid logging.** The Daily Log has one always-focused input box. A Prefix sets the Entry's type: `. ` a Task, `o ` an Event, `- ` a Note; no Prefix means a Task. `*` (Priority) and `!` (Inspiration) Signifiers go before the type, and an optional time after it (`14:00`, `9am`, `2:30pm`). So `*. 14:00 call mom` is a Priority Task at 14:00. Entries go on the day you're viewing.
- **Task States.** A Task is Open, Completed (×), Migrated (>), Scheduled (<) or Cancelled (struck through). Delete removes a mistake; Cancel records a decision.
- **Ordering.** Timed Entries stay in chronological order. Each untimed Entry is Anchored to the Timed Entry above it and moves with it when that time changes; untimed Entries can be reordered and re-anchor where they land.
- **Nested Notes.** A Note can be nested one level under a Task or Event, from the keyboard (`Tab`).
- **Logs.** The Daily Log for any day; the Monthly Log (a calendar of the month's Events plus its task list) for the current and past months; the Future Log, later months in month buckets.
- **Migration and Scheduling.** Moving a Task leaves the original in place marked `>` or `<` and creates a fresh Open copy at the destination, which carries its Nested Notes and its time. Each Task shows its Migration Count (`>>3`).
- **Rituals.** Daily Migration, the night before or in the morning (or skipped), lists earlier days' Open Tasks grouped under their Anchor. The Monthly Review on the 1st handles last month's leftover Open Tasks and pulls this month's Future Log Entries in. It is behind the `FLAG_MONTHLY_REVIEW` feature flag.
- **Phone capture.** `/capture` is a minimal page that saves raw text as a Capture in the Inbox. On desktop the Daily Log shows the Inbox count, and `/inbox` (`i` from the Daily Log) Triages each Capture into an Entry on a day, the month's task list or the Future Log.

**Expected behaviour.** Past days stay an honest record: Migration copies a Task and marks the original, it never moves it ([ADR-0001](docs/adr/0001-migration-copies-entries.md)). "Today" follows each User's own timezone. The journal needs a login, which lasts 30 days, and each User sees only their own Entries. With a feature flag off its pages are hidden and its routes answer 404, and the app behaves exactly as before the flag. A save the User got wrong (blank text, an impossible date) is refused with a message; it is not an error. No Entry or Capture text ever leaves the app in telemetry: only an Entry's type, text length and ID.

## Run it locally

One command, with Docker:

```sh
docker compose up --build
```

(`make up` runs the same.) This starts Postgres and the app, applies the Alembic migrations, creates the local User, and serves the journal at <http://localhost:8000>. Log in as:

- **Email:** `me@example.com`
- **Password:** `dots-and-dashes`

The local User's "today" is UTC; set `LOCAL_USER_TIMEZONE` (an IANA name, e.g. `America/Los_Angeles`) before the first `up` to change it. Restarts leave the User as it is.

## Run the tests

Requires [uv](https://docs.astral.sh/uv/) and Docker. One command runs all the suites:

```sh
make setup      # once: Python 3.12 dependencies, Playwright's Chromium, the git hooks
make test       # unit, integration and browser tests (T=path for some only)
make check      # lint, typecheck, then test: the gate CI runs on every pull request
make test-down  # stop the test stack and delete its volume
```

| Suite | Path | Seam |
|---|---|---|
| Unit | `tests/unit` | The Journal domain module (`journal.py`), which is pure: no I/O |
| Integration | `tests/integration` | The HTTP app in-process, against a real Postgres |
| Browser | `tests/browser` | Playwright driving the app container of the test Compose stack |
| Scripts | `tests/scripts` | The provisioning wizards, the On-call scripts and `sync-worktree` |

`make test` builds and starts a Compose project of its own for this checkout (`dots-and-dashes-test-<hash of the path>`, its own volume, host ports the OS picks), so your dev journal is never touched and worktrees can test side by side. Integration tests run against a `dots_and_dashes_test` database on its Postgres, which they create and migrate. `make test-unit`, `make test-integration` and `make test-browser` run one suite; `make test-logs` shows the stack's logs. To run the suites against something else, set `TEST_DATABASE_URL` (a SQLAlchemy URL naming a `*_test` database) and `BASE_URL` and run `uv run pytest`. CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs `make check` on every pull request, then runs the canary script once against the test stack.

New migrations: `DATABASE_URL=… uv run alembic revision --autogenerate -m "…"`.

## Deploy and roll back

| | Dev | Prod |
|---|---|---|
| URL | <https://dots-and-dashes-dev.fly.dev> | <https://dots-and-dashes.fly.dev> |
| Deploys | Automatically, on every merge to `main` | By hand: **Actions → Deploy to prod**, with a commit SHA |
| Workflow | [`deploy-dev.yml`](.github/workflows/deploy-dev.yml) | [`deploy-prod.yml`](.github/workflows/deploy-prod.yml) |
| Fly apps | `dots-and-dashes-dev`, `dots-and-dashes-dev-db` | `dots-and-dashes`, `dots-and-dashes-db` |
| Runs | Stops when idle | Always on |

**Dev.** Every merge to `main` builds an image tagged with the commit (`registry.fly.io/dots-and-dashes-dev:<sha>`) and deploys it. The release command, `dots-and-dashes migrate`, applies the Alembic migrations before any Machine moves to the new image, and the run ends with a smoke test. Run the workflow from the Actions tab to redeploy `main` by hand, for instance after changing a Fly secret.

**Prod.** Prod never builds: it runs the exact image dev ran. Pick the SHA of a `main` merge whose dev deploy passed, then:

```sh
gh workflow run deploy-prod.yml -f version=<sha>
```

The run copies dev's image into prod's registry (`registry.fly.io/dots-and-dashes:<sha>`), deploys it, and smoke-tests `/login`. It refuses a commit that isn't on `main`.

**Roll back.** The same run with an earlier SHA. Each run is titled `Deploy <sha> to prod`, so `gh run list --workflow deploy-prod.yml --status success` is prod's history. A rollback restores the image only; Fly secrets (feature flags, pool size) stay as they are. [`docs/runbooks/deploy.md`](docs/runbooks/deploy.md) is the full runbook.

Each environment is two Fly apps in `iad`: the app ([`fly.dev.toml`](fly.dev.toml), [`fly.prod.toml`](fly.prod.toml)) and its own Postgres on a Fly Machine ([`fly.dev-db.toml`](fly.dev-db.toml), [`fly.prod-db.toml`](fly.prod-db.toml), [ADR-0003](docs/adr/0003-self-run-postgres-on-fly.md)), which has no public IP and is reached over Flycast. `DATABASE_URL`, `SESSION_SECRET`, `FLAG_MONTHLY_REVIEW` and the telemetry settings are Fly secrets. CD deploys with the `FLY_API_TOKEN` (dev) and `FLY_PROD_API_TOKEN` (prod) GitHub secrets, each a deploy token for its own app only. To set an environment up from nothing (apps, volume, secrets, token, first deploy and your User), run its wizard; each needs [`flyctl`](https://fly.io/docs/flyctl/install/) and `gh` and is safe to re-run:

```sh
scripts/provision-dev
scripts/provision-prod   # once deploy-prod.yml is on main and dev has deployed
```

### Users on a deployed app

There is no sign-up page, and only Compose makes the local User. On Fly the release command only migrates, so create the User, and the Canary User for monitoring, from the command line on the app's Machine (`scripts/provision-dev` and `scripts/provision-prod` walk through it, and `scripts/provision-canary` for the Canary User), with the password from a secret (the `USER_PASSWORD` environment variable, or the one `--password-env` names), piped in with `--password-stdin`, or typed at a prompt:

```sh
fly ssh console -a <app> --pty -C "/app/.venv/bin/dots-and-dashes create-user --email me@example.com --timezone America/Los_Angeles"
fly ssh console -a <app> --pty -C "/app/.venv/bin/dots-and-dashes create-user --email canary@example.com --timezone UTC --canary"
```

Each User's timezone (an IANA name) decides their "today". A login lasts 30 days, in a session cookie signed with `SESSION_SECRET`. Set it wherever the app is deployed; without it each app process makes its own, so a restart logs everyone out. Set `SECURE_COOKIES=on` where the app is served over HTTPS, so the cookie is never sent in the clear. Entries logged before Users existed belong to the first User created who isn't the Canary User.

Feature flags are environment variables too, off unless set to `1`, `true`, `yes` or `on`: `FLAG_MONTHLY_REVIEW` turns on the Monthly Review (`/monthly-review`).

## Observability

The key journey is **logging an Entry on today's Daily Log**. Telemetry goes over OTLP to Grafana Cloud (Tempo, Loki, Prometheus) when `OTEL_EXPORTER_OTLP_ENDPOINT` (the stack's OTLP gateway, `https://otlp-gateway-<zone>.grafana.net/otlp`) and `OTEL_EXPORTER_OTLP_HEADERS` (`Authorization=Basic <base64 of instance-id:token>`) are set; without them the app runs the same and exports nothing.

- **Traces.** Every request is a trace, with a span per database statement and a `db.connection.checkout` span for each wait on the connection pool.
- **Metrics.** Logging an Entry (`POST /entries`, `POST /api/entries`) counts `entry.saves` by `outcome` (`saved`, `refused`, `failed`) and times it in `entry.save.duration` (seconds), whose exemplars link to the trace.
- **Logs.** Structured: `Entry saved` or `Entry save failed`, on the same trace ID as the request's spans.
- **Labels.** `DEPLOYMENT_ENVIRONMENT` (`dev`, `prod`) and the Machine's `FLY_IMAGE_REF` label every signal. The environment is also the `service.namespace`, so Grafana's `job` label reads `prod/dots-and-dashes` or `dev/dots-and-dashes`.
- **No journal text.** No signal carries Entry or Capture text: only an Entry's type, text length and ID, and an error's type, never its message. [`tests/integration/test_telemetry.py`](tests/integration/test_telemetry.py) proves it with in-memory exporters.

The **Dots & Dashes: key journey** dashboard ([`monitoring/dashboard.json`](monitoring/dashboard.json)) shows the save failure rate, saves by outcome, p95 save latency (with exemplars) and the canary pass rate, filtered by environment and image.

### Canary and alerts

Two Grafana Synthetic Monitoring scripted checks run [`monitoring/canary.js`](monitoring/canary.js), each as its environment's Canary User: log in, log an Entry, read it back, delete it. One runs against prod every minute, the other against dev every 15 minutes. That steady traffic is what the alerts fire on, with one real User.

Three alerts, each with a prod and a dev rule ([`monitoring/alert-rules.json`](monitoring/alert-rules.json)), all on user impact:

- **Save failures:** Entry save failure rate above 5% over 10 minutes.
- **Save latency:** p95 Entry save latency above 1s over 10 minutes.
- **Canary failing:** the canary passed under 80% of its runs (and, on prod, a canary that stops reporting).

Each notification names the environment and image and links the dashboard, the panel and the runbook section. [`docs/runbooks/README.md`](docs/runbooks/README.md) is the runbook for each alert. To create both Canary Users and both checks, import the rules and dashboard, and fire the dev alerts once, run its wizard once prod is up:

```sh
scripts/provision-canary
```

## On-call agent

When an alert fires, Grafana's webhook sends a `repository_dispatch` event that runs [`.github/workflows/on-call.yml`](.github/workflows/on-call.yml): Claude Code as the On-call agent ([`scripts/on-call/agent.md`](scripts/on-call/agent.md)). It diagnoses from Grafana and Fly, applies one of three remedies through [`scripts/on-call/remedy`](scripts/on-call/remedy) (roll back, turn a feature flag off, raise the DB pool size and redeploy), and files an incident issue. Anything else goes to the human, labelled `ready-for-human` ([ADR-0002](docs/adr/0002-on-call-agent-in-github-actions.md); [runbook](docs/runbooks/README.md#the-on-call-agent)).

It woke on real alerts and fixed all three staged scenarios on dev on 2026-10-27 ([#80's live-run summary](https://github.com/ckcabang/dots-and-dashes/issues/80#issuecomment-6445833970)):

| Scenario | Incident issue the agent filed | Remedy it ran |
|---|---|---|
| Broken feature flag | [#91](https://github.com/ckcabang/dots-and-dashes/issues/91) | `remedy flag-off dev FLAG_MONTHLY_REVIEW` |
| DB connection pool exhausted | [#93](https://github.com/ckcabang/dots-and-dashes/issues/93) | `remedy raise-pool dev 10 --above 1` |
| Bad deploy | [#94](https://github.com/ckcabang/dots-and-dashes/issues/94) | `remedy rollback dev --from <the bad image>` |

It also handed two alerts no remedy fits to the human: [#90](https://github.com/ckcabang/dots-and-dashes/issues/90) (dev Postgres cold start, since fixed by #95) and [#92](https://github.com/ckcabang/dots-and-dashes/issues/92) (prod canary check disabled by mistake).

**The On-call workflow is disabled now**, to save Claude API cost (`gh workflow disable on-call.yml`). While it is disabled, alerts still fire in Grafana and notify the contact point, but no agent runs. To re-enable it:

```sh
gh workflow enable on-call.yml
```

To create its tokens, store them as GitHub secrets, wire the contact point and notification policy, and send a test notification, run its wizard from `main` once the alerts are imported:

```sh
scripts/provision-oncall
```

## The agent team and the docs

The project is built by four agents and a human, handing work over through the tracker ([`docs/process/agent-team.md`](docs/process/agent-team.md)): the **Spec** agent turns an idea into a spec issue and tickets with acceptance criteria; the **Builder** builds one ticket test-first and opens a PR that closes it; the **Reviewer** posts a verdict on the PR against each acceptance criterion; the **On-call** agent answers alerts. The human merges and deploys to prod. Their definitions are in [`.claude/agents/`](.claude/agents/).

[`AGENTS.md`](AGENTS.md) is the entry point for agents ([`CLAUDE.md`](CLAUDE.md) is just `@AGENTS.md`). It points to:

| Doc | What it holds |
|---|---|
| [`CONTEXT.md`](CONTEXT.md) | The glossary |
| [`docs/adr/`](docs/adr/) | Decisions made |
| [`docs/architecture/README.md`](docs/architecture/README.md) | Modules, the test seams, where the system runs |
| [`docs/process/implementing.md`](docs/process/implementing.md) | How a ticket is built on a branch |
| [`docs/process/agent-team.md`](docs/process/agent-team.md) | The handoffs between agents and the human |
| [`CODING_STANDARDS.md`](CODING_STANDARDS.md) | The rules a review enforces |
| [`docs/runbooks/`](docs/runbooks/README.md) | Alerts, incidents, deploy and rollback, running costs |
| [`docs/agents/`](docs/agents/) | Tracker commands, triage labels, domain-doc layout |

## Course criteria and evidence

Course reviewers can't log in to Grafana Cloud or Fly, so each criterion of [`_docs/final_project_rubric.md`](_docs/final_project_rubric.md) links to evidence on GitHub. Screenshots of Grafana are in [`docs/evidence/`](docs/evidence/README.md).

| Criterion | Where it is satisfied | Evidence |
|---|---|---|
| **Problem description** (2) | [The problem](#the-problem), [What it does](#what-it-does) | The spec's problem statement and user stories: [#1](https://github.com/ckcabang/dots-and-dashes/issues/1) |
| **Product specification** (2) | Spec [#1](https://github.com/ckcabang/dots-and-dashes/issues/1), with [`_docs/plan.md`](_docs/plan.md) and [`CONTEXT.md`](CONTEXT.md); a public tracker | Tickets [#3](https://github.com/ckcabang/dots-and-dashes/issues/3)–[#22](https://github.com/ckcabang/dots-and-dashes/issues/22) are sub-issues of #1, each with acceptance criteria ticked as met, e.g. [#8](https://github.com/ckcabang/dots-and-dashes/issues/8), [#9](https://github.com/ckcabang/dots-and-dashes/issues/9). Agents using the tracker: the Reviewer linking its verdict on the issue ([#54](https://github.com/ckcabang/dots-and-dashes/issues/54#issuecomment-6429514699), [#73](https://github.com/ckcabang/dots-and-dashes/issues/73#issuecomment-6433568982)); the On-call agent filing [#91](https://github.com/ckcabang/dots-and-dashes/issues/91), [#93](https://github.com/ckcabang/dots-and-dashes/issues/93), [#94](https://github.com/ckcabang/dots-and-dashes/issues/94) |
| **Agent team specification** (2) | [`docs/process/agent-team.md`](docs/process/agent-team.md), [`.claude/agents/`](.claude/agents/), [`scripts/on-call/agent.md`](scripts/on-call/agent.md) | Builder PRs that start `Closes #<n>`, e.g. [#84](https://github.com/ckcabang/dots-and-dashes/pull/84) for #22. Reviewer verdicts on PRs: [#53](https://github.com/ckcabang/dots-and-dashes/pull/53#pullrequestreview-5659600279) changes requested, then [ready to merge](https://github.com/ckcabang/dots-and-dashes/pull/53#pullrequestreview-5659668127); [#69](https://github.com/ckcabang/dots-and-dashes/pull/69#pullrequestreview-5660778535) three rounds, then [ready to merge](https://github.com/ckcabang/dots-and-dashes/pull/69#pullrequestreview-5662072357); [#84](https://github.com/ckcabang/dots-and-dashes/pull/84#pullrequestreview-5662927267); [#50](https://github.com/ckcabang/dots-and-dashes/pull/50#pullrequestreview-5659474379); [#62](https://github.com/ckcabang/dots-and-dashes/pull/62#pullrequestreview-5660183369). Human handoffs labelled `ready-for-human`: [#80](https://github.com/ckcabang/dots-and-dashes/issues/80), [#102](https://github.com/ckcabang/dots-and-dashes/issues/102), [#103](https://github.com/ckcabang/dots-and-dashes/issues/103) |
| **Context management** (2) | [`AGENTS.md`](AGENTS.md), and [`CLAUDE.md`](CLAUDE.md) as `@AGENTS.md` | The modular docs it points to: [the table above](#the-agent-team-and-the-docs) |
| **Application** (2) | FastAPI + Jinja/HTMX + Postgres; `docker compose up --build` | Integration tests drive the HTTP app against a real Postgres ([`tests/integration/`](tests/integration/)); browser tests drive the running container ([`tests/browser/`](tests/browser/)); deployed at <https://dots-and-dashes.fly.dev> |
| **Testing** (2) | Unit, integration and browser suites, one command: `make test` | [`tests/`](tests/); a [CI run on PR #99](https://github.com/ckcabang/dots-and-dashes/actions/runs/40534001804) passing `make check` |
| **Containerization** (2) | [`Dockerfile`](Dockerfile), [`docker-compose.yml`](docker-compose.yml): app and Postgres, one command | [Run it locally](#run-it-locally); the browser suite and CI's canary run against the same Compose stack |
| **Deployment** (2) | Fly.io, <https://dots-and-dashes.fly.dev> | The latest [prod deploy](https://github.com/ckcabang/dots-and-dashes/actions/runs/40448895422) passing its smoke test of the public URL |
| **CI/CD** (3) | [`ci.yml`](.github/workflows/ci.yml) on every PR; [`deploy-dev.yml`](.github/workflows/deploy-dev.yml) on every merge; [`deploy-prod.yml`](.github/workflows/deploy-prod.yml) by hand | [CI on a PR](https://github.com/ckcabang/dots-and-dashes/actions/runs/40534001804); [dev deploy on the merge of #101](https://github.com/ckcabang/dots-and-dashes/actions/runs/40535041059); prod deploys by hand: [first](https://github.com/ckcabang/dots-and-dashes/actions/runs/40407639189), [latest](https://github.com/ckcabang/dots-and-dashes/actions/runs/40448895422); rollback as the same run with an earlier SHA: [479edbc](https://github.com/ckcabang/dots-and-dashes/actions/runs/40421835511), then forward to [4b34c82](https://github.com/ckcabang/dots-and-dashes/actions/runs/40422236152) ([#8](https://github.com/ckcabang/dots-and-dashes/issues/8#issuecomment-6430095263)). Prod had only run 479edbc before, so that run shows an earlier SHA deploying, not prod leaving a newer image; the agent's rollback off a bad image is [#94](https://github.com/ckcabang/dots-and-dashes/issues/94) on dev |
| **Observability** (2) | [Observability](#observability); [`telemetry.py`](src/dots_and_dashes/telemetry.py); [`dashboard.json`](monitoring/dashboard.json) | Shared trace ID and no Entry or Capture text, proved by [`test_telemetry.py`](tests/integration/test_telemetry.py) (`test_saved_entry_and_capture_text_never_enters_a_signal`, `test_entry_text_never_enters_a_signal_even_when_a_save_fails`). Signals in Grafana: dev and prod traces in Tempo ([#9](https://github.com/ckcabang/dots-and-dashes/issues/9#issuecomment-6430085291), [prod](https://github.com/ckcabang/dots-and-dashes/issues/9#issuecomment-6430109683)); the On-call agent citing trace IDs, `db.connection.checkout` spans and Prometheus readings ([#93](https://github.com/ckcabang/dots-and-dashes/issues/93)) and Loki logs ([#94](https://github.com/ckcabang/dots-and-dashes/issues/94)). Entry text kept out of Fly's logs too ([#54](https://github.com/ckcabang/dots-and-dashes/issues/54)). Screenshots: [trace, log and exemplar with one trace ID, and a log search finding no Entry text](docs/evidence/README.md#observability). The canary's k6 debug logs leaked the Canary User's session cookie into Synthetic Monitoring's logs (not the app's telemetry); fixed by [#98](https://github.com/ckcabang/dots-and-dashes/issues/98) / [PR #100](https://github.com/ckcabang/dots-and-dashes/pull/100) (merged: the canary refuses to log in with k6's HTTP debug logging on); confirming the episode and rotating `SESSION_SECRET` is still open in [#102](https://github.com/ckcabang/dots-and-dashes/issues/102) |
| **Alerting on user impact** (1) | [`monitoring/alert-rules.json`](monitoring/alert-rules.json): save failures, save latency, canary failing, for prod and dev | Six rules read back from Grafana ([#80](https://github.com/ckcabang/dots-and-dashes/issues/80#issuecomment-6435697689)); alerts firing and resolving, each On-call run being one notification: Save failures (dev) for the broken flag, [firing](https://github.com/ckcabang/dots-and-dashes/actions/runs/40467354591) and [resolved](https://github.com/ckcabang/dots-and-dashes/actions/runs/40468860977) ([#91](https://github.com/ckcabang/dots-and-dashes/issues/91)); Save latency (dev), [firing](https://github.com/ckcabang/dots-and-dashes/actions/runs/40520864099) and [resolved](https://github.com/ckcabang/dots-and-dashes/actions/runs/40522458298) ([#93](https://github.com/ckcabang/dots-and-dashes/issues/93)); Save failures (dev) for the bad deploy, [firing](https://github.com/ckcabang/dots-and-dashes/actions/runs/40525899967) and [resolved](https://github.com/ckcabang/dots-and-dashes/actions/runs/40528390753) ([#94](https://github.com/ckcabang/dots-and-dashes/issues/94)). Not user impact: Canary failing (prod) [fired](https://github.com/ckcabang/dots-and-dashes/actions/runs/40498279930) and [resolved](https://github.com/ckcabang/dots-and-dashes/actions/runs/40518164796) because the prod check was disabled by mistake and stopped reporting, with the app healthy ([#92](https://github.com/ckcabang/dots-and-dashes/issues/92)). Screenshots: [the dashboard, the six rules and an alert firing](docs/evidence/README.md#alerting) |
| **On-call agent** (2) | [On-call agent](#on-call-agent); [ADR-0002](docs/adr/0002-on-call-agent-in-github-actions.md); [`on-call.yml`](.github/workflows/on-call.yml) | Woke on an alert and fixed it, three times: [#91](https://github.com/ckcabang/dots-and-dashes/issues/91) (flag off, [run](https://github.com/ckcabang/dots-and-dashes/actions/runs/40467354591)), [#93](https://github.com/ckcabang/dots-and-dashes/issues/93) (raise pool, [run](https://github.com/ckcabang/dots-and-dashes/actions/runs/40520864099)), [#94](https://github.com/ckcabang/dots-and-dashes/issues/94) (rollback, [run](https://github.com/ckcabang/dots-and-dashes/actions/runs/40525899967)); [#80's live-run summary](https://github.com/ckcabang/dots-and-dashes/issues/80#issuecomment-6445833970). Disabled now to save API cost; `gh workflow enable on-call.yml` turns it back on |

Open follow-ups: [#102](https://github.com/ckcabang/dots-and-dashes/issues/102) (confirm and clean up the canary cookie leak) and [#103](https://github.com/ckcabang/dots-and-dashes/issues/103) (find why dev's Postgres stopped under load in the pool scenario), both for the human.
