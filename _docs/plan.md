# Dots & Dashes: Project Plan

A personal, keyboard-first bullet journal web app, built as the course final project.
This document captures the agreed scope and decisions. Domain vocabulary lives in [`CONTEXT.md`](../CONTEXT.md), and lasting decisions are recorded in [`docs/adr/`](../docs/adr/). Acceptance criteria will be added per issue in the tracker.

## Name

| | |
|---|---|
| **App name** | Dots & Dashes |
| **Repo name** | `dots-and-dashes` |

**Why this name**

- It's a nod to the tiki cocktail **Three Dots and a Dash**, whose name is Morse code for V (`...–`).
- It matches the app's prefix syntax: `.` creates a task and `-` creates a note.

**Usage**

- Use **Dots & Dashes** as the display name in the README and the app UI.
- Use `dots-and-dashes` for the repo, packages and other identifiers. Repo names can't contain `&`, and lowercase with hyphens is the GitHub convention.
- Avoid the one-word "Dotdash", which is already the name of a large media company (Dotdash Meredith).

**Logo idea:** BuJo in Morse code, `–... ..– .––– –––`.

## Core Job

Primary: **task management**. Capture to-dos fast and keep a focused task list with bullet journal rituals (complete, migrate, schedule, cancel).

Secondary:

- **Planning ahead** with monthly and future logs.
- **Light notes and reflections** about the day.

## Scope v1

### Capture

**Desktop (main app):** a single input box using the prefix grammar `[signifiers][type] [time] text`.

| Prefix | Meaning |
|--------|---------|
| `. ` | Task (•) |
| `o ` | Event (○) |
| `- ` | Note (–) |
| `*` | Signifier: priority |
| `!` | Signifier: inspiration |

- Examples: `*. 14:00 call mom`, `!- idea about X`, `*!. ship it`, `o 7pm dinner`.
- Signifiers come **before** the type character. Either or both may be used.
- The type character needs a trailing space, so `.5 miles run` is not read as a task.
- Time is optional. It goes right after the type and accepts `HH:MM`, `9am` or `2:30pm`.
- **No prefix means a task.**
- Desktop input always creates Entries on the page you're on. It never goes to the Inbox.

**Mobile quick-capture page:**

- A minimal, mobile-first page for jotting things down on the go.
- Saves raw text as a **Capture** with no type. Captures go to the **Inbox**.

**Inbox triage (on desktop):**

- Triage reads the Capture's text with the prefix grammar to suggest a type, signifiers and time (no prefix suggests a task). You can adjust the suggestion before placing it.
- Each Capture is placed on one of: a specific day, the current month's task list or the future log. It can also be deleted.

### Entries

- **Types:** task, event, note.
- **Task states:** open, completed (×), migrated (>), scheduled (<), cancelled (struck through).
- **Optional time** on both tasks and events. Time is never required.
- **Notes** can stand alone or be **nested one level** under a task or event. You nest a note with a keyboard action after capture (for example `Tab` attaches the selected note to the entry above). Notes never nest under notes, and tasks never nest under tasks.
- **Signifiers:** `*` priority and `!` inspiration. An entry can have both.
- **Delete vs cancel:** delete permanently removes a mistake. Cancel records a decision about a task. Deleting one copy in a migration chain re-links the chain around it.

### Ordering Within a Day

- **Timed entries always stay in chronological order** and can't be dragged. You move one by changing its time.
- Every untimed entry is **anchored** to the timed entry above it, meaning "sometime after that, no specific time". Untimed entries at the top of the day have no anchor.
- When a timed entry's time changes, its anchored entries **move with it**. If you missed the timed thing, you probably missed what followed it too.
- Untimed entries can be dragged anywhere and re-anchor to whatever timed entry ends up above them.

### Logs

| Log | Description |
|-----|-------------|
| **Daily log** | One day's page: quick entry plus the ordered list of entries. Can exist for any date, including future days this month. |
| **Monthly log** | Exists for the **current and past months** only. It shows a calendar **derived** from that month's events plus the month's task list. |
| **Future log** | Months after the current one, organized in **month buckets**. Each entry can have an optional specific date. |
| **Inbox** | Captures from mobile waiting for triage. |

### Migration and Scheduling

Only **tasks** are migrated or scheduled. Moving an event is just a date edit with no history. Standalone notes stay on their day.

| Action | Destination | Original becomes |
|--------|-------------|------------------|
| **Migrate** | The day being planned (today, or tomorrow when you do it the night before), or the current month's task list | `>` migrated |
| **Schedule** | A later day this month (lands on that daily log), or a later month (future log, optional date) | `<` scheduled |

- Both create a **new open copy** at the destination and leave the original in place with its marker ([ADR-0001](../docs/adr/0001-migration-copies-entries.md)).
- **Nested notes move to the new copy.** The original keeps only its marker.
- A migrated timed task **keeps its time**.
- Each task shows its **migration count** (for example `>>3`): the length of its chain of copies, counting both migrations and schedulings.

**Daily migration**

- Can be done **the night before or each morning**.
- Can be **skipped** and done later **manually** whenever you choose.
- Lists open tasks from earlier days **grouped under their anchor**, so a missed block can be handled in a few keystrokes. Each task is still decided on its own: complete, migrate, schedule or cancel.

**Monthly review (on the 1st)**

- Shows **all of last month's leftover open tasks**, each to be completed, migrated, scheduled or cancelled.
- Also pulls **this month's future log entries** into the new monthly log (or onto their day, if dated). Their future log originals are marked migrated.

### Users

- **Single user** (you), with a password login so the journal stays private when deployed publicly.
- A separate **canary user** for synthetic monitoring, so test entries never touch the real journal.
- Both are created with a CLI command (`dots-and-dashes create-user --email … [--canary]`), with the password supplied through a secret. There is no sign-up page.
- Each user has an **IANA timezone**. "Today" runs from local midnight to midnight, with no rollover hour.
- A **30-day cookie session** is shared by desktop and mobile, so quick capture stays one tap.

### Stretch Goals (after all 12 criteria are covered)

- Search across entries
- Habit tracker (monthly grid)
- Custom collections (e.g. "Books to read")
- Markdown export
- Offline support (PWA)

## Draft Data Model

Subject to change during design.

```
users
  id, email, password_hash, timezone, is_canary

captures
  id, user_id, text, created_at

entries
  id, user_id
  type            task | event | note
  status          open | completed | migrated | scheduled | cancelled   (tasks only)
  text
  is_priority     bool
  is_inspiration  bool
  time            optional time of day
  location        day | month | future
  date            set for day entries; optional for future entries
  month           set for month and future entries
  position        manual sort order within its location (anchoring is derived from position + time)
  parent_id       set when a note is nested under a task/event
  migrated_from_id  links a copy to its previous copy (chain length = migration count)
  created_at, updated_at
```

## Stack and Infrastructure

| Area | Decision |
|------|----------|
| **Language / tooling** | Python **3.12** (bump `.python-version` from 3.9, which is end-of-life), `uv` |
| **Backend** | FastAPI, SQLAlchemy, Alembic |
| **Frontend** | Server-rendered Jinja + HTMX, with a little vanilla JS for keyboard handling |
| **Database** | Postgres |
| **Tests** | pytest for unit and integration (integration runs against a real Postgres). Playwright for a few frontend journeys. One command: `make test` |
| **Local run** | `docker compose up` (app + Postgres) |
| **Hosting** | Fly.io (`iad`), two apps: `dots-and-dashes-dev` and `dots-and-dashes` (prod). Each has its own **self-run Postgres** on a Fly Machine with a 1GB volume ([ADR-0003](../docs/adr/0003-self-run-postgres-on-fly.md)). Alembic migrations run as the Fly release command. Estimated cost is about **$8/month** (see Hosting Cost below). |
| **Telemetry** | OpenTelemetry SDK → Grafana Cloud (free tier): Tempo traces, Loki logs, Prometheus/Mimir metrics, Grafana UI |
| **Canary** | Grafana Synthetic Monitoring (scripted k6 check) every minute against prod, logged in as the canary user |
| **Feature flags & chaos switch** | Environment variables / Fly secrets (e.g. `FLAG_MONTHLY_REVIEW`, `CHAOS_SAVE_ERROR_RATE`, `CHAOS_SAVE_LATENCY_MS`, `DB_POOL_SIZE`) |

## Agent Team

Agents hand work to each other through GitHub issue labels (see `docs/agents/triage-labels.md`). This also leaves visible evidence that the tracker was used.

| Agent | Responsibility | Hands off by |
|-------|----------------|--------------|
| **Spec** | Grills ideas into specs, then splits them into issues with acceptance criteria | Labelling issues `ready-for-agent` |
| **Builder** | Takes a `ready-for-agent` issue and works TDD on a branch | Opening a PR that links the issue |
| **Reviewer** | Reviews the PR against the issue's acceptance criteria and repo standards | Approving or requesting changes |
| **On-call** | Woken by an alert, diagnoses from telemetry and applies a fixed set of remedies ([ADR-0002](../docs/adr/0002-on-call-agent-in-github-actions.md)) | Filing an incident issue describing what it did |

The human merges PRs and triggers production deploys. Agents are defined in `.claude/agents/`, and the process is described in `docs/process/agent-team.md`.

## How It Maps to the Course Criteria

| Criterion | Plan |
|-----------|------|
| **Problem description** | README describes the bullet journal workflow and the features above. |
| **Product spec + tracker** | This plan plus `CONTEXT.md` form the spec. Features are split into GitHub Issues with acceptance criteria on `ckcabang/dots-and-dashes`. |
| **Agent team** | Spec, builder, reviewer and on-call agents, with label-based handoffs (see above). |
| **Context management** | `AGENTS.md` is the source of truth and links to modular docs (`docs/process/`, `docs/architecture/`, `docs/runbooks/`, `CONTEXT.md`, `docs/adr/`). `CLAUDE.md` is just `@AGENTS.md`. |
| **Application** | FastAPI + HTMX + Postgres, started locally with `docker compose up`. |
| **Unit tests** | Prefix parser (types, signifiers, times, edge cases), ordering and anchoring rules, migration/scheduling rules (destinations, month rollover, chains and counts, nested notes moving). |
| **Integration tests** | Create an entry via the API, it persists, migrate it, it appears on the new day, and the original is marked `>`. Capture triage to a day, the month or the future log. Monthly review pulls future log entries. |
| **Frontend tests** | Playwright: quick entry on today's page, mobile capture, inbox triage. |
| **Containerization** | Docker Compose for the app and database, one command. |
| **Deployment** | Public URL on Fly.io. |
| **CI/CD** | GitHub Actions. CI runs all tests on each PR. A merge to `main` builds an image and auto-deploys to dev. Production deploy is a manual `workflow_dispatch` with an image tag. Rollback redeploys a previous tag. |
| **Observability** | Key journey: **log an entry on today's page**. Metrics, traces and structured logs share a trace ID. **Entry and Capture text are never sent to telemetry**: only type, length and IDs are recorded. |
| **Alerting on user impact** | Entry save failure rate > 5% over 10 min, or p95 save latency > 1s (canary traffic keeps these meaningful). |
| **On-call agent** | Grafana webhook → GitHub Actions → Claude Code with a fixed set of remedies (see below and ADR-0002). |

## Low Traffic: Synthetic Canary

There's only one real user, so there isn't enough traffic for error-rate alerts to work. The fix is a canary check that runs every minute as the **canary user**: it logs in, creates an entry, reads it back and deletes it. Alerts fire on canary failures, which gives steady, realistic traffic on the key journey.

## On-Call Failure Scenarios

Build a **chaos switch** (environment variables that inject errors or latency) from day one so incidents can be staged.

1. **Bad deploy** (demo this first): a release where the parser throws on some input. The save error rate spikes and the alert fires. The agent links the errors to the new release and **rolls back**.
2. **Broken feature flag:** a flagged feature (e.g. the monthly review) fails. The agent sees that errors only happen with the flag on and **turns it off**.
3. **DB connection pool exhausted:** pool size set too low, so latency climbs. The agent **raises the config value and redeploys**.

## Hosting Cost

Fly.io list prices for Ashburn (`iad`), Oct 2026. Compute is billed per second while a Machine runs.

| Item | Size | Runs | ~Per month |
|------|------|------|-----------|
| Prod app | shared-cpu-1x, 512MB | Always (the canary hits it every minute) | $3.69 |
| Prod Postgres | shared-cpu-1x, 256MB + 1GB volume | Always | $2.34 |
| Dev app | shared-cpu-1x, 512MB | Auto-stops when idle | ~$1 |
| Dev Postgres | shared-cpu-1x, 256MB + 1GB volume | Stopped when not in use | ~$1 |
| **Total** | | | **~$8** |

Shared IPv4 is free, and egress at this traffic level is pennies. Managed Postgres was ruled out because its smallest plan (Basic) is $38/month **per cluster**, which comes to about $80/month for two environments.

## Open Decisions

None. All decisions to date are recorded above, in `CONTEXT.md` and in `docs/adr/`.
