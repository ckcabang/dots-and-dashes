# The on-call agent runs in GitHub Actions with a fixed set of remedies

A Grafana alert sends a webhook that triggers a GitHub `repository_dispatch` event, which starts a workflow that runs Claude Code. The agent reads telemetry through Grafana's HTTP APIs and may apply only three remedies:

- roll back to the previous image
- turn off a feature flag
- raise the DB pool size and redeploy

It records what it did in a GitHub incident issue. We chose this over a long-running agent service on the hosting provider for three reasons: there is nothing extra to host or keep alive, the run logs are public evidence for the course reviewers, and the deploy credentials it uses are the same scoped secrets CD already holds. The trade-off is a cold start of roughly a minute or more per incident, which is acceptable for a single-user app. Any remedy beyond the three needs a human.
