# The agent team

Work moves through GitHub Issues and PRs. Each handoff is a label, a PR or a review on the tracker, so the tracker always shows who holds the work. The agents are defined in `.claude/agents/`; label names are in `docs/agents/triage-labels.md`, `gh` commands in `docs/agents/issue-tracker.md`.

| Who | Picks up | Does | Hands off by |
|---|---|---|---|
| **Spec** (`spec`) | An idea from the human | Grills it into a spec issue, then splits the spec into tickets with acceptance criteria | Labelling each ticket `ready-for-agent` (or `ready-for-human` when it needs a person) |
| **Builder** (`builder`) | A `ready-for-agent` ticket with no open blocker | Claims it, works TDD on branch `<n>-<slug>`, gets `make check` green | Opening a PR whose body starts `Closes #<n>` |
| **Reviewer** (`reviewer`) | An open Builder PR | Reviews it against the ticket's acceptance criteria and the repo's standards | Posting a review comment whose first line is `Verdict: ready to merge` or `Verdict: changes requested`; on `ready to merge`, ticking the met criteria on the issue |
| **Human** | A PR with a verdict | Merges, or sends it back to the Builder | Merging to `main`, which deploys to dev; triggering the prod deploy by hand |
| **On-call** (`on-call`) | A Grafana alert | Diagnoses from telemetry and applies one of three remedies (`docs/runbooks/README.md`) | Filing an incident issue; `ready-for-human` when the alert has not cleared |

## The loop

1. **Spec**: idea → spec issue → tickets. Tickets are sub-issues of the spec, with blockers as native issue dependencies, so "ready" means labelled `ready-for-agent` and every blocker closed.
2. **Build**: the Builder claims the ticket by assigning itself, which takes it off the frontier for other Builders. One ticket, one branch, one PR.
3. **Review**: the Reviewer posts its verdict on the PR. The verdict lists every acceptance criterion as a checkbox, ticked with where the diff meets it or left unticked with a note on why, and names the command it ran (at least `make check`) and its result. Any criterion not met makes the verdict `changes requested`; the Builder pushes fixes to the same branch and the Reviewer reviews again. On `ready to merge`, the Reviewer ticks those boxes on the issue body and links the verdict in an issue comment, so the closed issue shows each criterion checked.
4. **Merge and deploy**: only the human merges PRs and triggers prod deploys. A merge to `main` deploys to dev automatically; prod is a manual `workflow_dispatch` with an image tag, and rollback redeploys an earlier tag.
5. **Operate**: an alert wakes the On-call agent in GitHub Actions (ADR-0002). Its incident issue is the record; follow-up work goes back through Spec or straight to a `ready-for-agent` ticket.

## Parallel Builders

Several Builders can run at once, each in its own git worktree. `make test` gives every checkout its own Compose test stack, so suites never collide; run `make test-down` when done. A large spec can use an integration branch named `<spec#>-<slug>`: tickets branch from and merge into it, and it reaches `main` through one PR the human merges.
