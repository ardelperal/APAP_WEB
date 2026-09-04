# Proposal: M3 — Magic-link production wiring

skill_resolution: paths-injected (sdd-propose, web-tdd-philosophy)

## Why this slice

M2 (Coolify production deploy docs) shipped an `.env.example` and a runbook that explicitly mark `APAP_AUTH_ENABLE_MAGIC_LINK=false` for the Coolify production deploy. That was the right M2 call: M1's `SMTPMailTransport` was a `NotImplementedError` placeholder, and shipping a "magic-link in production" surface without a real SMTP transport would have been worse than the current state.

But the user can't log in on Coolify right now without the Google OAuth path through InsForge. The original M0 spec called out InsForge deprecation in 2026-Q3 — meaning the OAuth path is going away. We need a self-contained credential channel that works without an external OAuth provider.

This slice ships the production wiring of the M1 magic-link flow:

1. `SMTPMailTransport` is implemented with stdlib `smtplib` via `asyncio.to_thread` (no new dependencies).
2. The production `app/main.py::lifespan` wires the three ports (`magic_link_port`, `mail_transport`, `auth_port`) when `APAP_AUTH_ENABLE_MAGIC_LINK=true` and `APAP_SMTP_HOST` is set.
3. `auth_port` in production reuses the existing `InsForgeAuthUsersAdapter` (already implemented in `app/core/adapters/insforge/auth_insforge_adapter.py`) — no new auth port needed.
4. `magic_link_port` reuses the existing `PostgresMagicLinkAdapter` from M1 — but pointed at the local Postgres DSN (NOT InsForge). Production deploys would set `APAP_LOCAL_DB_URL` to a Postgres instance the operator manages alongside the app on Coolify.
5. The `verify-fallback-ready` gate adds a new check `check_magic_link_production_round_trip` that exercises the production flow against the deployed process (using the same spawn-uvicorn pattern as M0/F3).
6. `.env.example` and `docs/production-env.md` flip `APAP_AUTH_ENABLE_MAGIC_LINK` and the `APAP_SMTP_*` block from "Production=no" to "Production=yes when active" and add the new required vars.

## What this slice does NOT do

- Coolify-specific deploy workflow (the existing `.github/workflows/deploy.yml` is reused as-is; no new Coolify API surface).
- Multi-replica deploy (the audit `auth-cache-in-process-audit-2026-Q3` reports 1 replica + single worker; multi-replica requires Redis auth cache which is M4 work).
- Email templating (we send a plain-text message with the verify URL; HTML is M3.1).
- Auth cache Redis backend (M4).
- Switching the existing OAuth path off (M3 wires the alternative; the operator can run both paths concurrently by leaving `APAP_GOOGLE_CLIENT_ID` set).

## Relationship to the chain

- Builds on M1's `MagicLinkPort` + `PostgresMagicLinkAdapter` + `MailTransport` (F1, F2).
- Builds on M0's `LocalPostgresExecutor` (we reuse the `dsn + search_path` shape).
- Builds on M2's `.env.example` and runbook (we update them; the structure stays).
- Replaces the `SMTPMailTransport` placeholder from M1 with a real implementation.

## Forecast

Forecast total ≤700 LOC additions plus ≤50 deletions. Single feature (no chain needed because the change is dominated by the SMTP implementation + the lifespan wiring + the new gate check + the env-file updates — all in one logical unit).

- `app/core/auth_magic/mail_transports.py` — ~150 LOC (SMTPMailTransport real implementation)
- `app/core/auth_magic/lifespan.py` — ~70 LOC (new — `wire_magic_link_to_app_state(app, settings)` helper)
- `app/main.py` — ~25 LOC (call the helper from `lifespan`)
- `app/core/adapters/insforge/auth_insforge_adapter.py` — ~10 LOC (verify the existing adapter supports `get_user_by_email`; extend if needed)
- `migration/verify_fallback_ready.py` — ~80 LOC (new `check_magic_link_production_round_trip` + dispatch list)
- `tests/integration/test_magic_link_production.py` — ~120 LOC (AS10-equivalent: real SMTP loop with mock server)
- `tests/migration/test_magic_link_production_round_trip.py` — ~80 LOC (gate check atom)
- `.env.example` — ~50 lines added (SMTP block restructured; magic-link block marked yes)
- `docs/production-env.md` — ~40 lines added
- `docs/runbooks/coolify-deploy.md` — ~30 lines added (step 5 expanded)

Each file remains under 700 lines. The two largest (`mail_transports.py` and the new integration test) are at 70–80% of the budget; flag for F3.1 if a fourth file is added.

## Risk

- **SMTP infra decision**: this slice assumes the operator provides a working SMTP relay. Common choices: Mailgun, SES, MailPit (dev). The slice does NOT add a default relay; the operator configures via env.
- **Local Postgres**: magic-link tokens persist in a Postgres table (`magic_link_tokens`) that the F1 adapter creates lazily. The production deploy must wire `APAP_LOCAL_DB_URL` to a working Postgres (not InsForge). If the operator doesn't have one, magic-link doesn't work in production — but the OAuth path still does.
- **Email deliverability**: the plain-text verify URL might be flagged as spam. M3.1 add HTML template + DKIM/SPF hints.
- **Session secret rotation**: every production redeploy with a different `APAP_SESSION_SECRET` invalidates in-flight sessions. Already documented in M2's runbook; this slice does not change that.
- **Backward compat**: leaving the OAuth path on while wiring magic-link requires the lifespan to add magic-link state WITHOUT removing InsForge client. Both paths run concurrently; the operator decides which to surface on the login page (M3.1).

## RDD binding

This slice ships under RDD with one lineage opened AFTER the docs commit (so the SDD is in scope) and BEFORE the implementation commit (so the implementation is in scope). Single lens `review-reliability` for a docs+code slice; the 4-line summary is enough to burn the lineage.
