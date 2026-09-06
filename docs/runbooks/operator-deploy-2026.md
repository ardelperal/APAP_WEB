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
| An auto-deploy script | CI pushes images; the operator decides when to flip the Coolify service. |
| A migration guide | See [`live-migration-apply.md`](live-migration-apply.md) for the ``.accdb`` → local backend migration. |
| A monitoring guide | Coolify's built-in container logs + `/healthz` are the only observability surface today. |

## Core invariants

- **Image is built by CI, not by hand**: tag is the short SHA of the
  ``main`` commit. ``:latest`` is forbidden by the yaml contract.
- **Self-host is irreversible from this runbook's perspective**: the
  container runs ``APAP_LOCAL_BACKEND=true`` and there is no operator
  path to fall back to InsForge. Rollback = roll back the image tag.
- **``APAP_SESSION_SECRET`` rotation invalidates every active session**:
  every operator must re-login. Coordinate the rotation for a low-
  traffic window.

## Phase 1 — First-time setup (one-off)

The Coolify service does not exist yet. The operator:

1. **Provision the Postgres service** in Coolify (already done in
   the staging VPS as ``apap-pg-test``). Verify the operator can
   connect from the app VPS with the DSN; the app reads
   ``APAP_LOCAL_DB_URL`` at lifespan time.

2. **Create the ``apap-web`` Coolify service**:
   - Image: ``ghcr.io/ardelperal/apap-web:main`` (first deploy; later
     deploys pin a SHA).
   - Port: ``8000``.
   - Healthcheck: ``GET /healthz`` every 10s, 30s grace period.
   - Domain: ``https://apap.romancaba.com`` behind Coolify's Traefik.

3. **Set the env vars** in Coolify's secret store (the UI calls them
   "environment variables"; mark the sensitive ones as **secret**).
   The full list and defaults are in
   [`coolify/apap-web-coolify.yaml`](../../coolify/apap-web-coolify.yaml).
   Required secrets: ``APAP_SESSION_SECRET``, ``APAP_LOCAL_DB_URL``,
   ``APAP_SMTP_PASSWORD``, ``APAP_INSFORGE_SERVICE_KEY``.

4. **Trigger the first deploy** by pushing to ``main`` (the webhook in
   ``COOLIFY_WEBHOOK_URL`` fires the build) OR by clicking "Deploy" in
   Coolify's UI.

5. **Verify**:
   ```bash
   curl -fsS https://apap.romancaba.com/healthz
   # Expected: {"db": "up", "storage": "up", "oauth": "configured"|"missing"}
   ```

   If ``db: "down"``:
   - The lifespan could not construct ``LocalPostgresExecutor``;
     usually ``APAP_LOCAL_DB_URL`` is wrong or the Postgres service is
     unreachable from the app container.

   If ``oauth: "missing"``:
   - This is acceptable in production (magic-link is the primary
     login flow). Configure ``APAP_GOOGLE_CLIENT_ID`` etc. only if
     you want Google OAuth as an alternate path.

## Phase 2 — Redeploy after a main merge

CI builds the image and pushes to ``ghcr.io`` with the short SHA tag.
The operator redeploys:

1. **Wait for CI to finish** (the GitHub Actions bot comments on the PR
   or the ``main`` commit with the image tag).

2. **Flip the Coolify service** to the new image tag. In the Coolify
   UI: apap-web → Configuration → Image → replace
   ``ghcr.io/ardelperal/apap-web:v<old_sha>`` with
   ``ghcr.io/ardelperal/apap-web:v<new_sha>``. Save.

3. **Deploy**: click "Redeploy" in the UI. The Coolify service pulls
   the new image, runs the lifespan, and the new ``/healthz`` reports
   ``db: "up"`` once the lifespan finishes.

4. **Smoke-test the magic-link flow**:
   ```bash
   curl -fsS https://apap.romancaba.com/login | grep -q 'name="csrf_token"'
   ```
   The form must be present. Then exercise the full round-trip with
   your test inbox (the CI's ``tests/e2e/test_magic_link_e2e.py`` is
   the canonical automation).

## Phase 3 — Rollback

The previous image tag is one Coolify UI click away:

1. **In the Coolify UI**: apap-web → Configuration → Image → replace the
   current tag with the previous ``v<sha>``.

2. **Redeploy**. The lifespan runs against the rolled-back image; the
   in-flight sessions remain valid (sessions are signed cookies, the
   signing secret did not change).

3. **If the rollback is a database-migration rollback**: do NOT use
   this runbook; instead follow
   [`live-migration-apply.md`](live-migration-apply.md) § Reverse
   migration. The container rollback is for application code only;
   schema changes require a forward migration + a verified reverse
   migration.

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
- [ ] After any change to ``app/core/local_backend/healthz.py``'s
      response shape, update the smoke-test command in Phase 1.
- [ ] When rotating ``APAP_SESSION_SECRET``, announce the rotation
      window to the team 24h ahead.

## Navigation

Previous: [coolify-deploy.md](coolify-deploy.md) (legacy) | Back: [Codebase Guide](../CODEBASE-GUIDE.md)
