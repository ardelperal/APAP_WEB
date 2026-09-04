# Proposal: M3.1 — Magic-link E2E verification (TDD + RDD)

skill_resolution: paths-injected (sdd-propose, web-tdd-philosophy)

## Why this slice

After M0/M1/M2/M3 landed on `main` and the M3 production deploy succeeded
(commit `9b057b7` on `feat/641-rdd-m0` and on `origin/main`), the app at
`https://apap.romancaba.com/healthz` returns `200 OK`. The previous
deployment gaps (arm64 image digests in the Dockerfile, psycopg missing
from runtime dependencies) are fixed in two commits that are now on
`main`:
- `84a44d7 fix(deps): move psycopg[binary] from dev optionals to runtime dependencies`
- `9b057b7 fix(deploy): use arm64 image digests so build works on Oracle VPS (aarch64)`

What is still missing is a **TDD-driven end-to-end Playwright test that
exercises the full magic-link round-trip against the deployed app**:
navigate to `/login` → see the magic-link form → submit email → read the
MailDev UI to extract the verify URL → GET it → assert the `apap_session`
cookie is set + the user lands on `/`.

The M3.1 slice ships exactly that test plus a tiny helper that talks to
the local MailDev HTTP UI to read the most recent message (the SMTP server
we run in this workspace, `apap-smtp-dev`, is MailDev, which exposes
`http://<container>:8025/` with a JSON API).

TDD red first: the test must fail BEFORE the implementation (because the
helper does not exist). The helper is the smallest possible implementation
that turns the test green. RDD: open a lineage AFTER the SDD commit,
BEFORE the implementation commit, so the implementation lands inside the
frozen scope.

## What this slice does NOT do

- The `apply-progress.md` for M3 — that belongs to the M3 archive; M3.1
  is verification, not the M3 slice itself.
- Real-SMTP Mailgun production wiring — that is M3.2 (operator-side env
  var change on Coolify). M3.1 uses the local MailDev container.
- A new gate in `verify-fallback-ready` for E2E — the Playwright test
  lives under `tests/e2e/`, not `tests/migration/`, and is run by the
  CI `e2e` job, not `verify-fallback-ready`.
- Modifying the existing F1/F2/F3 tests in `tests/integration/test_magic_link*.py`
  — those already pass against the local backend subprocess; they don't
  need a Coolify URL.

## Forecast

Forecast total ≤200 LOC additions plus ≤20 deletions. Single feature
(no chain needed) because the slice is dominated by a single Playwright
test plus one 30-line helper.

- `tests/e2e/test_magic_link_e2e.py` (NEW, ~120 LOC) — single atom
  `test_magic_link_round_trip_against_deployed_app` marked
  `@pytest.mark.e2e` (existing marker; `e2e-self-hosted.yml` already runs
  this job). Reads `apap.romancaba.com` from `E2E_BASE_URL` env (defaults
  to `https://apap.romancaba.com`).
- `tests/e2e/_maildev_helper.py` (NEW, ~50 LOC) — `read_latest_verify_url(mailbox_url: str) -> str`
  calls `GET {mailbox_url}/api/v2/messages` on MailDev and returns the
  first `verifyUrl` field of the most recent message.
- `tests/e2e/conftest.py` (NEW, ~30 LOC) — `maildev_url` fixture that
  returns the MailDev HTTP base URL from `MAILDEV_URL` env
  (defaults to `http://apap-smtp-dev:8025`).

Each file is well under 700 lines.

## Why not just the existing `tests/integration/test_magic_link_production.py`

Those integration tests use a local `subprocess.Popen` for the backend
(per the F3 helper `run_magic_link_local_round_trip`). They do NOT touch
the deployed `apap.romancaba.com`. M3.1 is the layer above: it proves
the production deploy end-to-end with the real SMTP and real DB on
the same VPS.

## Risk

- The Playwright test depends on `apap.romancaba.com` being reachable
  from the test runner. CI's `e2e-self-hosted.yml` already runs the
  e2e job on the same VPS (via `myoung34/github-runner:ubuntu-noble`
  in `apap` Coolify project per engram #504), so the test runs locally
  to `apap.romancaba.com` without leaving the host network.
- The test depends on the MailDev container `apap-smtp-dev` running on
  the coolify network. If that container is down, the test fails
  loudly (the test's `request.get(maildev_url, timeout=5)` raises).
- The test depends on the user's authorized email existing in
  `usuarios_autorizados` in the local Postgres `apap-pg-test`. The
  bootstrap seed via `APAP_INITIAL_ADMIN_EMAIL=ardelperal@gmail.com`
  handles this on first deploy; subsequent deploys use `WHERE NOT EXISTS`
  so the row is not duplicated.

## RDD binding

This slice ships under RDD. Single lens `review-reliability` is enough
for a 1-test slice; the lineage opens AFTER the SDD commit and BEFORE
the implementation commit so the implementation lands in the frozen
scope.
