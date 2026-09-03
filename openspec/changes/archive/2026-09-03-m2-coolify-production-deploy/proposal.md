# Proposal: M2 — Coolify production deploy (env + runbook)

skill_resolution: paths-injected (sdd-propose)

## Why this slice

M0 (local backend) and M1 (magic-link) shipped with their slice-specific features but neither produced a single canonical `.env.example` document for the production deploy, nor a runbook that ties the existing Dockerfile + Coolify target + the new M0/M1 env flags together.

This slice closes that gap without re-architecting M0 or M1. The scope is bounded to documentation + one canonical env file:

1. `.env.example` at the repo root — documents every `APAP_*` env var with a one-line description, the default the pydantic-settings class ships with, the production-required value, and a comment linking to the doc section that explains the trade-off.
2. `docs/runbooks/coolify-deploy.md` — the deploy checklist operators run on Coolify: pull, env, healthcheck, log tail, rollback; references the existing `docs/development.md` build recipe and the existing `docs/audits/auth-cache-in-process-audit-2026-Q3.md` worker-count contract.
3. `docs/production-env.md` — short reference document linking each env flag to (a) the canonical doc that explains it, and (b) the runtime check that fires if it's missing or invalid (the startup-config-validator in `app/core/config.py`).

No new code paths. No Dockerfile changes. No ratchet-baseline modifications.

## What this slice does NOT do

- Real SMTP production wiring (M1.5 deferred; `SMTPMailTransport` placeholder remains in `app/core/auth_magic/mail_transports.py`).
- Multi-replica Coolify deploy (the audit `auth-cache-in-process-audit-2026-Q3` reports the prod deploy runs 1 replica; multi-replica requires Redis auth cache which is out-of-scope here).
- Dockerfile hardening (the existing multi-stage build is production-grade; this slice leaves the Dockerfile untouched).
- CI deploy job changes (`.github/workflows/deploy.yml` already targets Coolify; this slice does not modify it).

## Forecast

Forecast total ≤350 LOC additions plus ≤30 deletions across three doc/config files. The forecast is well under the 400-line hard cap.

- `.env.example` (new) — ~120 lines (one block per env var + a header + trailer)
- `docs/runbooks/coolify-deploy.md` (new) — ~140 lines
- `docs/production-env.md` (new) — ~70 lines
- `app/core/config.py` (modify) — ~10 lines (add doc-comment link to the new runbook in the `env_prefix` docstring)

Fits in one feature (no chain needed).

## Risk

- Doc rot: `.env.example` must track every new `APAP_*` env var declared in `app/core/config.py`. The slice establishes a 1:1 convention (each `SettingsConfigField` in config.py gets a matching `.env.example` block) but enforcement is manual. The slice ends with a CI-check sketch in tasks.md as a follow-up candidate.
- Operator confusion: a `.env.example` with 40 variables is intimidating at first read. The runbook groups them by concern (InsForge, session, M0 local-backend, M1 magic-link, E2E, RBAC, observability).
- Forward compat: when M2 → M3 (next slice, hypothetical) adds more env vars, `.env.example` updates accordingly.

## RDD binding

This slice ships under RDD. The orchestrator opens lineage with `--base-ref=1e2948e (the post-M1-archive commit) --workspace-overlay` so the lineage covers the M2 SDD files at capture time. Single lens `review-reliability`; one review capture is enough for a docs-only slice.
