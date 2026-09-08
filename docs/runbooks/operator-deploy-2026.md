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

- **Build once, deploy by digest**: `deploy.yml` publishes
  `sha-<full-sha>` with a component inventory and build provenance, scans that
  exact digest, then moves `deploy-current`. Coolify never builds source.
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
   # Expected revision: the full SHA of the merged commit.
   ```

## Phase 2 — Automated deployment after a merge

No manual image flip is required:

1. `evidence` proves that the merge tree is identical to a successful PR CI run.
2. The dedicated ARM64 runner builds and pushes `sha-<full-sha>` once, with
   component-inventory and provenance attestations.
3. Trivy scans that digest and an isolated PostgreSQL smoke test starts that
   same digest and checks `/healthz.revision`.
4. CI moves `deploy-current` to the verified digest and invokes the signed
   Coolify webhook.
5. CI polls `APAP_DEPLOY_HEALTH_URL` until the public endpoint reports the
   expected full SHA. A stale or unhealthy deployment is a failed run.

The unique `sha-<full-sha>` tag remains available for audit and rollback.

## Phase 3 — Rollback

Post-deploy failure triggers rollback automatically: CI restores
`deploy-current` to the previous digest, invokes Coolify again, and verifies the
previous revision. The workflow remains red so the incident is visible.

For manual incident response:

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

## Contributor checklist

- [ ] Before any change to ``coolify/apap-web-coolify.yaml``, run
      ``pytest tests/test_coolify_web_yaml.py`` to confirm the new
      contract still parses.
- [ ] After any change to ``app/core/config.py::Settings`` (new env
      var), update the yaml and the env table in this runbook.
- [ ] After any change to ``app/main.py``'s
      response shape, update the smoke-test command in Phase 1.
- [ ] When rotating ``APAP_SESSION_SECRET``, announce the rotation
      window to the team 24h ahead.

## Navigation

Previous: [coolify-deploy.md](coolify-deploy.md) (legacy) | Back: [Codebase Guide](../CODEBASE-GUIDE.md)
