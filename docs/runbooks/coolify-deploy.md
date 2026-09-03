# Runbook: Coolify production deploy

Audience: production operators deploying APAP_WEB on Coolify.
Scope: post-M0 + post-M1 self-host backend, pre-M1.5 SMTP wiring.

## 1. Pre-deploy checks

Before pushing to the deploy branch:

- All APAP_* env vars referenced in [.env.example](../../../.env.example) MUST be set on the Coolify target.
  Run `coolify env list --app apap-web` (or the Coolify UI) and cross-reference with [.env.example](../../../.env.example).
- Run `python -m migration.cli_verify_fallback_ready --ci-only` against the production
  InsForge URL. Exit code MUST be 0. The 4 current checks are
  check_round_trip_test, check_pii_audit_verdict,
  check_web_to_legacy_check_only, and check_magic_link_local_round_trip.

## 2. Deploy

Coolify detects pushes to main via the GitHub webhook in
`.github/workflows/deploy.yml`. The Dockerfile is multi-stage:

- Stage 1 (tailwind-base): Node 20 + Tailwind v4 compiles the production CSS bundle.
- Stage 2 (builder): Python 3.11 + build-essential builds the wheel.
- Stage 3 (runtime): Python 3.11 slim + non-root user (uid 1001) + the
  wheel from the builder stage. HEALTHCHECK probes /healthz for CD-02.

Build time: ~3 min on the standard Coolify builder.
First deploy after a Tailwind bump takes ~5 min (full rebuild).

## 3. Verify

After the Coolify badge turns green:

- `curl -fsS https://apap.example.org/healthz` returns
  `{"status": "ok", "app": "APAP_WEB"}` with HTTP 200.
- The OAuth round-trip still works end-to-end with a known
  `usuarios_autorizados` row: GET / redirects to /login,
  GET /auth/google redirects to Google, callback lands at /.
- The structured logs emit auth.login events on every successful
  sign-in (visible in the Coolify log view). See
  docs/codebase/operations.md for log routing.

## 4. M0 local backend (POST-M0, MONITORING-ONLY)

The M0 slice added a local-backend subprocess wired via
[APAP_LOCAL_BACKEND](../../../.env.example#10-m0-local-backend-post-m0-monitoring-only)=true.
**Production MUST set this to false** (see
[docs/production-env.md](../production-env.md)).
The magic-link flow on production is verified via InsForge production
(per migration.verify_fallback_ready.check_web_to_legacy_check_only,
which spawns a local backend only when APAP_LOCAL_BACKEND=true).

## 5. M1 magic-link (POST-M1, MONITORING-ONLY)

The M1 slice added a magic-link channel gated by
[APAP_AUTH_ENABLE_MAGIC_LINK](../../../.env.example#11-m1-magic-link-post-m1-monitoring-only).
**Production MUST set this to false** (see
[docs/production-env.md](../production-env.md))
until M1.5 ships the SMTP wiring (the SMTPMailTransport placeholder
remains in place). Operators who want to experiment with the local
self-host magic-link flow set it to true and provide the M1 dev
env vars (see [.env.example](../../../.env.example) section "M1 magic-link").

## 6. Rollback

`git revert <deploy-sha>` followed by `git push origin main` triggers
a Coolify rebuild with the previous image. Rebuild takes ~3 min.

After rollback, sessions issued under the previous image MAY invalidate
because the session secret may differ between deploys. Set
[APAP_AUTH_CACHE_TTL_SECONDS](../../../.env.example#7-auth-cache)=0
in Coolify to force per-request
re-validation (one extra SELECT per authenticated request). See
[docs/runbooks/auth-cache-multi-worker.md](auth-cache-multi-worker.md) for the rationale.

## 7. Observability

JSON stdout logs are aggregated by Coolify's log collector. PII fields
(email, address, etc.) are redacted by app.core.logging.log_safe
via a 12-field allow-list. See [docs/codebase/security.md](../codebase/security.md).

## Cross-references

- [.env.example](../../../.env.example) — every APAP_* env var with Default + required state.
- [docs/production-env.md](../production-env.md) — single-page operator reference with the StartupConfigError rule per var.
- [docs/codebase/security.md](../codebase/security.md) — auth cache contract (single-worker + in-process).
- [docs/runbooks/auth-cache-multi-worker.md](auth-cache-multi-worker.md) — multi-replica checklist (out of scope today).
- [docs/audits/auth-cache-in-process-audit-2026-Q3.md](../audits/auth-cache-in-process-audit-2026-Q3.md) — production deploy audit.
