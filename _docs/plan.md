# Dots & Dashes: Project Plan

A personal, keyboard-first bullet journal web app, built as the course final project.
This document captures the agreed scope. Acceptance criteria will be added later.

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

Primary: **task management**. Capture to-dos fast and keep a focused task list with bullet journal rituals (complete, migrate, schedule, drop).

Secondary:

- **Planning ahead** with monthly and future logs.
- **Light notes and reflections** about the day.

## Scope v1

### Capture

**Desktop (main app):** a single input box with prefix syntax.

| Prefix | Meaning |
|--------|---------|
| `. ` | Task (•) |
| `o ` | Event (○) |
| `- ` | Note (–) |
| `*` | Signifier: priority |
| `!` | Signifier: inspiration |

**Mobile quick-capture page:**

- A minimal, mobile-first page for jotting things down on the go.
- Entries **default to tasks** unless they start with a prefix.
- Captured items go to an **inbox**.

**Inbox triage (on desktop):** each inbox item can be moved to:

- a specific day
- a month's task list
- the future log

### Entries

- **Types:** task, event, note.
- **Task states:** open, completed (×), migrated (>), scheduled (<), cancelled (struck through).
- **Optional time** on both tasks and events. Time is never required.
- **Notes** can stand alone or be **nested under a task or event**.
- **Signifiers:** `*` priority and `!` inspiration.

### Ordering Within a Day

- Entries are **ordered manually**, but **timed entries always stay in chronological order**.
- An untimed entry placed after a timed entry means "sometime after that time, no specific time."
- Untimed entries keep their place relative to the timed entry above them.

### Logs

| Log | Description |
|-----|-------------|
| **Daily log** | Today's page: quick entry plus the ordered list of entries. |
| **Monthly log** | Calendar view of events plus the month's task list. |
| **Future log** | Organized in **month buckets**. Each item can have an optional specific date. |
| **Inbox** | Items from mobile quick capture waiting to be sorted. |

### Migration

**Daily migration**

- Can be done **the night before or each morning**.
- Can be **skipped** and done later **manually** whenever you choose.

**Monthly review (on the 1st)**

- Shows **all of last month's leftover open tasks**.
- Also shows **this month's items from the future log**, so planning happens in one ritual.

**Migration behavior**

- **Nested notes move with the task.** The original entry keeps only the `>` marker.
- Each task shows a **migration count** (e.g. `>>3`) to make procrastination visible.

### Users

- **Single user** (you), with a password login so the journal stays private when deployed publicly.
- A separate **canary user** for synthetic monitoring, so test entries never touch the real journal.

### Stretch Goals (after all 12 criteria are covered)

- Search across entries
- Habit tracker (monthly grid)
- Custom collections (e.g. "Books to read")
- Markdown export
- Offline support (PWA)

## Draft Data Model

Subject to change during spec and design.

```
users
  id, email, password_hash, is_canary

entries
  id, user_id
  type            task | event | note
  status          open | done | migrated | scheduled | cancelled   (tasks only)
  text
  signifier       none | priority | inspiration
  time            optional time of day
  location        inbox | day | month | future
  date            set for day entries; optional for future entries
  month           set for month and future entries
  position        manual sort order within its location
  parent_id       set when a note is nested under a task/event
  migrated_from_id  links a migrated task to its previous copy (used for the migration count)
  created_at, updated_at
```

## How It Maps to the Course Criteria

| Criterion | Plan |
|-----------|------|
| **Problem description** | README describes the bullet journal workflow and the features above. |
| **Product spec + tracker** | This plan becomes a spec. Features are split into issues with acceptance criteria in a public tracker (e.g. GitHub Issues/Projects). |
| **Agent team** | To be defined (e.g. spec, builder, tester, reviewer and on-call agents, plus how they hand work to each other). |
| **Context management** | AGENTS.md linking to modular docs (process, team, architecture, runbooks). |
| **Application** | Frontend + backend + Postgres, started locally with one command. |
| **Unit tests** | Prefix parser (types, signifiers, times, edge cases), ordering rules (timed vs untimed), migration rules (open tasks, month rollover, migration chains, nested notes moving). |
| **Integration tests** | Create an entry via the API, it persists, migrate it, it appears on the new day, and the original is marked `>`. Inbox triage to day/month/future. |
| **Containerization** | Docker Compose for the app and database, one command. |
| **Deployment** | Public URL (e.g. Fly.io / Render / Railway). |
| **CI/CD** | CI runs tests on each PR. CD auto-deploys to dev. Production deploy is manual, with a rollback path. |
| **Observability** | Key journey: **log an entry on today's page**. Metrics, traces and structured logs share a trace ID. **Entry text is never sent to telemetry**: only type, length and IDs are recorded. |
| **Alerting on user impact** | E.g. entry save failure rate > 5% over 10 min, or p95 save latency > 1s. |
| **On-call agent** | Wakes on the alert, diagnoses the problem from telemetry and applies a limited fix (see below). |

## Low Traffic: Synthetic Canary

There's only one real user, so there isn't enough traffic for error-rate alerts to work. The fix is a canary job that runs every minute as the **canary user**: it logs in, creates an entry, reads it back and deletes it. Alerts fire on canary failures, which gives steady, realistic traffic on the key journey.

## On-Call Failure Scenarios

Build a **chaos switch** (an env var or feature flag that injects errors or latency) from day one so incidents can be staged.

1. **Bad deploy** (demo this first): a release where the parser throws on some input. The save error rate spikes and the alert fires. The agent links the errors to the new release and **rolls back**.
2. **Broken feature flag:** a flagged feature (e.g. the monthly review) fails. The agent sees that errors only happen with the flag on and **turns it off**.
3. **DB connection pool exhausted:** pool size set too low, so latency climbs. The agent **raises the config value and redeploys**.

## Open Decisions

- Stack (course default: Python/FastAPI + Postgres + a light frontend such as HTMX or React).
- Hosting provider and telemetry backend (e.g. Grafana stack, Honeycomb, Better Stack).
- Agent team composition and workflow.
- Whether a migrated timed task keeps its time.
