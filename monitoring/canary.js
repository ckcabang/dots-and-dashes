// The canary: the key journey, as the Canary User, once per run.
//
// Grafana Synthetic Monitoring runs it every minute against prod as a scripted
// (k6) check, so the save failure and save latency alerts have traffic to fire
// on with only one real User (docs/runbooks/README.md). CI runs it once against
// the Compose test stack as a smoke test (.github/workflows/ci.yml).
//
// It logs in, logs an Entry on today's Daily Log, reads it back and deletes it.
// Each step checks its own status code: a lost login answers 401, which the
// save metrics count as refused rather than failed, so only the canary's own
// failure (the "Canary failing" alert, on probe_success) would show it.
//
// The password is the Synthetic Monitoring secret `canary-password`, never in
// this file. Locally: k6 run --secret-source=file=<file with
// canary-password=...> monitoring/canary.js, with BASE_URL to aim it elsewhere.
//
// The Entry's text is fixed and says nothing; nothing here logs a request or
// response body, and the app keeps Entry text out of its own telemetry.

import http from 'k6/http';
import { check, fail } from 'k6';
import secrets from 'k6/secrets';

const BASE_URL = (__ENV.BASE_URL || 'https://dots-and-dashes.fly.dev').replace(/\/$/, '');
const EMAIL = __ENV.CANARY_EMAIL || 'canary@dots-and-dashes.invalid';
const TEXT = 'canary check';

export const options = {
  iterations: 1,
  // Any failed check fails the run, and so the probe.
  thresholds: { checks: ['rate==1.0'] },
};

// Each request is named by its route, not its URL, so an Entry ID never
// becomes a metric label.
function named(name, params = {}) {
  return { ...params, tags: { name } };
}

export default async function () {
  const password = await secrets.get('canary-password');

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
