# Spec: M2 — Coolify production deploy (env + runbook)

## Intent

Provide a single canonical reference for the production deploy on Coolify: one `.env.example` at the repo root that lists every `APAP_*` env var the operator must set, one runbook at `docs/runbooks/coolify-deploy.md` that describes the deploy + verify + rollback steps, and one short reference at `docs/production-env.md` that maps each env flag to its doc and its startup-config-validator rule.

The slice is bounded to docs + one example file + one minimal in-source docstring edit. No new code paths, no Dockerfile changes, no ratchet-baseline modifications.

## Requirements

### R1. `.env.example` documents every `APAP_*` env var

A new file `.env.example` at the repo root MUST be committed and MUST contain one block per `APAP_*` env var declared in `app/core/config.py`. Each block MUST:

- Render an empty value (the file is a template; the operator copies it to `.env` and fills values).
- Include a one-line comment describing the variable in the imperative form (e.g. "Google OAuth 2.0 client ID").
- Include a `Default:` line that mirrors the pydantic-settings class default.
- Include a `Production required:` line marking the variable as `yes` or `no` per the startup-config-validator behavior.
- Group variables by concern in fixed sections:
  1. InsForge (URL, anon key, service key)
  2. Google OAuth (client id, secret, redirect URI)
  3. Session (session secret)
  4. RBAC / bootstrap (initial admin email)
  5. CSRF (csrf enabled)
  6. Rate limiting (per-IP / per-user limits + trust_xff)
  7. Logging (log level + debug)
  8. E2E (e2e enabled, e2e secret, e2e default email) — marked "Production MUST be no" with a 1-line explanation
  9. Local backend (M0): `APAP_LOCAL_BACKEND`, `APAP_LOCAL_DB_URL`, `APAP_LOCAL_DB_SCHEMA`, `APAP_INSFORGE_URL`, `APAP_SMTP_HOST` (M1.5 placeholder), `APAP_APP_BASE_URL`
  10. Magic-link (M1): `APAP_AUTH_ENABLE_MAGIC_LINK`

The `.env.example` MUST NOT be loaded by the app at runtime — `pydantic-settings` reads `.env` only (the operator copies `.env.example` to `.env` and edits). The `.env.example` file's only job is documentation.

The block ordering MUST be: by setting module section, then alphabetical within section.

### R2. `docs/runbooks/coolify-deploy.md` walks the deploy + verify + rollback

A new file `docs/runbooks/coolify-deploy.md` MUST walk the operator through:

1. **Pre-deploy checks** — verify the Coolify target has the expected env vars set (cross-reference `docs/production-env.md`); verify `Dockerfile` builds cleanly (point at `docs/development.md` §Dockerfile); verify `verify-fallback-ready --ci-only` exits 0 against the InsForge prod URL.
2. **Deploy** — `git push origin feat/<branch>` (or `main` if post-merge); Coolify auto-detects via the GitHub webhook (`.github/workflows/deploy.yml`); first Coolify build compiles CSS + the Python wheel (multi-stage); second container starts `uvicorn` with the Dockerfile `CMD`.
3. **Verify** — `GET /healthz` returns `{"status": "ok", "app": "APAP_WEB"}` from the process; `GET /` redirects unauthenticated users to `/login`; a known `usuarios_autorizados` row can complete the OAuth flow end-to-end; the structured-log fields are emitted (mention `app.core.logging.log_safe`).
4. **M0 local backend** — when `APAP_LOCAL_BACKEND=true`, the same process now ALSO wires the local-backend dependency for backward compat with the magic-link flow (see M1 spec R5/R6 + R7). The runbook MUST document that the prod deploy sets `APAP_LOCAL_BACKEND=false` and that the magic-link flow falls back to InsForge production.
5. **M1 magic-link** — when `APAP_AUTH_ENABLE_MAGIC_LINK=true`, the magic-link flow issues `apap_session` cookies via `app/core/auth_magic/ConsoleMailTransport` + Postgres `magic_link_tokens` table. The runbook MUST document that prod deploys set this to `false` until M1.5 ships the SMTP wiring (the `SMTPMailTransport` placeholder remains in place).
6. **Rollback** — `git revert <deploy-sha>` and `git push origin main` triggers a Coolify rebuild with the previous image; the deploy job takes ~3 min; `apap_session` cookies issued under the new image MAY invalidate (set `APAP_AUTH_CACHE_TTL_SECONDS=0` to revoke immediately on rollback). The runbook cross-references `docs/runbooks/auth-cache-multi-worker.md`.
7. **Observability** — JSON stdout logs are aggregated by Coolify's log collector; the runbook cross-references `docs/codebase/operations.md` and `docs/codebase/security.md`.

The runbook MUST NOT include any new env var beyond what R1 documents. All env vars referenced in the runbook MUST point at `.env.example` for default + production-required state.

### R3. `docs/production-env.md` is the operator's short reference

A new file `docs/production-env.md` MUST be a single-page reference with one row per `APAP_*` env var:

- **Var name** (the `APAP_*` identifier)
- **Concern** (which section from R1 it belongs to)
- **Doc anchor** (the docs/ file that explains the trade-off)
- **Required?** — `yes`/`no` for production deploy
- **Default** — the pydantic-settings default
- **Startup check** — which `app/core/config.py::StartupConfigError` rule fires when missing or invalid

The table MUST be sorted alphabetically within each concern section.

### R4. `app/core/config.py` env-prefix docstring updated

The docstring of `Settings` (currently a one-liner) MUST grow to ONE additional paragraph pointing operators at `docs/production-env.md` and `.env.example`. No behavior change.

## Acceptance scenarios

### AS1. `.env.example` lists every APAP_* env var
- GIVEN the contents of `app/core/config.py::Settings`
- WHEN the operator greps `.env.example` for the pydantic field names
- THEN each field has a corresponding block (with `Default:` + `Production required:` lines)
- AND `APAP_E2E_AUTH_ENABLED` is marked `Production MUST be no` with a 1-line explanation

### AS2. Runbook links env vars to their doc anchors
- GIVEN `docs/runbooks/coolify-deploy.md`
- WHEN an operator grep-searches for `APAP_*` references
- THEN every env var referenced has a hyperlink to either `.env.example` or `docs/production-env.md`
- AND no env var is introduced in the runbook that is not in `.env.example`

### AS3. `docs/production-env.md` covers every env var
- GIVEN the union of env vars in `app/core/config.py` AND any new APAP_* env var added by M0 (LOCAL_*) or M1 (AUTH_ENABLE_MAGIC_LINK)
- WHEN the operator grep-searches `docs/production-env.md`
- THEN every var has a row in the table

### AS4. Doc-only slice keeps the gate suite green
- GIVEN the existing CI / linter / ratchet suite
- WHEN the M2 commit lands
- THEN `ruff check .` is clean
- AND `check_module_size.py` is clean (no source-module lines touched beyond the docstring)
- AND `check_mutation_sites.py` is clean
- AND `check_layers.py` is clean
- AND `check_slice_completeness.py` is OK
- AND `tests/conftest.py` is unchanged

### AS5. Coolify deploy audit-compatible
- GIVEN the audit `docs/audits/auth-cache-in-process-audit-2026-Q3.md` lists the contract for the production deploy
- WHEN an operator runs through `docs/runbooks/coolify-deploy.md`
- THEN every contracted item from the audit is addressed (1 replica, single worker, `APAP_AUTH_CACHE_TTL_SECONDS` ≥ 0).

## Out of scope

- Dockerfile changes
- Coolify stack/deploy workflow changes (`.github/workflows/deploy.yml`)
- Real SMTP wiring for the magic-link flow (M1.5 follow-up)
- Redis auth-cache backend (multi-replica)
- E2E deploy verification
- New env vars beyond the `APAP_*` namespace

## Forecast

Forecast total ≤350 LOC additions plus ≤30 deletions across three doc/config files.

## Gates

- `ruff check .` clean
- `python scripts/check_module_size.py` clean (the only source-module change is the `Settings` docstring in `app/core/config.py`; doc-only)
- `python scripts/check_mutation_sites.py` clean
- `python scripts/check_layers.py` clean
- `python scripts/check_slice_completeness.py` OK
- `python scripts/check_ruff_ratchet.py` (informational; pre-existing mismatch on the Ubuntu image, not introduced by this slice)
- All M0+M1 pre-existing gates red remain red and unaffected by this slice
- One commit; `gentle-ai review start` lineage burned

## Forecast risk

The slice is doc-only; no behavior change. The cost is reviewer time on a 350-LOC diff and operator onboarding improvement.
