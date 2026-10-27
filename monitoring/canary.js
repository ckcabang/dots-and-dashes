// The canary: the key journey, as the Canary User, once per run.
//
// Grafana Synthetic Monitoring runs it as two scripted (k6) checks: every
// minute against prod, and every 15 minutes against dev. That gives the save
// failure and save latency alerts traffic to fire on, with only one real User
// (docs/runbooks/README.md). CI runs it once against the Compose test stack as
// a smoke test (.github/workflows/ci.yml).
//
// It logs in, logs an Entry on today's Daily Log, reads it back and deletes it.
// Each step checks its own status code, and a failed step fails the run with
// fail(): Synthetic Monitoring runs k6 with --no-thresholds, so a failed check()
// alone would pass. A lost login answers 401, which the save metrics count as
// refused rather than failed, so only the canary's own failure (the "Canary
// failing" alert, on probe_success) shows it.
//
// The password is a Synthetic Monitoring secret, never in this file:
// canary-password for prod's Canary User, canary-password-dev for dev's.
// Locally: k6 run --secret-source=file=<file with canary-password=...>
// monitoring/canary.js, with BASE_URL to aim it elsewhere.
//
// The Entry's text is fixed and says nothing; nothing here logs a request or
// response body, and the app keeps Entry text out of its own telemetry.
//
// Synthetic Monitoring's check logs go to the stack's Loki, which the agents'
// Viewer token reads. k6 keeps the password out of them: it redacts a secret's
// value from every log line. It can't do that for the session cookie the app
// answers the log in with, and HTTP debug logging (k6's --http-debug, or
// K6_HTTP_DEBUG) logs it in every request's and response's headers, so with
// that on the canary refuses to log in and fails the run (issue #98). The
// script's own options can't turn it off: a flag or environment variable
// overrides them.

import http from 'k6/http';
import { check, fail } from 'k6';
import exec from 'k6/execution';
import secrets from 'k6/secrets';

// The check's environment: the one line that differs between the two checks.
// Synthetic Monitoring passes a check no variables, so scripts/provision-canary
// gives the dev check this script with 'prod' below changed to 'dev'.
const ENVIRONMENT = __ENV.CANARY_ENV || 'prod';

const ENVIRONMENTS = {
  prod: { url: 'https://dots-and-dashes.fly.dev', secret: 'canary-password' },
  // Dev stops when idle: its first request may wait for the app and its
  // Postgres to start, so the dev check's timeout is 120s (provision-canary).
  dev: { url: 'https://dots-and-dashes-dev.fly.dev', secret: 'canary-password-dev' },
};
const TARGET = ENVIRONMENTS[ENVIRONMENT];
if (!TARGET) {
  throw new Error(`no such environment: ${ENVIRONMENT}`);
}
const BASE_URL = (__ENV.BASE_URL || TARGET.url).replace(/\/$/, '');
const EMAIL = __ENV.CANARY_EMAIL || 'canary@dots-and-dashes.invalid';
const TEXT = 'canary check';
// Long enough for a cold start on dev; the check's own timeout bounds the run.
const REQUEST_TIMEOUT = '90s';

export const options = {
  iterations: 1,
  // Honoured by a plain k6 run (CI); Synthetic Monitoring ignores it, which
  // is why each failed step also calls fail().
  thresholds: { checks: ['rate==1.0'] },
};

// Each request is named by its route, not its URL, so an Entry ID never
// becomes a metric label.
function named(name, params = {}) {
  return { timeout: REQUEST_TIMEOUT, ...params, tags: { name } };
}

export default async function () {
  const httpDebug = exec.test.options.httpDebug;
  if (!check(httpDebug, { 'HTTP debug logging is off': (d) => !d })) {
    fail(`HTTP debug logging is on (${httpDebug}): refusing to log in, as it would log the session cookie`);
  }

  const password = await secrets.get(TARGET.secret);

  const login = http.post(
    `${BASE_URL}/login`,
    { email: EMAIL, password },
    named('POST /login', { redirects: 0 }),
  );
  if (!check(login, { 'log in answers 303': (r) => r.status === 303 })) {
    fail(`log in answered ${login.status}`);
  }

  const saved = http.post(
    `${BASE_URL}/api/entries`,
    JSON.stringify({ text: TEXT }),
    named('POST /api/entries', { headers: { 'Content-Type': 'application/json' } }),
  );
  if (!check(saved, { 'save answers 201': (r) => r.status === 201 })) {
    fail(`save answered ${saved.status}`);
  }
  const entry = saved.json();

  let readBack = `read back threw before answering`;
  try {
    const log = http.get(
      `${BASE_URL}/api/daily-logs/${entry.day}`,
      named('GET /api/daily-logs/{day}'),
    );
    const found = check(log, {
      'read back answers 200': (r) => r.status === 200,
      'read back finds the Entry': (r) =>
        r.status === 200 &&
        r.json('entries').some((e) => e.id === entry.id && e.text === TEXT),
    });
    readBack = found ? '' : `read back answered ${log.status} without the Entry`;
  } finally {
    // Deleted even when the read back fails, so the Canary User's Daily Log
    // never fills up.
    const deleted = http.del(
      `${BASE_URL}/api/entries/${entry.id}`,
      null,
      named('DELETE /api/entries/{id}'),
    );
    const gone = check(deleted, { 'delete answers 204': (r) => r.status === 204 });
    // fail() as well as the checks: the run fails whether or not the runner
    // honours the checks threshold.
    const failures = [readBack, gone ? '' : `delete answered ${deleted.status}`].filter(Boolean);
    if (failures.length) {
      fail(failures.join('; '));
    }
  }
}
