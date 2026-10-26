# Runbooks

Two alerts guard the key journey (log an Entry on today's Daily Log):

- **Save failures**: Entry save failure rate above 5% over 10 minutes.
- **Save latency**: p95 Entry save latency above 1s.

Both read prod's save metrics, as Grafana Cloud's Prometheus names them. Every series carries `job="<environment>/dots-and-dashes"`, because the app sets `service.namespace` to its `DEPLOYMENT_ENVIRONMENT`. Selecting `job="prod/dots-and-dashes"` therefore keeps incidents staged on dev from firing prod's alerts. Refused saves, such as blank text, are the User's doing and count as neither success nor failure:

```promql
# Save failure rate, prod
sum(rate(entry_saves_total{job="prod/dots-and-dashes", outcome="failed"}[10m]))
  / sum(rate(entry_saves_total{job="prod/dots-and-dashes", outcome=~"saved|failed"}[10m]))
# p95 save latency in seconds, prod
histogram_quantile(0.95, sum by (le) (rate(entry_save_duration_seconds_bucket{job="prod/dots-and-dashes", outcome=~"saved|failed"}[10m])))
```

To watch a staged incident on dev, run the same queries with `job="dev/dots-and-dashes"`. A failed save's span and its `Entry save failed` log share a trace ID and carry `error.type`; the latency histogram's exemplars link to slow traces.

The On-call agent (`.claude/agents/on-call.md`) applies only the three remedies below (ADR-0002). Anything else goes to the human through an incident issue labelled `ready-for-human`.

Stage each scenario on dev with the chaos switch or the flag and pool settings below. The incident issues the agent files are the evidence it works.

## Staging an incident

Set these as Fly secrets on dev (`fly secrets set -a dots-and-dashes-dev NAME=value`, which restarts the app) and unset them to end the incident. Unset, the app behaves exactly as without them.

- **`CHAOS_SAVE_ERROR_RATE`**: the share of Entry saves to fail, from 0 to 1. The failures are spread evenly, not drawn at random: `0.25` fails exactly every fourth save on each Machine. The failure alert fires above 5%, so stage it with more than `0.05`. A failed save answers 500, counts as `outcome="failed"`, and its span and `Entry save failed` log carry `error.type="dots_and_dashes.chaos.InjectedSaveFailure"`.
- **`CHAOS_SAVE_LATENCY_MS`**: milliseconds to slow every Entry save by, while it holds its database connection. It shows in `entry.save.duration` and as the time between the save's checkout and its first statement.
- **`DB_POOL_SIZE`**: the most database connections each Machine holds. Unset, SQLAlchemy's default applies: 5, plus 10 overflow. Set, it is the hard limit, with no overflow, so `DB_POOL_SIZE=1` with `CHAOS_SAVE_LATENCY_MS=2000` and a few saves at once exhausts the pool.

Every wait for a pooled connection is a `db.connection.checkout` span under the request's span. It carries `db.client.connection.max`, the most connections the app may hold, and `db.client.connection.used`, how many it held when the checkout began.

## Bad deploy → roll back

- **Signs**: save failures start right after a release; the errors' traces point at code that changed in it.
- **Remedy**: redeploy the previous image tag: run **Deploy to prod** with the version before the bad one ([deploy.md](deploy.md#roll-back)).
- **Cleared when**: the failure rate falls back under the threshold.

## Broken feature flag → turn it off

- **Signs**: errors only come from requests with the flag on (for example `FLAG_MONTHLY_REVIEW`).
- **Remedy**: set the flag off as a Fly secret, which restarts the app.
- **Cleared when**: the flagged requests' errors stop.

## DB connection pool exhausted → raise the pool size and redeploy

- **Signs**: save latency climbs while the database itself is healthy. In a slow save's trace, the time goes to a long `db.connection.checkout` span whose `db.client.connection.used` equals its `db.client.connection.max`: every connection was in use, so the save waited for one. The statements after it are fast. A checkout that waits out the pool's 30s timeout fails with `error.type="sqlalchemy.exc.TimeoutError"`.
- **Remedy**: set `DB_POOL_SIZE` as a Fly secret, above the `db.client.connection.max` on the long checkout span, and redeploy. Unset, that maximum is already 15 (5 plus 10 overflow), so a smaller `DB_POOL_SIZE` lowers the limit and makes the exhaustion worse. Keep `DB_POOL_SIZE` times the number of Machines under Postgres's `max_connections` (100 by default), less a few for migrations and `psql`.
- **Cleared when**: p95 save latency falls back under 1s.
