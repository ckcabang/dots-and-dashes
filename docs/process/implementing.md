# Implementing a ticket

How a Builder (or any implementer agent) builds one ticket on its own branch, often in a worktree beside other implementers. The handoffs around this are in `agent-team.md`.

1. **Start from the right base.** Branch `<ticket#>-<slug>` from the integration branch the orchestrator names (or `main`). In a worktree, confirm `HEAD` is that branch's tip before you write anything.
2. **Build test-first** with the `tdd` skill, through the three seams in `docs/architecture/README.md`. Every bullet-journal decision goes in `journal.py`; `CODING_STANDARDS.md` lists the rules the review enforces.
3. **Migrations.** Name the file and revision id `<ticket#>_<slug>`, zero-padded (`0016_migration_chain`). Set `down_revision` to the current head. `make lint` fails while there's more than one head: re-point your `down_revision` at the other head, and `make test-down` before re-testing, because a test volume keeps the old revision.
4. **Protected files.** `Makefile`, `Dockerfile`, `docker-compose*.yml` and `.env` are write-protected for agents. Put each change one of them needs in your report and the PR body, as an exact snippet for the human to apply.
5. **Commit** in small steps with plain messages. Stage the files you changed by name: the main checkout can hold the human's uncommitted edits.
6. **Merge the base's current tip into your branch** before reporting. In a worktree use `scripts/sync-worktree <base>`: the sandbox masks `.claude/` files there, which breaks a plain `git merge` whenever the base changed them.
7. **Check:** `make check`, then `make test-down`. Done when it's green, or the only failure also fails on the base and you say so.

Leave pushing, PRs and closing issues to whoever asked for the build, unless they asked you to.
