# Tasks: M2 — Coolify production deploy (env + runbook)

Per the [spec](specs/m2-coolify-deploy/spec.md) this is a docs-only slice with one source-docstring edit. All work lands in three new files + one minimal edit to `app/core/config.py::Settings.env_prefix` docstring. Single feature, no chain.

## Single feature: M2-deploy-docs

### T1. Write `.env.example` at repo root

The file MUST contain every APAP_* env var grouped by concern section:

```text
# APAP_WEB — Production environment template
#
# Operators copy this file to .env and edit values. The app never reads
# .env.example. See docs/production-env.md for the operator reference
# and docs/runbooks/coolify-deploy.md for the deploy checklist.
#
# Each block has a Default line and a Production required: yes/no line. When
# a required value is missing at startup, the StartupConfigError rule fires
# and the app fails fast (no half-booted prod).
```

Then per-concern sections:

1. **InsForge** — `APAP_INSFORGE_URL`, `APAP_INSFORGE_ANON_KEY`, `APAP_INSFORGE_SERVICE_KEY`. Required: `APAP_INSFORGE_URL=yes`, `APAP_INSFORGE_SERVICE_KEY=yes`, `APAP_INSFORGE_ANON_KEY=no`.
2. **Google OAuth** — `APAP_GOOGLE_CLIENT_ID`, `APAP_GOOGLE_CLIENT_SECRET`, `APAP_GOOGLE_REDIRECT_URI`. Required: `APAP_GOOGLE_CLIENT_ID=yes`, others `no` (defaults suffice for some flows).
3. **Session** — `APAP_SESSION_SECRET` (required `yes`, ≥32 chars).
4. **Bootstrap / RBAC** — `APAP_INITIAL_ADMIN_EMAIL` (required `no`; empty disables seeding).
5. **CSRF / Rate limit** — `APAP_CSRF_ENABLED`, `APAP_RATE_LIMIT_ENABLED`, `APAP_RATE_LIMIT_OAUTH_PER_MIN`, `APAP_RATE_LIMIT_WRITE_PER_MIN_USER`, `APAP_RATE_LIMIT_WRITE_PER_MIN_IP`, `APAP_TRUST_XFF`. Required: `yes` to keep the defaults sane; `APAP_TRUST_XFF=no` (set to `yes` only behind a trusted proxy).
6. **Auth cache + multi-worker** — `APAP_AUTH_CACHE_TTL_SECONDS` (default 300), `APAP_AUTH_CACHE_BACKEND` (default `in_process`, reject any other value). Required: defaults.
7. **Logging** — `APAP_LOG_LEVEL`, `APAP_DEBUG`, `APAP_MODE`. Required: `APAP_MODE=yes` for production (`web`), `APAP_DEBUG=no`. Per audit `auth-cache-in-process-audit-2026-Q3` the prod deploy runs `APAP_MODE=web`.
8. **E2E** — `APAP_E2E_AUTH_ENABLED`, `APAP_E2E_AUTH_SECRET`, `APAP_E2E_AUTH_DEFAULT_EMAIL`. Required: `APAP_E2E_AUTH_ENABLED=no` (production MUST be no; reference `app/core/config.py` E2E block).
9. **M0 local backend** — `APAP_LOCAL_BACKEND` (required `no` for prod; `yes` only for the dev/local self-host scenario), `APAP_LOCAL_DB_URL`, `APAP_LOCAL_DB_SCHEMA`, `APAP_INSFORGE_URL_OVERRIDE` (the local InsForge URL when M0 is active), `APAP_SMTP_HOST`, `APAP_SMTP_PORT`, `APAP_SMTP_USER`, `APAP_SMTP_PASSWORD`, `APAP_SMTP_FROM`, `APAP_APP_BASE_URL`. Each marked `Production=no` (Coolify deploy does NOT enable M0 local backend; magic-link verifies via InsForge production per M1 task T3.1).
10. **M1 magic-link** — `APAP_AUTH_ENABLE_MAGIC_LINK` (required `no` for prod; `yes` only for the local self-host dev scenario). References `app/core/auth_magic/routes.py` and the M1 spec.

Each block ends with a one-line `Default: <pydantic default>` line. Operator copies `.env.example` to `.env` and fills values.

### T2. Write `docs/runbooks/coolify-deploy.md`

Follow the 7-step structure from R2 verbatim:

1. **Pre-deploy checks** — list the 3 checks (env vars + healthcheck + verify-fallback-ready).
2. **Deploy** — reference `docs/development.md` §Dockerfile and the GitHub webhook path.
3. **Verify** — `/healthz` + OAuth end-to-end + log fields.
4. **M0 local backend** — note `APAP_LOCAL_BACKEND=false` for prod.
5. **M1 magic-link** — note `APAP_AUTH_ENABLE_MAGIC_LINK=false` for prod until M1.5.
6. **Rollback** — `git revert` recipe + `APAP_AUTH_CACHE_TTL_SECONDS=0` mention.
7. **Observability** — cross-references to `docs/codebase/operations.md` + `docs/codebase/security.md`.

Each env var mentioned in the runbook MUST hyperlink to `.env.example` or `docs/production-env.md`.

### T3. Write `docs/production-env.md`

Single-page table with one row per env var. Columns: `Var name`, `Concern`, `Doc anchor`, `Required?` (`yes`/`no` for prod), `Default`, `Startup check`. Sorted alphabetically within each concern section. Concerns mirror R1 groups.

### T4. Update `app/core/config.py::Settings.env_prefix` docstring

Currently:
```python
"""Runtime settings for the APAP_WEB application.

Environment variables are read with the ``APAP_`` prefix. For
example, ``APAP_INSFORGE_URL`` populates :attr:`insforge_url`.
"""
```

Update to:
```python
"""Runtime settings for the APAP_WEB application.

Environment variables are read with the ``APAP_`` prefix. For
example, ``APAP_INSFORGE_URL`` populates :attr:`insforge_url`.

Production operators: see ``docs/production-env.md`` for the
canonical reference of every APAP_* env var (concern, default,
required state, startup-config check) and the single-page
runbook ``docs/runbooks/coolify-deploy.md`` for the deploy
checklist. The repo-root ``.env.example`` lists every APAP_* in
template form for the local-dev ``.env`` workflow.
"""
```

No behavior change; this is a docstring-only update.

### Gate

- [x] `ruff check .` clean
- [x] `python scripts/check_module_size.py` clean (only `app/core/config.py::Settings.env_prefix` docstring touched — doc-only; pre-existing `migration/apply.py` + `migration/cli.py` violations unaffected)
- [x] `python scripts/check_mutation_sites.py` clean (pre-existing `insforge.py` + `migration/*` violations unaffected)
- [x] `python scripts/check_layers.py` clean
- [x] `python scripts/check_slice_completeness.py` OK
- [x] `python scripts/check_ruff_ratchet.py` (informational; pre-existing mismatch on the Ubuntu image, not introduced)
- [x] All M0+M1 pre-existing gates red remain red and unaffected
- [x] One commit `7a5e4d4 docs(m2-coolify-deploy): env template, deploy runbook, prod-env reference`; RDD lineage `review-3deb6ab9b7ed430f` opened at base-ref=1e2948e (post-M1-archive); 4 paths in scope (3 new docs + the docstring); single lens review-reliability capture pending (parent will capture); authoritative burnout follows.
