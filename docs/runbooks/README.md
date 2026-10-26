# Runbooks

Two alerts guard the key journey (log an Entry on today's Daily Log):

- **Save failures**: Entry save failure rate above 5% over 10 minutes.
- **Save latency**: p95 Entry save latency above 1s.

Both read the save metrics, as Grafana Cloud's Prometheus names them (refused saves, such as blank text, are the User's doing and count as neither):

```promql
# Save failure rate
sum(rate(entry_saves_total{outcome="failed"}[10m]))
  / sum(rate(entry_saves_total{outcome=~"saved|failed"}[10m]))
# p95 save latency, in seconds
histogram_quantile(0.95, sum by (le) (rate(entry_save_duration_seconds_bucket{outcome=~"saved|failed"}[10m])))
```

Narrow either to one environment with `deployment_environment_name` (`dev`, `prod`), when the stack promotes that resource attribute to a label, or else through `target_info`. A failed save's span and its `Entry save failed` log share a trace ID and carry `error.type`; the latency histogram's exemplars link to slow traces.

The On-call agent (`.claude/agents/on-call.md`) applies only the three remedies below (ADR-0002). Anything else goes to the human through an incident issue labelled `ready-for-human`.

Stage each scenario on dev with the chaos switch (`CHAOS_SAVE_ERROR_RATE`, `CHAOS_SAVE_LATENCY_MS`) or the flag and pool settings below. The incident issues the agent files are the evidence it works.

## Bad deploy → roll back

- **Signs**: save failures start right after a release; the errors' traces point at code that changed in it.
- **Remedy**: redeploy the previous image tag.
- **Cleared when**: the failure rate falls back under the threshold.

## Broken feature flag → turn it off

- **Signs**: errors only come from requests with the flag on (for example `FLAG_MONTHLY_REVIEW`).
- **Remedy**: set the flag off as a Fly secret, which restarts the app.
- **Cleared when**: the flagged requests' errors stop.

## DB connection pool exhausted → raise the pool size and redeploy

- **Signs**: save latency climbs while the database itself is healthy; traces show time spent waiting for a connection.
- **Remedy**: raise `DB_POOL_SIZE` as a Fly secret and redeploy.
- **Cleared when**: p95 save latency falls back under 1s.
