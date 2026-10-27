# Runbooks

Three alerts guard the key journey (log an Entry on today's Daily Log). Their rules are `monitoring/alert-rules.json` and their panels are on the **Dots & Dashes: key journey** dashboard (`monitoring/dashboard.json`); `scripts/provision-canary` imports both into Grafana Cloud.

- **Save failures**: Entry save failure rate above 5% over 10 minutes.
- **Save latency**: p95 Entry save latency above 1s, over 10 minutes.
- **Canary failing**: the canary passed under 80% of its runs over 5 minutes, or stopped reporting.

The two save alerts read the save metrics, as Grafana Cloud's Prometheus names them. Every series carries `job="<environment>/dots-and-dashes"`, because the app sets `service.namespace` to its `DEPLOYMENT_ENVIRONMENT`, and `image`, the deployed image (`FLY_IMAGE_REF`). Each save alert has a prod rule and a dev rule that differ only in that `job` selector, so an incident staged on dev fires the dev rule and never prod's. They are counted by image, so a notification names the image whose saves fail. Refused saves, such as blank text, are the User's doing and count as neither success nor failure:

```promql
# Save failure rate, prod, by image
(sum by (image) (rate(entry_saves_total{job="prod/dots-and-dashes", outcome="failed"}[10m]))
  or sum by (image) (rate(entry_saves_total{job="prod/dots-and-dashes", outcome=~"saved|failed"}[10m])) * 0)
  / sum by (image) (rate(entry_saves_total{job="prod/dots-and-dashes", outcome=~"saved|failed"}[10m]))
# p95 save latency in seconds, prod, by image
histogram_quantile(0.95, sum by (le, image) (rate(entry_save_duration_seconds_bucket{job="prod/dots-and-dashes", outcome=~"saved|failed"}[10m])))
```

To watch a staged incident on dev, run the same queries with `job="dev/dots-and-dashes"`, or pick `dev` on the dashboard. A failed save's span and its `Entry save failed` log share a trace ID and carry `error.type`; the latency histogram's exemplars link to slow traces.

Every notification carries the environment, the image, a link to the dashboard filtered to both, the alert's panel (Grafana's own panel link) and this runbook's section for it.

## Alert: Save failures

- **Means**: more than 5% of Entry saves answered 500 over the last 10 minutes, on the image the notification names. At one canary save a minute, a single failed save is enough.
- **First look**: the dashboard's **Save failure rate** and **Saves by outcome** panels, then the failed saves' traces and `Entry save failed` logs (search Tempo for `error.type`). A new image starting to fail right after a release is a [bad deploy](#bad-deploy--roll-back); failures only from flagged requests are a [broken feature flag](#broken-feature-flag--turn-it-off).

## Alert: Save latency

- **Means**: the p95 Entry save took over 1s over the last 10 minutes.
- **First look**: an exemplar on the **p95 save latency** panel opens a slow save's trace. Time in a long `db.connection.checkout` span is an [exhausted pool](#db-connection-pool-exhausted--raise-the-pool-size-and-redeploy).

## Alert: Canary failing

- **Means**: the Synthetic Monitoring check `dots-and-dashes-canary` (the script is `monitoring/canary.js`) failed at least 2 of its last 5 runs, or stopped reporting. It logs in as the Canary User and expects 303, saves an Entry (201), reads it back (200) and deletes it (204). A lost login answers 401, which the save metrics count as refused, so this is the only alert that sees it.
- **First look**: the check's logs in Synthetic Monitoring name the step and status that failed. A failed save also shows on the save alerts; a 401 on the save, or a log in that isn't 303, means the Canary User's login broke: its password must match the `canary-password` Synthetic Monitoring secret (`scripts/provision-canary`). The image serving prod is on the dashboard's Image filter; the probe can't know it, so this notification doesn't carry it.

The On-call agent (`.claude/agents/on-call.md`) applies only the three remedies below (ADR-0002). Anything else goes to the human through an incident issue labelled `ready-for-human`.

Stage each scenario on dev with the chaos switch or the flag and pool settings below. The incident issues the agent files are the evidence it works.

## Staging an incident

Set these as Fly secrets on dev (`fly secrets set -a dots-and-dashes-dev NAME=value`, which restarts the app) and unset them to end the incident. Unset, the app behaves exactly as without them.

The canary runs on prod only, so dev's save alerts need saves to fire on. Drive some with the canary script as dev's Canary User (`scripts/provision-canary` can create one), from a file holding `canary-password=<its password>`:

```sh
k6 run -i 50 --secret-source=file=canary.secrets \
  -e BASE_URL=https://dots-and-dashes-dev.fly.dev monitoring/canary.js
```

The 10-minute windows keep the saves counted for 10 minutes after the run.

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
