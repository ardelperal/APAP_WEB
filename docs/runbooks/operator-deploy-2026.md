# Operator deploy runbook — APAP_WEB on Coolify

[← Back to Codebase Guide](../CODEBASE-GUIDE.md)

This runbook walks an operator through the full deploy lifecycle for the
``apap-web`` Coolify service: first-time setup, every-deploy procedure,
rollback, password reset, and session-secret rotation. It is the single
human-facing counterpart to [`coolify/apap-web-coolify.yaml`](../../coolify/apap-web-coolify.yaml),
the deploy contract that pins image / port / healthcheck / env vars.

**Audience**: operator with Coolify admin access, SSH into the Oracle VPS,
and `gh` CLI on a workstation. No application code is touched.

**When to use this runbook**:

- First-time deploy of ``apap-web`` to a new Coolify service.
- Scheduled redeploy after a ``main`` merge that the CI built.
- Incident response: rollback to a previous image tag.
- Password reset for the bootstrap admin (``ardelperal@gmail.com``).
- Rotation of ``APAP_SESSION_SECRET`` (every 90 days, see
  [`cookie-rotation.md`](cookie-rotation.md)).

## What this is / is not

### What this is

| It is | Evidence in this repo |
|---|---|
| The single source of truth for operator deploy steps | [`coolify/apap-web-coolify.yaml`](../../coolify/apap-web-coolify.yaml) pins image, port, healthcheck, env vars. |
| A step-by-step procedure the operator follows without reading code | This document, ordered by phase. |
| Test-anchored: the yaml contract is enforced by `tests/test_coolify_web_yaml.py`. | CI fails the build if the deploy contract drifts from the runbook. |

### What this is not

| It is not | Use this boundary |
|---|---|
| A substitute for CI/CD | GitHub Actions publishes, verifies and promotes the image; the operator maintains the Coolify service and its secrets. |
| A migration guide | See [`live-migration-apply.md`](live-migration-apply.md) for the ``.accdb`` → local backend migration. |
| A monitoring guide | Coolify's built-in container logs + `/healthz` are the only observability surface today. |

## Core invariants

- **Verify before deployment**: `deploy.yml` publishes `sha-<full-sha>` with a
  component inventory and provenance, then scans and smokes that exact digest.
  The current source-based Coolify resource must expose the same commit through
  its runtime `SOURCE_COMMIT`; phase 1 remains the target image-based setup.
- **Fail closed**: missing webhook credentials, missing health URL, absent CI
  evidence, a failed scan, smoke test or revision check all fail the deployment.
- **Automatic rollback**: if post-deploy verification fails after promotion,
  CI restores the previous digest, retriggers Coolify and verifies its revision.
- **`APAP_SESSION_SECRET` rotation invalidates every active session**:
  coordinate the rotation for a low-traffic window.

## Phase 1 — First-time setup (one-off)

1. **Provision PostgreSQL** in Coolify and verify connectivity from the app
   network. The application reads `APAP_LOCAL_DB_URL` at startup.

2. **Create `apap-web` as an image-based service**:
   - Image: `ghcr.io/ardelperal/apap-web:deploy-current`.
   - Always pull the image when a deployment is triggered.
   - Do not configure a source build in Coolify.
   - Port: `8000`.
   - Healthcheck: `GET /healthz` every 10 seconds, with 30 seconds of grace.
     The response includes ``storage: up|down|unconfigured``.
   - Domain: `https://apap.romancaba.com` behind Traefik.

3. **Set runtime variables** from
   [`coolify/apap-web-coolify.yaml`](../../coolify/apap-web-coolify.yaml).
   Store `APAP_SESSION_SECRET`, `APAP_LOCAL_DB_URL` and
   `APAP_SMTP_PASSWORD` as secrets.

4. **Set GitHub Actions deployment configuration**:
   - Secret `COOLIFY_WEBHOOK_URL`.
   - Secret `COOLIFY_WEBHOOK_SECRET`.
   - Repository variable `APAP_DEPLOY_HEALTH_URL`, normally
     `https://apap.romancaba.com/healthz`.
   - One production runner must carry the exclusive `deploy` label.

5. **Bootstrap the deployment pointer**. Run the deploy workflow only after a
   PR has passed `ci / required` and has been merged to `main`. The workflow
   publishes the immutable image and creates `deploy-current`.

6. **Verify the result**:
   ```bash
   curl -fsS https://apap.romancaba.com/healthz
   # Expected: {"status": "ok", "app": "APAP_WEB", "revision": "<sha>", "storage": "unconfigured|up|down"}
   ```

## Phase 2 — Automated deployment after a merge

No manual image flip is required:

1. `evidence` proves that the merge tree is identical to a successful PR CI run.
2. The dedicated ARM64 runner builds and pushes `sha-<full-sha>` once, with
   component-inventory and provenance attestations.
3. Trivy scans that digest and an isolated PostgreSQL smoke test starts that
   same digest and checks `/healthz.revision`.
4. CI moves `deploy-current` to the verified digest and invokes the signed
   Coolify webhook. The current resource rebuilds that commit and injects
   `SOURCE_COMMIT`; an image-based replacement pulls the promoted pointer.
5. CI polls `APAP_DEPLOY_HEALTH_URL` until the public endpoint reports the
   expected full SHA. A stale or unhealthy deployment is a failed run.

The unique `sha-<full-sha>` tag remains available for audit and rollback.

> **Deploy-order warning (issue #1005)**: since the magic-link flag landed,
> the `APAP_AUTH_ENABLE_MAGIC_LINK` environment variable gates the
> magic-link login routes (default **off**). A build with the flag
> merged but the variable unset disables magic-link login on deploy.
> Verify the variable is set to `true` in the Coolify environment
> before promoting such a build — see
> [Feature flag: `APAP_AUTH_ENABLE_MAGIC_LINK`](#feature-flag-apap_auth_enable_magic_link-magic-link-login)
> below.

## Phase 3 — Rollback

Post-deploy failure triggers rollback automatically: CI restores
`deploy-current`, requests the previous source revision from Coolify and verifies
that revision. The workflow remains red so the incident is visible.

For manual incident response on an image-based resource:

1. Identify a previously verified digest from the deploy run or the
   `sha-<full-sha>` tag in the GitHub container registry.
2. Move the deployment pointer:
   ```bash
   docker buildx imagetools create \
     --tag ghcr.io/ardelperal/apap-web:deploy-current \
     ghcr.io/ardelperal/apap-web@sha256:<digest>
   ```
3. Trigger the signed Coolify webhook and verify `/healthz.revision` matches the
   chosen build SHA.

For the current source-based resource, revert the faulty merge through a green
pull request. Its normal deployment becomes the auditable rollback.

A database migration rollback is outside this procedure; follow
[`live-migration-apply.md`](live-migration-apply.md) for schema recovery.

## Phase 4 — Password reset (bootstrap admin)

The bootstrap admin is seeded on first startup from
``APAP_INITIAL_ADMIN_EMAIL`` (defaults to ``ardelperal@gmail.com`` in
``Settings.initial_admin_email``). To reset that user's password:

1. **Get a DB shell** against ``apap-pg-test`` (the Postgres service).
   ```bash
   coolify_exec --service apap-pg-test -- psql -U apap -d apap
   ```

2. **Generate an argon2id hash** of the new password locally:
   ```bash
   python -c "from app.core.adapters.auth_local.classic_password_auth_port import ClassicPasswordAuthPortImpl; print(ClassicPasswordAuthPortImpl._hash_password('new-secret-123'))"
   ```
   The default argon2id parameters match ``ClassicPasswordAuthPort``;
   reusing the helper guarantees the hash format is accepted by the
   login route.

3. **Update the row**:
   ```sql
   UPDATE usuarios_autorizados
   SET password_hash = '<paste-hash>'
   WHERE email = 'ardelperal@gmail.com';
   ```

4. **Log in** at ``https://apap.romancaba.com/login`` with the new
   password. The next session is signed with the existing
   ``APAP_SESSION_SECRET`` so other users are unaffected.

## Phase 5 — Rotate ``APAP_SESSION_SECRET``

Per [`cookie-rotation.md`](cookie-rotation.md), rotate every 90 days.
This invalidates every active session — coordinate for a low-traffic
window.

1. **In the Coolify UI**: apap-web → Environment → edit
   ``APAP_SESSION_SECRET`` to a new random string of at least 32
   characters. Mark it as **secret**.

2. **Redeploy**. The lifespan regenerates the signer with the new
   secret; old cookies are rejected on the next request.

3. **Notify the team**: every operator and key user must log in again.

## Phase 6 — Restore from a backup

The ``apap-pg-test`` Postgres service is backed up via Coolify's
scheduled dump (see the operator-side ``coolify_database_backups``
config; the schedule is documented in the staging VPS runbook).
To restore:

1. **Stop the apap-web service** in Coolify.

2. **Restore the dump**:
   ```bash
   coolify_exec --service apap-pg-test -- \
       psql -U apap -d apap < /backups/apap-pg-test-YYYY-MM-DD.sql
   ```

3. **Restart the apap-web service**. The lifespan re-bootstraps the
   schema idempotently (``CREATE TABLE IF NOT EXISTS``), so a dump
   that is missing a column lands the service in a known-good state
   after the next forward migration.

4. **Smoke-test** as in Phase 1 step 5.

## Phase 7 — Add object storage (Cloudflare R2)

Cloudflare R2 stores animal photos, replacing the M0 in-memory placeholder.
MinIO is not deployed: MinIO Community Edition went source-only in late 2025
and its container images were removed from Docker Hub, quay.io and every
public mirror, so there is nothing upstream left to run. R2 is S3-compatible,
which is what the application's storage client already speaks.

### 7a — Create the R2 buckets

Create **two** buckets in the existing R2 account, both private and both in
the **`eu` jurisdiction**:

| Bucket | Purpose |
|---|---|
| ``apap-photos`` | production attachments |
| ``apap-e2e`` | the CI gate's test objects |

The jurisdiction is fixed at creation and **cannot be changed afterwards**.
The photos are personal data, so ``eu`` is the correct choice, not the
default.

Attach a lifecycle rule to ``apap-e2e`` that expires the prefix ``e2e/``
after 24 hours. The suite writes every object under ``e2e/<run-id>/``, so the
rule replaces cleanup code and stops orphaned objects from accumulating.

### 7b — Create a scoped R2 API token

R2 → Manage R2 API Tokens → Create API token, permission **Object Read &
Write**, scoped to ``apap-photos``. Record the endpoint host
(``<account-id>.r2.cloudflarestorage.com``), the Access Key ID and the
Secret Access Key.

Do **not** reuse the account-level token that restic uses for backups: it can
list and delete every bucket in the account, and the web application needs no
such privilege.

### 7c — Configure the web service

In the ``apap-web`` Coolify resource → Environment, set (or update):

| Variable | Value |
|---|---|
| ``APAP_S3_ENDPOINT`` | ``<account-id>.r2.cloudflarestorage.com`` (bare host, no scheme) |
| ``APAP_S3_ACCESS_KEY`` | the Access Key ID of the scoped token |
| ``APAP_S3_SECRET_KEY`` | the Secret Access Key (mark as secret) |
| ``APAP_S3_BUCKET`` | ``apap-photos`` |
| ``APAP_S3_SECURE`` | ``true`` |

### 7d — Verify

```bash
curl -fsS https://apap.romancaba.com/healthz | python3 -c "import sys,json; d=json.load(sys.stdin); print('storage:', d.get('storage'))"
# Expected: storage: up
```

``storage: down`` means the credentials, the endpoint or the token scope is
wrong.

### 7e — Provision the CI gate

The ``e2e`` job in ``ci.yml`` validates this same backend through the
``apap-e2e`` bucket. Create a **second** token, permission Object Read &
Write, scoped to ``apap-e2e`` only, and store its values as repository
secrets:

| Secret | Value |
|---|---|
| ``R2_E2E_ENDPOINT`` | ``<account-id>.r2.cloudflarestorage.com`` |
| ``R2_E2E_ACCESS_KEY_ID`` | the Access Key ID |
| ``R2_E2E_SECRET_ACCESS_KEY`` | the Secret Access Key |

Two tokens, not one shared token: CI's credential cannot reach a production
object even if a constant or an environment variable is misconfigured, so
the isolation does not depend on the code being right.

The gate fails closed while these secrets are absent — the e2e suite raises
instead of skipping, so a missing credential shows up as a red run rather
than a green one that tested nothing.

``make e2e-local`` is the exception: it runs the pinned MinIO replica on a
workstation and needs no R2 credentials. See
``docs/operations/minio-replica.md``.

## Feature flag: `APAP_AUTH_ENABLE_MAGIC_LINK` (magic-link login)

| Property | Value |
|---|---|
| Env var | `APAP_AUTH_ENABLE_MAGIC_LINK` |
| Default | `false` (default-deny, AGENTS §6) — the magic-link login routes are **not** registered and probes to `/auth/magic/*` receive a fail-closed 404 |
| How to enable | In the `apap-web` Coolify resource → Environment, set `APAP_AUTH_ENABLE_MAGIC_LINK=true` and redeploy |
| Introduced by | Issue #1005 (deferred from #917) |

**Deploy-order warning**: production served magic-link login with the
routes registered unconditionally. When deploying a build that carries
this flag, the variable must already be set to `true` in the Coolify
environment — merging without it breaks magic-link login on the next
deploy (the login form's POST to `/auth/magic/start` will receive a
404). Setting the variable is the operator's decision: coordinate the
change before promoting the build, never after.

The Google OAuth login flow is not affected by this flag; only the
magic-link (`email + token`) login surface is gated.

## Contributor checklist

- [ ] Before any change to ``coolify/apap-web-coolify.yaml``, run
      ``pytest tests/test_coolify_web_yaml.py`` to confirm the new
      contract still parses.
- [ ] After any change to ``app/core/config.py::Settings`` (new env
      var), update the yaml and the env table in this runbook.
- [ ] After adding MinIO storage vars, document them in Phase 7 and in
      ``coolify/apap-web-coolify.yaml``.
- [ ] After any change to ``app/main.py``'s
      response shape, update the smoke-test command in Phase 1.
- [ ] When rotating ``APAP_SESSION_SECRET``, announce the rotation
      window to the team 24h ahead.

## Navigation

Previous: [coolify-deploy.md](coolify-deploy.md) (legacy) | Back: [Codebase Guide](../CODEBASE-GUIDE.md)
