# Runbooks

Contents:

- [Alert: Save failures](#alert-save-failures)
- [Alert: Save latency](#alert-save-latency)
- [Alert: Canary failing](#alert-canary-failing)
- [The On-call agent](#the-on-call-agent): how an alert wakes it, its tokens and the tools it may use
- [Staging an incident](#staging-an-incident)
- [Bad deploy → roll back](#bad-deploy--roll-back)
- [Broken feature flag → turn it off](#broken-feature-flag--turn-it-off)
- [DB connection pool exhausted → raise the pool size and redeploy](#db-connection-pool-exhausted--raise-the-pool-size-and-redeploy)
- [Running costs](#running-costs): free-tier usage, the Fly bill, pausing the canaries and shutting down after grading

Three alerts guard the key journey (log an Entry on today's Daily Log). Their rules are `monitoring/alert-rules.json` and their panels are on the **Dots & Dashes: key journey** dashboard (`monitoring/dashboard.json`); `scripts/provision-canary` imports both into Grafana Cloud.

- **Save failures**: Entry save failure rate above 5% over 10 minutes.
- **Save latency**: p95 Entry save latency above 1s, over 10 minutes.
- **Canary failing**: the canary passed under 80% of its runs: over 5 minutes on prod (it runs every minute), or 35 minutes on dev (every 15 minutes). On prod, a canary that stops reporting fires too.

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

- **Means**: a Synthetic Monitoring check running `monitoring/canary.js` passed under 80% of its runs in the window. On prod that is 2 or more failures in the last 5 runs; on dev, any failure among its 2 or 3. The checks are `dots-and-dashes-canary-prod`, which runs every minute and is read over 5 minutes, and `dots-and-dashes-canary-dev`, which runs every 15 minutes and is read over 35 minutes, so that window always holds two runs or more. On prod, a check that stops reporting fires too. On dev, no data resolves, so a paused dev check doesn't fire for good. Otherwise the two rules differ only in their `job`. The check logs in as its environment's Canary User and expects 303, saves an Entry (201), reads it back (200) and deletes it (204). A lost login answers 401, which the save metrics count as refused, so this is the only alert that sees it.
- **First look**: the check's logs in Synthetic Monitoring name the step and status that failed. A failed save also shows on the save alerts. A 401 on the save, or a log in that isn't 303, means the Canary User's login broke: its password must match its Synthetic Monitoring secret, `canary-password` on prod or `canary-password-dev` on dev (`scripts/provision-canary`). On dev, a run that times out may just be a cold start, since dev stops when idle. The check's timeout is 120s to cover one. The probe can't know the image, so the rule joins its pass rate with the images the app's save metrics carried over the same window. That gives one notification per image serving the environment, or one naming no image when the app saved nothing (the app is down).
- **Budget**: at one probe location the two checks use about 46k of the free tier's 100k test executions a month (prod every minute, about 43,200; dev every 15 minutes, about 2,900). Each extra probe location multiplies that, so keep one.

## The On-call agent

When an alert fires, the On-call agent (`.claude/agents/on-call.md`) wakes in GitHub Actions, diagnoses from telemetry and applies only the three remedies below (ADR-0002). Anything else goes to the human through an incident issue labelled `ready-for-human`. `scripts/provision-oncall` sets up everything in this section and prints the evidence, read back from each service.

**The bridge: a custom payload on the contact point.** GitHub's `repository_dispatch` API takes `{"event_type", "client_payload"}` and a token; Grafana's webhook sends its own shape. So the Grafana contact point `dots-and-dashes-on-call` is a webhook whose custom payload, `monitoring/on-call-payload.tmpl`, rewrites each notification into that body, and it POSTs it straight to `https://api.github.com/repos/ckcabang/dots-and-dashes/dispatches`. Nothing else is hosted. The event type is `grafana-alert`, which starts `.github/workflows/on-call.yml`; `client_payload` holds the notification's status, labels, annotations (`environment`, `image`, `dashboard_url`, `runbook_url`) and each alert.

- **The trigger's GitHub token**, `dots-and-dashes-on-call-dispatch`, is a fine-grained personal access token for this repository only, with **Contents: read and write**, the least that can send `repository_dispatch`. It is stored only on the contact point, as its `Authorization` header's credentials (`authorization_scheme` Bearer), a secure field Grafana never shows again. It can also push code, so give it an expiry and rotate it by re-running the wizard.
- **The route**: a notification policy sends every alert in folder **Dots & Dashes** (`grafana_folder="Dots & Dashes"`, uid `dots-and-dashes`) to the contact point, grouped by `alertname` and `env`.
- **Test notification**: the contact point's **Test** sends Grafana's `TestAlert`. It starts an On-call run that wakes no agent and says so in its summary: the proof the bridge works.

**What the workflow gives the agent.** Its `GITHUB_TOKEN` has `contents: read` and `issues: write` and nothing else. Claude Code runs with the agent definition as its only agent, the built-in tools `Read`, `Grep`, `Glob` and `Bash` only, and `--permission-mode dontAsk`, so a command outside these allow rules is refused, never asked about:

| Allowed | For |
|---|---|
| `Read`, `Grep`, `Glob` on `./**` | the checkout only; `/proc`, `/sys`, `/dev`, `/etc`, `/tmp`, `/root` and the runner's temp dir are denied outright |
| `scripts/on-call/grafana <api path>` | GET-only reads of Grafana's HTTP API with the Viewer token: alert rules and states, and Prometheus, Loki and Tempo through the data source proxy. It follows no redirect, so the token goes to Grafana only |
| `scripts/on-call/fly releases\|status\|secrets\|logs <dev\|prod>` | Fly's release history (with images), Machines, secret names and recent logs |
| `scripts/on-call/remedy rollback\|flag-off\|raise-pool …` | the three remedies, and nothing else: each checks its arguments and refuses anything outside the remedy |
| `scripts/on-call/incident open\|view\|create\|comment …` | the incident issues: listing the open ones, reading one, filing one, adding findings. Title and body are text arguments only, labelled `incident` (and `ready-for-human`) |
| `sleep` | waiting between checks that the signal recovered |

The agent may run no raw `gh`. The repo's own Claude settings, hooks and MCP servers don't apply (`--bare --setting-sources user --strict-mcp-config`). Each run keeps the agent's transcript as an artifact.

**Keeping the tokens out of public issues.** The agent reads text anyone can write, such as request paths in Fly's logs and in traces. So no token is ever where the agent could put it in an argument or a file it posts. The defences come in three layers:

1. **No token in the agent's environment.** Its shell could expand any variable there into an argument, so none is a token. An earlier step writes each token to a 0600 file in `$RUNNER_TEMP/on-call-tokens`; the agent gets only that directory's path (`ON_CALL_TOKENS`). The agent's file tools are denied the runner's temp dir and `/proc`. Each script reads only the token it needs (`scripts/on-call/on_call_lib.py`) and passes its child process that one token and no other: `flyctl` gets that environment's deploy token, and `gh` in `scripts/on-call/incident` gets the GitHub token. Claude Code reads its own API key through an `apiKeyHelper` that `cat`s its file. `claude --help` (2.1.311) says `--bare` takes the key from `ANTHROPIC_API_KEY` or an `apiKeyHelper` given with `--settings`, so the key is never in the environment its Bash commands inherit. A final step deletes the files however the run ends.
2. **The incident script refuses a token.** It takes no `--body-file`, `-F` or `--repo`. It refuses a title or body holding any token it can see (from its environment or the token files) or any 8-character run of one. It also refuses anything shaped like an Anthropic (`sk-ant-`), Fly (`FlyV1 `, `fm2_`), GitHub (`ghs_`, `github_pat_`, …) or Grafana (`glsa_`) token.
3. **Nothing is echoed back.** The scripts never repeat an argument in their errors. `scripts/on-call/grafana` redacts any token in Grafana's answer and follows no redirect. They fail with the error's type rather than a traceback. The checkout keeps no token in `.git/config` (`persist-credentials: false`).

**Secrets and variables** the workflow reads, all set by `scripts/provision-oncall`:

- `ANTHROPIC_API_KEY` (secret): the Claude API key Claude Code runs with, read through `apiKeyHelper` from its token file.
- `GRAFANA_URL` (variable): the Grafana Cloud stack's URL.
- `GRAFANA_VIEWER_TOKEN` (secret): a token of the Viewer-role service account `dots-and-dashes-agents`. Grafana answers it 200 to a read and 403 to any write. The wizard also writes it, with `GRAFANA_URL`, to the gitignored `.env`, where `scripts/on-call/grafana` finds it, so a local agent (a Reviewer checking rules, Synthetic Monitoring checks or alert states) reads Grafana without asking the human for screenshots.
- `FLY_API_TOKEN` and `FLY_PROD_API_TOKEN` (secrets): CD's deploy tokens, scoped to `dots-and-dashes-dev` and `dots-and-dashes` ([deploy.md](deploy.md#secrets-it-needs)). A deploy token can deploy its app and set its secrets, which is all the remedies do; `scripts/on-call/remedy` hands each command only its own environment's token.

**Diagnosing locally**: with `.env` filled by the wizard, the same read tools work from a checkout, e.g. `scripts/on-call/grafana 'api/prometheus/grafana/api/v1/rules'`. The Fly ones use your own `flyctl` login.

Stage each scenario on dev as its section below says. The incident issues the agent files are the evidence it works.

## Staging an incident

Set these as Fly secrets on dev (`fly secrets set -a dots-and-dashes-dev NAME=value`, which restarts the app) and unset them to end the incident. Unset, the app behaves exactly as without them.

Dev's canary saves only once every 15 minutes, too rarely to fire dev's save alerts in good time. Drive more saves with the canary script as dev's Canary User (`scripts/provision-canary` creates it), from a file holding `canary-password-dev=<its password>`:

```sh
k6 run -i 50 --secret-source=file=canary.secrets -e CANARY_ENV=dev monitoring/canary.js
```

The 10-minute windows keep the saves counted for 10 minutes after the run.

- **`CHAOS_SAVE_ERROR_RATE`**: the share of Entry saves to fail, from 0 to 1. The failures are spread evenly, not drawn at random: `0.25` fails exactly every fourth save on each Machine. The failure alert fires above 5%, so stage it with more than `0.05`. A failed save answers 500, counts as `outcome="failed"`, and its span and `Entry save failed` log carry `error.type="dots_and_dashes.chaos.InjectedSaveFailure"`.
- **`CHAOS_SAVE_LATENCY_MS`**: milliseconds to slow every Entry save by, while it holds its database connection. It shows in `entry.save.duration` and as the time between the save's checkout and its first statement.
- **`DB_POOL_SIZE`**: the most database connections each Machine holds. Unset, SQLAlchemy's default applies: 5, plus 10 overflow. Set, it is the hard limit, with no overflow, so `DB_POOL_SIZE=1` with `CHAOS_SAVE_LATENCY_MS=600` and a few saves at once exhausts the pool.
- **`CHAOS_SAVE_ERROR_FLAG`**: a feature flag, such as `FLAG_MONTHLY_REVIEW`, to tie `CHAOS_SAVE_ERROR_RATE` to: set, saves fail only while that flag is on, the way a broken flagged feature would. Any other value stops the app starting.

Every wait for a pooled connection is a `db.connection.checkout` span under the request's span. It carries `db.client.connection.max`, the most connections the app may hold, and `db.client.connection.used`, how many it held when the checkout began.

## Bad deploy → roll back

- **Signs**: save failures start right after a release, on the image the alert names; `scripts/on-call/fly releases <env>` shows that image arriving at the release before the failures began, and the errors' traces point at code that changed in it.
- **Remedy**: deploy the image of the release before it. The agent runs `scripts/on-call/remedy rollback <env> --from <the alert's image>`: it reads the release history, refuses unless the app still runs that image (so a second run never rolls forward onto the bad one), skips failed releases and ones of the same image (a secrets change), and deploys the one before with `flyctl deploy --image`. A human can do the same on prod with **Deploy to prod** and the version before the bad one ([deploy.md](deploy.md#roll-back)). A rollback restores the image only: Fly secrets stay as they are, so a bad secret or flag is not undone by it.
- **Cleared when**: the failure rate falls back under the threshold.
- **Stage it on dev** with a broken build, not a chaos secret: a secret would survive the rollback. Build one on a branch, never merged, and deploy it with `deploy-dev.yml`'s `ref` input, which builds that branch with main's copy of the workflow. Prod can never get it: Deploy to prod refuses a commit that isn't on `main`.

  ```sh
  git switch -c stage/bad-deploy origin/main
  # Every Entry save now violates the NOT NULL on entries.position.
  sed -i 's/user_id=_user_id(session), position=0)/user_id=_user_id(session), position=None)/' src/dots_and_dashes/persistence.py
  git commit -am "Stage a bad deploy on dev (never merge)"
  git push origin stage/bad-deploy
  gh workflow run deploy-dev.yml -f ref=stage/bad-deploy
  ```

  Once the run has deployed it, drive saves with k6 (above). Every save answers 500 with `error.type="sqlalchemy.exc.IntegrityError"`, and **Save failures (dev)** fires naming the bad image. The agent rolls dev back with `scripts/on-call/remedy rollback dev --from registry.fly.io/dots-and-dashes-dev:<the bad commit>`. Afterwards delete the branch (`git push origin --delete stage/bad-deploy`); the next merge to `main` deploys `main` as usual.

## Broken feature flag → turn it off

- **Signs**: errors only come with the flag on (for example `FLAG_MONTHLY_REVIEW`): they begin at a release that changed secrets but not the image (`scripts/on-call/fly releases <env>` shows the same image as before it), and `scripts/on-call/fly secrets <env>` lists the flag.
- **Remedy**: set the flag off as a Fly secret, which restarts the app. The agent runs `scripts/on-call/remedy flag-off <env> FLAG_MONTHLY_REVIEW`; it refuses any name that isn't one of the app's feature flags (`FLAGS` in `settings.py`). With a flag off the app behaves exactly as before the flag (`CODING_STANDARDS.md`), so this is always safe.
- **Cleared when**: the flagged requests' errors stop.
- **Stage it on dev** with the chaos switch tied to the flag, so the failures come only with the flag on and turning the flag off clears them while the chaos secrets stay:

  ```sh
  flyctl secrets set -a dots-and-dashes-dev FLAG_MONTHLY_REVIEW=off
  flyctl secrets set -a dots-and-dashes-dev CHAOS_SAVE_ERROR_RATE=0.5 CHAOS_SAVE_ERROR_FLAG=FLAG_MONTHLY_REVIEW
  # Saves still succeed. Now the release that turns the flag on starts the failures:
  flyctl secrets set -a dots-and-dashes-dev FLAG_MONTHLY_REVIEW=on
  ```

  Drive saves with k6: half fail, and **Save failures (dev)** fires. The agent runs `scripts/on-call/remedy flag-off dev FLAG_MONTHLY_REVIEW`. Afterwards end it: `flyctl secrets unset -a dots-and-dashes-dev CHAOS_SAVE_ERROR_RATE CHAOS_SAVE_ERROR_FLAG`, then `flyctl secrets set -a dots-and-dashes-dev FLAG_MONTHLY_REVIEW=on` to put the flag back.

## DB connection pool exhausted → raise the pool size and redeploy

- **Signs**: save latency climbs while the database itself is healthy. In a slow save's trace, the time goes to a long `db.connection.checkout` span whose `db.client.connection.used` equals its `db.client.connection.max`: every connection was in use, so the save waited for one. The statements after it are fast. A checkout that waits out the pool's 30s timeout fails with `error.type="sqlalchemy.exc.TimeoutError"`.
- **Remedy**: set `DB_POOL_SIZE` as a Fly secret, above the `db.client.connection.max` on the long checkout span, and redeploy. Unset, that maximum is already 15 (5 plus 10 overflow), so a smaller `DB_POOL_SIZE` lowers the limit and makes the exhaustion worse. Keep `DB_POOL_SIZE` times the number of Machines under Postgres's `max_connections` (100 by default), less a few for migrations and `psql`. The agent runs `scripts/on-call/remedy raise-pool <env> <size> --above <db.client.connection.max>`: it refuses a size that isn't above that maximum, or is over 40. It also checks Fly's own secrets listing rather than trusting `--above`: with `DB_POOL_SIZE` unset it refuses anything up to 15, and with it set, anything up to the default pool's 5. Setting the secret makes a new release, so Fly redeploys every Machine with the new size.
- **Cleared when**: p95 save latency falls back under 1s.
- **Stage it on dev** with one connection and slow saves. Each save is held 600ms, under the 1s threshold on its own, so only the queue for the one connection pushes p95 over:

  ```sh
  flyctl secrets set -a dots-and-dashes-dev DB_POOL_SIZE=1 CHAOS_SAVE_LATENCY_MS=600
  k6 run --vus 5 -i 100 --secret-source=file=canary.secrets -e CANARY_ENV=dev monitoring/canary.js
  ```

  **Save latency (dev)** fires, and a slow save's trace shows a long checkout with `db.client.connection.used` = `db.client.connection.max` = 1. The agent runs `scripts/on-call/remedy raise-pool dev 10 --above 1`; with ten connections each save takes about 600ms and p95 falls under 1s. Afterwards: `flyctl secrets unset -a dots-and-dashes-dev DB_POOL_SIZE CHAOS_SAVE_LATENCY_MS`.

## Running costs

The project runs on Grafana Cloud's free tier and about $8 a month of Fly.io. Neither needs watching day to day, but the canaries are what use both up, so this is where to check and what to switch off.

### Grafana Cloud free tier

| Allowance | Free tier | This project uses |
|-----------|-----------|-------------------|
| Synthetic Monitoring API and scripted test executions | 100,000 a month (browser checks: 10,000, unused) | About 46,000 at one probe location: the [canary budget](#alert-canary-failing) |
| Metrics | 10,000 active series | About 200, exported once a minute (the OpenTelemetry default) |
| Logs | 50 GB | Well under |
| Traces | 50 GB | Well under |
| Retention | 14 days | Everything older is deleted |

Check usage in your Grafana Cloud stack's **Cost Management and Billing** app, on its **Usage** tab: it shows each product's usage, Synthetic Monitoring's in test executions. The executions are the only allowance near its limit, and each extra probe location on a check multiplies them.

**Screenshot the evidence on the day.** Grafana deletes data after 14 days, so the incidents, firing alerts and dashboards a grader should see won't be there later. When you stage an incident or an alert fires, screenshot the dashboard, the alert in **Alerting → Alert rules**, the trace and log that explain it, and link the incident issue the On-call agent filed.

### Fly cost

Fly list prices for Ashburn (`iad`), from [`_docs/plan.md`](../../_docs/plan.md#hosting-cost) (October 2026), billed per second while a Machine runs. Postgres runs on our own Machines rather than Fly Managed Postgres to keep this low ([ADR-0003](../adr/0003-self-run-postgres-on-fly.md)).

| Machine | Size | Always on? | ~Per month |
|---------|------|------------|-----------|
| `dots-and-dashes` (prod app) | shared-cpu-1x, 512MB | Yes, by design: the prod canary saves every minute | $3.69 |
| `dots-and-dashes-db` (prod Postgres) | shared-cpu-1x, 256MB + 1GB volume | Yes, by design, alongside the prod app | $2.34 |
| `dots-and-dashes-dev` (dev app) | shared-cpu-1x, 512MB | No: auto-stops when idle | ~$1 |
| `dots-and-dashes-dev-db` (dev Postgres) | shared-cpu-1x, 256MB + 1GB volume | No: stops once the dev app has | ~$1 |
| **Total** | | | **~$8** |

**What the dev canary does to that.** The ~$1 for each dev Machine assumes dev is mostly stopped. The dev canary runs every 15 minutes, so it wakes the dev app, and through it dev's Postgres, about 96 times a day, and each Machine then stays up until Fly sees it idle and stops it. Dev therefore runs much more than "mostly stopped". The worst case is dev always on, priced like prod: $3.69 + $2.34 for dev, so about **$12 a month** in all.

**Pausing the dev canary saves Fly money too.** With no check waking it, dev sleeps, and its two Machines cost close to their volume and stopped root file system only. It also saves about 2,900 Synthetic Monitoring executions a month.

**The bill.** See it on the Fly dashboard's **Billing** page, per organization; each invoice breaks down the charges. Spend controls, checked against Fly's [billing](https://docs.fly.io/about/billing) and [pricing](https://docs.fly.io/about/pricing) docs on 2026-10-26: Fly offers prepaid credits, bought on the Billing page (from $25), with usage taken off the balance each month. Those docs mention no spending limit, budget cap or billing alert, so treat any such control as unconfirmed and check the Billing page. Fly says it will discuss a refund for resources created by mistake (billing@fly.io).

Stopped Machines aren't free: Fly charges about $0.15 per GB a month for each volume, attached or not, and for a stopped Machine's root file system (approximate, from Fly's pricing page). That's cents a month here.

### Pause and resume the dev canary

Pause it whenever you aren't staging an incident on dev. Dev's canary rule treats no data as OK, so a paused dev check never fires.

1. In Grafana Cloud, open **Testing & synthetics → Synthetics → Checks**.
2. Open `dots-and-dashes-canary-dev`, then **Edit**.
3. Turn the check's **Enabled** switch off and **Save**. Its card in the check list shows it as disabled.
4. Within a few idle minutes `flyctl status -a dots-and-dashes-dev` shows the dev Machine `stopped`, and soon after `flyctl status -a dots-and-dashes-dev-db` shows dev's Postgres stopped too.

To resume it, before staging an incident, do the same and turn **Enabled** back on. The next run wakes dev, and may time out once on the cold start.

The field names follow the Synthetic Monitoring app as `scripts/provision-canary` describes it; the form's layout may differ.

### Shut down after grading

Once grading is done, stop prod and its database. The journal's data stays on the database's `pgdata` volume, which is kept (and billed at about $0.15 a month), so everything comes back as it was.

1. **Pause both canary checks first**, `dots-and-dashes-canary-prod` and `dots-and-dashes-canary-dev`, as [above](#pause-and-resume-the-dev-canary). Otherwise the prod canary fails against a stopped app and pages you.
2. **Pause the `Canary failing (prod)` alert rule.** Prod's canary rule treats no data as alerting, so a paused prod check fires it on its own. In **Alerting → Alert rules**, find it in the **Dots & Dashes** folder and choose **Pause evaluation**.
3. Note the version prod runs, to bring the same one back:

   ```sh
   flyctl releases -a dots-and-dashes --image
   ```

4. Stop the prod app, then its database. `scale count 0` removes the app's Machines; it has no volume, so nothing is lost. `machine stop` asks which Machine to stop: there is one.

   ```sh
   flyctl scale count 0 -a dots-and-dashes
   flyctl machine stop -a dots-and-dashes-db
   ```

5. Check both: `flyctl status -a dots-and-dashes` lists no Machines, and `flyctl status -a dots-and-dashes-db` shows the database `stopped`.

To start up again, in reverse order:

1. Start the database:

   ```sh
   flyctl machine start -a dots-and-dashes-db
   ```

2. Bring the app back. `flyctl scale count 1 -a dots-and-dashes` alone can't do it from zero, because Fly's [scale-count docs](https://docs.fly.io/launch/scale-count) say scaling clones an existing Machine. Redeploy instead: run **Deploy to prod** with the version you noted before shutting down ([deploy.md](deploy.md#deploy)). A deploy onto no Machines may create two for high availability, so then scale back to the one prod runs:

   ```sh
   flyctl scale count 1 -a dots-and-dashes
   ```

3. Check it: `https://dots-and-dashes.fly.dev/login` loads and logging an Entry works.
4. Resume the `dots-and-dashes-canary-prod` check, and once its first run has passed, the `Canary failing (prod)` rule (**Resume evaluation**), so the rule never reads a window with no data. Resume the dev check only if you're staging an incident.
