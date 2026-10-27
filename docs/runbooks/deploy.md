# Deploy and roll back prod

Prod, <https://dots-and-dashes.fly.dev>, changes only when the human runs **Actions → Deploy to prod** ([`deploy-prod.yml`](../../.github/workflows/deploy-prod.yml)) with a version: the commit SHA of a build of `main`. Rolling back is the same run with an earlier SHA. One-time setup is [`scripts/provision-prod`](../../scripts/provision-prod).

Prod never builds. Every merge to `main` builds `registry.fly.io/dots-and-dashes-dev:<sha>` and runs it on dev first. A prod deploy copies that image into prod's own repository, `registry.fly.io/dots-and-dashes:<sha>`, and deploys it, so prod runs the exact image dev ran. The release command, `dots-and-dashes migrate`, applies the Alembic migrations before any Machine moves to it; if it fails, prod keeps running the old version.

## Deploy

1. Pick the version: the SHA of a merge on `main` whose **Deploy to dev** run passed, and that you've checked on dev.
2. Run it, from the Actions tab (**Deploy to prod → Run workflow**, version = the SHA) or the terminal:

   ```sh
   gh workflow run deploy-prod.yml -f version=<sha>
   gh run watch "$(gh run list --workflow deploy-prod.yml --limit 1 --json databaseId --jq '.[0].databaseId')"
   ```

   A short SHA works; the workflow resolves it and refuses one that isn't on `main`.
3. Check it: the run ends by fetching `/login` (**Smoke-test prod**), its summary names the version, `flyctl releases -a dots-and-dashes --image` lists it as the newest release, and logging an Entry on <https://dots-and-dashes.fly.dev> works.

## Roll back

1. Find the version to go back to. Each run of **Deploy to prod** is titled `Deploy <sha> to prod`, so the run list is prod's history:

   ```sh
   gh run list --workflow deploy-prod.yml --status success
   ```

   `flyctl releases -a dots-and-dashes --image` shows the same from Fly's side.
2. Deploy that earlier SHA exactly as above. Its image is already in prod's repository, so the run skips the copy.
3. Check it as above, and that the alert that sent you here clears.

A rollback restores the image only. The run reads `fly.prod.toml` from `main` as it is now, and Fly secrets stay as they are, so a bad change to env, VM size, a secret or a feature flag is undone there, not by rolling back.

A rollback across a migration works as long as migrations only add to the schema: the older release's `dots-and-dashes migrate` sees the database at a revision it doesn't know, says so in the release log, and leaves the schema as it is. A migration that drops or renames something the older code reads breaks that, so split such a change across two releases (add, then remove once nothing reads the old shape). Images built before `dots-and-dashes migrate` existed fail the release command, so they can't be deployed to prod.

## Secrets it needs

The prod app's own Fly secrets are `DATABASE_URL`, `SESSION_SECRET`, `FLAG_MONTHLY_REVIEW`, and the Grafana Cloud `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_HEADERS`. All are set by `scripts/provision-prod`. A deploy and a rollback both leave them as they are.

GitHub secrets, both set by the provisioning wizards:

- `FLY_PROD_API_TOKEN`: a deploy token for `dots-and-dashes` only; it pushes to prod's repository and deploys.
- `FLY_API_TOKEN`: dev's deploy token, used only to pull dev's image.

The On-call workflow reads both too, for its remedies on each app ([the On-call agent](README.md#the-on-call-agent)). The agent's rollback deploys the previous release's image directly with `flyctl deploy --image`, rather than through this workflow.
