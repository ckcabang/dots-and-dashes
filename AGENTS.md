# Dots & Dashes

A personal, keyboard-first bullet journal web app: rapid logging into Daily, Monthly and Future Logs, the Migration rituals, and a phone Inbox for Captures. It is also a course final project, so it runs like a production system: deployed to Fly.io, observable in Grafana, alerting on user impact, with an On-call agent. Python 3.12, FastAPI, Jinja + HTMX, SQLAlchemy, Postgres. Commands are in `README.md` and the `Makefile`; `make check` is the gate CI runs on every PR.

## Read before working

- **`CONTEXT.md`**: the glossary. Name issues, tests and code with its terms.
- **`docs/adr/`**: decisions already made. Read the ones touching your area; say so explicitly when your work contradicts one.
- **`docs/architecture/README.md`**: modules, the three test seams, and where the system runs. Read before changing code.

## Reach for when it applies

- **`docs/process/agent-team.md`**: the handoffs between the Spec, Builder, Reviewer and On-call agents and the human. Read when taking or handing off an issue or PR.
- **`.claude/agents/`**: the four agent definitions.
- **`docs/runbooks/README.md`**: incident scenarios and their remedies. Read when an alert fires or you stage an incident with the chaos switch.
- **`_docs/plan.md`**: the full project plan and course criteria.

## Agent skills

- **Issue tracker**: GitHub Issues on `ckcabang/dots-and-dashes`, through the `gh` CLI. See `docs/agents/issue-tracker.md`.
- **Triage labels**: the five defaults as-is (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.
- **Domain docs**: single-context, one `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
