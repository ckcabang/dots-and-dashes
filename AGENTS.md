# Dots & Dashes

A personal, keyboard-first bullet journal web app: rapid logging into Daily, Monthly and Future Logs, the Migration rituals, and a phone Inbox for Captures. It is also a course final project, so it runs like a production system: deployed to Fly.io, observable in Grafana, alerting on user impact, with an On-call agent. Python 3.12, FastAPI, Jinja + HTMX, SQLAlchemy, Postgres. Commands are in `README.md` and the `Makefile`; `make check` is the gate CI runs on every PR.

## Read before working

- **`CONTEXT.md`**: the glossary. Name issues, tests and code with its terms.
- **`docs/adr/`**: decisions already made. Read the ones touching your area; say so explicitly when your work contradicts one.
- **`docs/architecture/README.md`**: modules, the three test seams, and where the system runs. Read before changing code.

## Reach for when it applies

- **`docs/process/implementing.md`**: building a ticket on a branch or in a worktree: migrations, merging the base, the checks. Read before you start.
- **`CODING_STANDARDS.md`**: the judgement-call rules a review enforces, chiefly where bullet-journal rules live. Read when reviewing, or when unsure where a rule goes.
- **`docs/process/agent-team.md`**: the handoffs between the Spec, Builder, Reviewer and On-call agents and the human. Read when taking or handing off an issue or PR.
- **`.claude/agents/`**: the four agent definitions.
- **`docs/runbooks/README.md`**: incident scenarios and their remedies. Read when an alert fires or you stage an incident with the chaos switch.
- **`_docs/plan.md`**: the full project plan and course criteria.

## Running commands

Run `make check`, `make test`, `make test-integration`, `make test-browser`, `make test-logs`, `make test-down` and the `docker compose` lifecycle commands (`up`, `down`, `ps`, `logs`, `build`, `stop`, `restart`) as standalone commands: no `cd`, no `&&`/`;` chaining, no env-var prefix, no pipes or redirects. Only these exact forms match the sandbox exclusions in `.claude/settings.json`, so only they can reach Docker without a permission prompt. `make test T=…` and `docker compose exec`/`run` are not excluded: they run sandboxed, cannot reach Docker, and asking to retry them unsandboxed prompts the human. To run part of the suite, use `make test-unit` (no Docker, runs sandboxed), `make test-integration` or `make test-browser`; `make lint` and `make typecheck` also run sandboxed.

## Agent skills

- **Issue tracker**: GitHub Issues on `ckcabang/dots-and-dashes`, through the `gh` CLI, reading with `--json` (plain `gh issue view` fails). See `docs/agents/issue-tracker.md`.
- **Triage labels**: the five defaults as-is (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.
- **Domain docs**: single-context, one `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
