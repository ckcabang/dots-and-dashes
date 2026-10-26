# Coding standards

The judgement calls a reviewer enforces. Mechanical rules are checks in `make check` (`make lint`: ruff and a single Alembic head), so they aren't repeated here.

## Where rules live

- **Every bullet-journal decision is made in `journal.py`**: what a Prefix means, Anchors and Daily Log order, which Task States can change, nesting, Migrated vs Scheduled, the Day being planned, Migration Chains. Look for a decision outside it, not just a duplicate.
- **Clients send intent, never decisions.** `keyboard.js` and API callers say what the User asked for ("migrate this Task", "plan tomorrow"); the server asks the Journal what that means. A request field like `night_before` that lets the caller decide the outcome is a violation.
- **Routes are thin**: parse the request, call the Journal, persist what it returns, render. Branching on domain state in `web.py` is a rule that belongs in the Journal.
- **Persistence stores what the Journal decided.** Ordering, re-linking and un-nesting rules in `persistence.py` or the schema are violations; a foreign key may stay as a safety net under a Journal rule.
- **Flagged features stay behind their flag.** A Journal function changed for a flagged feature must not change what an unflagged route does; give the flagged path its own function. With the flag off, the app behaves exactly as before.
- **Templates render, they don't decide.** A template condition that restates a Journal rule should call a Journal predicate instead.

## Names

- **Glossary terms only**, in code, tests and test data. `CONTEXT.md` lists the term to use and the words to avoid; an avoided word as a name for the concept (`done` for Completed) is a violation, the same word in ordinary English (`aria-label`, Entry text like "draft") is not.

## CI

- **A CI change works under the workflow's own triggers**, not just in the diff. A pull request restores only caches saved by itself or its base branch, and a cancelled run saves nothing. The PR cites the run log line that shows it working ("Cache restored", the step's duration). A workflow that only runs after merge (push to `main`, `workflow_dispatch`) can't cite a run in its PR: the PR says how its first run will show it working, and that run's log line is posted on the PR after merge.

## Tests

- Through the three seams in `docs/architecture/README.md` and the public interface only. A Journal function that only tests call is dead code the route rebuilt: production should call it.
