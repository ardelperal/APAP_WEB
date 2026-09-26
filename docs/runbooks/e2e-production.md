[← Back to Codebase Guide](../CODEBASE-GUIDE.md)

# Runbook — Production E2E Validation Release Gate

This runbook covers the production e2e validation release gate: turning the
hardened e2e auth mock on against `https://apap.romancaba.com`, running the
gate suites with Playwright, and turning it back off. It exists so an agent
or operator can execute the full on → tests → off cycle without asking
questions (epic #909, opción B endurecida).

**Audience**: an agent session or operator with the Coolify API credentials
in the environment and `gh`/`python` available locally. No SSH to the VPS is
required; every server-side action goes through the Coolify API.

**When to use this runbook**:

- Only as a release gate: a release candidate was merged to `main` and must
  be validated against production before it is declared valid.
- Never for day-to-day testing. Authenticated e2e against production outside
  a release cycle is a non-goal of the epic (issue #909).

## What this is / is not

### What this is

| It is | Evidence in this repo |
|---|---|
| The operator procedure for the e2e release gate (env edit + restart via Coolify API) | The flags live in `Settings` (`e2e_auth_enabled`, `e2e_auth_secret`, `app/core/config.py`); the route contract lives in `app/core/e2e_auth.py`. |
| The canonical way to mint an authenticated Playwright session in production | `scripts/e2e_login.py` (issue #906, merged via #1000) plus the fixtures in `tests/e2e/conftest.py`. |
| The definition of which suites are the gate and what pass/fail means | The suites and skip policy below mirror `tests/e2e/conftest.py` and the hardened `tests/e2e/test_e2e_login_storage_state.py`. |

### What this is not

| It is not | Use instead |
|---|---|
| A rollback procedure | [`deploy-rollback.md`](deploy-rollback.md) if a failed gate forces a revert. |
| A deployment guide | [`operator-deploy-2026.md`](operator-deploy-2026.md) for first deploy and redeploy. |
| A place to run the e2e suite in CI with the secret | The epic explicitly excludes running Playwright with secrets inside GitHub Actions (#909). |

## Core invariants

- **The flag must end off (reposo).** `APAP_E2E_AUTH_ENABLED=false` is the
  resting state of production. The off procedure at the end is not optional:
  it is an epic acceptance criterion (#909). If a gate run aborts early, the
  off procedure still applies.
- **The secret never travels on argv, in logs, or in the repo.** The helper
  reads it from the environment variable named by `--secret-env` and never
  prints it. The minted `storageState` holds a live session cookie and is
  written with `0600`; `.auth/` is gitignored — keep it that way.
- **A wrong secret fails; a missing one skips.** Per the dual-review fix in
  fefa6c2: a wrong or stale secret (401) fails the authenticated suite
  loudly, while a missing `APAP_E2E_AUTH_SECRET` env var or a 404 (mock
  disabled) skips. During a gate run the env is set, so any skip of the
  authenticated suites means misconfiguration — investigate before
  declaring anything.
- **Never run the whole `tests/e2e/` directory against production.** Many
  suites are data-writing CRUD batteries; with the flag on they would
  mutate production data. Run only the explicit gate suites listed below.

## Preconditions

1. **Flags provisioned in Coolify.** As of this PR the production
   environment variables `APAP_E2E_AUTH_ENABLED` and `APAP_E2E_AUTH_SECRET`
   are not yet provisioned — provisioning was deferred to issue #905. Until
   #905 lands and its dry run fills the `TODO-VERIFY` markers below, the on
   procedure cannot run against production. Do not improvise endpoints.
2. **Secret generated and held outside the repo.** The secret is a
   64-character hexadecimal string, generated with
   `openssl rand -hex 32`, stored in Coolify (and, if ever needed for CI,
   in GitHub Actions secrets). The operator exports it into the shell:

   ```bash
   export APAP_E2E_AUTH_SECRET="<value from the Coolify env / secret store>"
   ```

3. **Coolify API credentials in the shell.** The operator's environment
   carries the base URL and the access token of the Coolify instance:

   ```bash
   export COOLIFY_BASE_URL="<coolify instance base url>"
   export COOLIFY_ACCESS_TOKEN="<coolify api token>"
   ```

4. **Local tooling.** Python environment with the dev extras and Chromium:

   ```bash
   uv sync --frozen --extra dev
   python -m playwright install chromium
   ```

5. **Target reachable.** `https://apap.romancaba.com/healthz` reports the
   revision under validation before starting.

## Step 1 — Turn the e2e auth flag on (Coolify API)

The on procedure is an environment edit plus a restart through the Coolify
API, using the operator credentials `COOLIFY_BASE_URL` and
`COOLIFY_ACCESS_TOKEN`. The generic endpoint pattern is shown with the
application UUID as a placeholder.

```bash
# 1a. List the current environment variables of the application.
# TODO-VERIFY(#905): fill APP_UUID and confirm the exact endpoint and verb
# against the live Coolify API during the #905 dry run.
curl -sS -H "Authorization: Bearer ${COOLIFY_ACCESS_TOKEN}" \
  "${COOLIFY_BASE_URL}/api/v1/applications/{APP_UUID}/envs"

# 1b. Set the flag to true.
curl -sS -X PATCH \
  -H "Authorization: Bearer ${COOLIFY_ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"key": "APAP_E2E_AUTH_ENABLED", "value": "true"}' \
  "${COOLIFY_BASE_URL}/api/v1/applications/{APP_UUID}/envs"

# 1c. Restart the application so the new env takes effect.
curl -sS -H "Authorization: Bearer ${COOLIFY_ACCESS_TOKEN}" \
  "${COOLIFY_BASE_URL}/api/v1/applications/{APP_UUID}/restart"
```

`APAP_E2E_AUTH_SECRET` is already provisioned as a Coolify env by #905; this
step only toggles the enabled flag. Do not echo or log either value.

## Step 2 — Verify the endpoint is live

After the restart, the mock must answer 401 without the secret header
(route registered, secret required) instead of 404 (route absent, flag off):

```bash
export APAP_E2E_BASE_URL="https://apap.romancaba.com"
curl -sS -o /dev/null -w '%{http_code}\n' "${APAP_E2E_BASE_URL}/e2e/login"
```

- `401` — flag on, secret enforced. Proceed.
- `404` — the flag did not take effect. Re-check the env edit and the
  restart; do not continue.

The endpoint is audited and rate-limited (issue #904): every mint attempt
writes an audit entry. Mint once per suite run, not in a loop.

## Step 3 — Mint the storageState

`scripts/e2e_login.py` calls `GET /e2e/login` with the `X-E2E-Secret` header
and writes a Playwright `storageState`:

```bash
python scripts/e2e_login.py \
  --base-url "${APAP_E2E_BASE_URL}" \
  --secret-env APAP_E2E_AUTH_SECRET \
  --email e2e@apap.local \
  --out .auth/state.json
```

Contract of the helper (issue #906):

- The secret is read from the environment variable named by `--secret-env`
  only — never from argv, and never printed on success or failure.
- The file is written with `0600` because it contains a live session cookie.
- Exit 0 means the `apap_session` cookie was minted and persisted; exit 1
  with a message on stderr means login or transport failure.

The minted session mirrors the OAuth callback payload (role `developer`)
and pre-populates the in-process auth cache, so it does not depend on the
`usuarios_autorizados` seed.

## Step 4 — Run the gate suites

Point the suite at production with `APAP_E2E_BASE_URL` and run only the
explicit gate suites:

- **Authenticated gate** (via the shared `authenticated_state` /
  `authenticated_context` fixtures): `test_e2e_login_storage_state.py`
  (the storage-state suite) and `test_stepper_component.py` (stepper
  component and preview via `authenticated_context`).
- **Public, read-only gate**: landing, layout, navigation and a11y suites,
  plus the login-form, public-redirect and security-header suites.

```bash
APAP_E2E_BASE_URL="${APAP_E2E_BASE_URL}" python -m pytest \
  tests/e2e/test_e2e_login_storage_state.py \
  tests/e2e/test_stepper_component.py \
  tests/e2e/test_landing.py \
  tests/e2e/test_layout_responsive_extended.py \
  tests/e2e/test_nav_active_state.py \
  tests/e2e/test_nav_burger_toggle.py \
  tests/e2e/test_nav_icons.py \
  tests/e2e/test_nav_layout.py \
  tests/e2e/test_nav_no_multiline.py \
  tests/e2e/test_nav_responsive_structure.py \
  tests/e2e/test_a11y_brand_tabindex.py \
  tests/e2e/test_a11y_main_landmark.py \
  tests/e2e/test_a11y_skip_link.py \
  tests/e2e/test_login_form.py \
  tests/e2e/test_login_submit_button.py \
  tests/e2e/test_public_redirects.py \
  tests/e2e/test_security_headers.py \
  -v
```

### Skipped by design

- **Data-writing CRUD suites** (`test_acogidas_crud.py`, `test_animales_*`,
  `test_adopciones_*`, `test_casas_acogida_*`, `test_cesiones_*`,
  `test_entradas_*`, `test_materiales_*`, `test_sanidad_*`,
  `test_terapias_*`, `test_voluntarios_*`, and similar): excluded from the
  production gate. They create, update and delete rows; production
  validation through them is out of scope for the gate.
- **`test_magic_link_e2e.py`**: needs a reachable MailDev instance
  (`MAILDEV_URL`); it skips without one and has no production target.
- **Stepper devtools preview tests** inside `test_stepper_component.py`:
  they hit `/devtools/stepper-preview`, which answers 404 when the server's
  devtools flag is off — the production default. That skip is expected and
  acceptable; do not turn the devtools flag on in production for the gate.

### Station suite, not regular CI

`tests/e2e/` is a station suite: the regular CI pytest run ignores it, and
the dedicated `e2e` job in `ci.yml` fires only on tag push or manual
dispatch against its own ephemeral stack. The production gate in this
runbook runs from a workstation against the live deployment.

## Pass/fail criteria and failure handling

**Pass** means: pytest exits 0 with no failures, and the only skips are the
expected ones above (devtools preview when the flag is off). Any other skip
of the authenticated suites — typically the 404 skip — means the mock was
not actually enabled: stop, return to Step 2, and re-verify.

**Fail** means: at least one gate test failed. Then:

1. Do not mark the release as valid. A red gate is a failed gate.
2. Reproduce once to rule out a transient error, with the same command.
3. If the failure reflects a real defect in the deployed revision, the
   release candidate is rejected: fix forward or revert. For a revert of the
   deployed digest, follow [`deploy-rollback.md`](deploy-rollback.md).
4. File a `type:bug` issue with the failing test, the run output and the
   revision under test (precedent: #901).

The gate verdict and the pytest run output (or its stored artifact) become
part of the release evidence, next to the deployment verification.

## Step 5 — Turn the flag off and verify reposo

Same endpoint pattern as Step 1, with the value set back to `false`, then a
restart and a 404 check:

```bash
# 5a. Set the flag back to false.
curl -sS -X PATCH \
  -H "Authorization: Bearer ${COOLIFY_ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"key": "APAP_E2E_AUTH_ENABLED", "value": "false"}' \
  "${COOLIFY_BASE_URL}/api/v1/applications/{APP_UUID}/envs"

# 5b. Restart the application.
curl -sS -H "Authorization: Bearer ${COOLIFY_ACCESS_TOKEN}" \
  "${COOLIFY_BASE_URL}/api/v1/applications/{APP_UUID}/restart"

# 5c. Verify reposo: the route must be gone.
curl -sS -o /dev/null -w '%{http_code}\n' "${APAP_E2E_BASE_URL}/e2e/login"
```

`404` is the required final state. Anything else means the flag did not
take effect — repeat the env edit and restart until the route is gone.

## Step 6 — Clean up and record evidence

The minted `storageState` is a live session: destroy it after the run.

```bash
rm -f .auth/state.json
```

Record in the release evidence: the pytest invocation, the pass/fail
verdict, the deployed revision, and the timestamps of the on and off
transitions. `rm` is confined to the gitignored `.auth/` scratch file; it
touches nothing else.

## Copyable checklist

Execute in order. Stop at the first unexpected result and re-read the
matching step.

```bash
# 0. Preconditions: credentials and secret in the shell.
test -n "${APAP_E2E_AUTH_SECRET:?export APAP_E2E_AUTH_SECRET first}" \
  && test -n "${COOLIFY_BASE_URL:?}" && test -n "${COOLIFY_ACCESS_TOKEN:?}"
export APAP_E2E_BASE_URL="https://apap.romancaba.com"

# 1. Flag on (Coolify API: env edit + restart).
# TODO-VERIFY(#905): confirm endpoint/verb and fill {APP_UUID}.
curl -sS -X PATCH -H "Authorization: Bearer ${COOLIFY_ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"key": "APAP_E2E_AUTH_ENABLED", "value": "true"}' \
  "${COOLIFY_BASE_URL}/api/v1/applications/{APP_UUID}/envs"
curl -sS -H "Authorization: Bearer ${COOLIFY_ACCESS_TOKEN}" \
  "${COOLIFY_BASE_URL}/api/v1/applications/{APP_UUID}/restart"

# 2. Endpoint live: expect 401 without the header.
curl -sS -o /dev/null -w '%{http_code}\n' "${APAP_E2E_BASE_URL}/e2e/login"

# 3. Mint the storageState (secret from env; file written 0600).
python scripts/e2e_login.py --base-url "${APAP_E2E_BASE_URL}" \
  --secret-env APAP_E2E_AUTH_SECRET --email e2e@apap.local \
  --out .auth/state.json

# 4. Gate suites (never the whole tests/e2e/ directory).
APAP_E2E_BASE_URL="${APAP_E2E_BASE_URL}" python -m pytest \
  tests/e2e/test_e2e_login_storage_state.py \
  tests/e2e/test_stepper_component.py \
  tests/e2e/test_landing.py \
  tests/e2e/test_layout_responsive_extended.py \
  tests/e2e/test_nav_active_state.py \
  tests/e2e/test_nav_burger_toggle.py \
  tests/e2e/test_nav_icons.py \
  tests/e2e/test_nav_layout.py \
  tests/e2e/test_nav_no_multiline.py \
  tests/e2e/test_nav_responsive_structure.py \
  tests/e2e/test_a11y_brand_tabindex.py \
  tests/e2e/test_a11y_main_landmark.py \
  tests/e2e/test_a11y_skip_link.py \
  tests/e2e/test_login_form.py \
  tests/e2e/test_login_submit_button.py \
  tests/e2e/test_public_redirects.py \
  tests/e2e/test_security_headers.py \
  -v

# 5. Flag off (Coolify API: env edit + restart).
curl -sS -X PATCH -H "Authorization: Bearer ${COOLIFY_ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"key": "APAP_E2E_AUTH_ENABLED", "value": "false"}' \
  "${COOLIFY_BASE_URL}/api/v1/applications/{APP_UUID}/envs"
curl -sS -H "Authorization: Bearer ${COOLIFY_ACCESS_TOKEN}" \
  "${COOLIFY_BASE_URL}/api/v1/applications/{APP_UUID}/restart"

# 6. Reposo verified: expect 404.
curl -sS -o /dev/null -w '%{http_code}\n' "${APAP_E2E_BASE_URL}/e2e/login"

# 7. Destroy the live session file.
rm -f .auth/state.json
```

## Anti-patterns

| Symptom | Why it matters | Do instead |
|---|---|---|
| Running the whole `tests/e2e/` directory against production | The CRUD suites write and delete production rows | Run only the explicit gate suites from Step 4 |
| Leaving the flag on after a successful run | The session-minting mock stays reachable in production | Step 5 is mandatory; verify the 404 |
| Passing the secret on the command line | argv leaks through shell history and process listings | Use `--secret-env` and export the variable |
| Committing or sharing `.auth/state.json` | It contains a live session cookie | Keep it in the gitignored `.auth/` and delete it after the run |
| Marking the release valid with a red or skipped gate | A green-skipped gate validates nothing | Only an exit 0 run with only the expected skips counts |
| Turning the devtools flag on in production to unskip preview tests | Widens the production surface for a test convenience | Accept the documented skip |

## Contributor checklist

- [ ] The run started from a provisioned environment (#905) with the flag off.
- [ ] `TODO-VERIFY(#905)` markers were resolved against the live Coolify API before the first real run.
- [ ] Only the gate suites ran; no CRUD suite touched production data.
- [ ] The minted `storageState` was deleted after the run.
- [ ] The final check returned 404 and the flag is off.
- [ ] The verdict and run output were recorded in the release evidence.

## Navigation

Related: [deploy-rollback.md](deploy-rollback.md) | [operator-deploy-2026.md](operator-deploy-2026.md) | Back: [Codebase Guide](../CODEBASE-GUIDE.md)
