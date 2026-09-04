# Spec: M3 — Magic-link production wiring

## Intent

Wire the M1 magic-link flow into the production `app/main.py` so an operator can flip `APAP_AUTH_ENABLE_MAGIC_LINK=true` on Coolify and have a self-contained credential channel (no InsForge OAuth dependency) work end-to-end. The slice implements `SMTPMailTransport` (currently a placeholder), adds a `wire_magic_link_to_app_state(app, settings)` lifespan helper, and updates the `verify-fallback-ready` gate with a production round-trip check.

In scope: SMTPMailTransport, lifespan wiring, gate check, .env.example + runbook updates.
Out of scope: HTML email template, Redis auth cache, multi-replica, replacing the OAuth login page UI.

## Requirements

### R1. `SMTPMailTransport` sends a plain-text verify URL via SMTP

`app/core/auth_magic/mail_transports.py` MUST replace the `NotImplementedError` placeholder in `SMTPMailTransport.send_magic_link` with a real implementation:

- Read SMTP config from env: `APAP_SMTP_HOST` (required), `APAP_SMTP_PORT` (default 587), `APAP_SMTP_USER` (default empty = no auth), `APAP_SMTP_PASSWORD` (default empty = no auth), `APAP_SMTP_FROM` (default `noreply@apap.local`).
- Build the verify URL: `f"{base_url.rstrip('/')}/auth/magic/verify?token={raw_token}"`.
- Build a `MIMEText` message with subject `"APAP_WEB — inicia sesión"`, body containing the verify URL.
- Connect to the SMTP server. If `APAP_SMTP_PORT == 465`, use `SMTP_SSL`; otherwise use `SMTP` + `starttls()` when `APAP_SMTP_USER` is non-empty.
- Login if `APAP_SMTP_USER` is set, then `sendmail(APAP_SMTP_FROM, [email], msg.as_string())`.
- Run the synchronous I/O via `asyncio.to_thread(...)`.
- Raise a custom `SMTPTransportError(RuntimeError)` on failure (NOT a bare `RuntimeError` — so the F2 route can map it specifically).

### R2. Production lifespan wires magic-link state

`app/main.py::lifespan` MUST call a new `wire_magic_link_to_app_state(application, settings)` helper when `APAP_AUTH_ENABLE_MAGIC_LINK=true`. The helper:

- If `APAP_SMTP_HOST` is unset, log a warning and skip the wiring (the lifespan must not fail-fast on missing SMTP — the operator can still use the OAuth path).
- Otherwise:
  - Create `PostgresMagicLinkAdapter(dsn=APAP_LOCAL_DB_URL, search_path=APAP_LOCAL_DB_SCHEMA or None)`. The adapter's lazy DDL creates `magic_link_tokens` on first use.
  - Create `SMTPMailTransport()`.
  - Create an `InsForgeAuthUsersAdapter(application.state.insforge_client)` (reuses the existing adapter that already implements `get_user_by_email` against InsForge).
  - Attach all three to `application.state.magic_link_port`, `application.state.mail_transport`, `application.state.auth_port`.

The new helper MUST live in a new module `app/core/auth_magic/lifespan.py` (so the import does not bloat `app/main.py`).

### R3. `verify-fallback-ready` adds `check_magic_link_production_round_trip`

`migration/verify_fallback_ready.py` MUST add a new check that:

- Reads `APAP_AUTH_ENABLE_MAGIC_LINK` at check time. If unset/false, returns `PASS (skipped)` with evidence `"APAP_AUTH_ENABLE_MAGIC_LINK unset"`.
- Otherwise, spawns uvicorn with `app.core.local_backend.app:create_app --factory` (the local backend already wires magic-link state per F3). Set env: `APAP_AUTH_ENABLE_MAGIC_LINK=true`, `APAP_LOCAL_DB_URL`, `APAP_LOCAL_DB_SCHEMA`, `APAP_SMTP_HOST=<sandbox-smtp-server>`, `APAP_INSFORGE_URL=http://127.0.0.1:<port>/api`.
- Polls `/healthz` for 5 s. If 503 or timeout, returns `FAIL local backend did not become healthy on port <port> within 5s`.
- Inserts a temp user into `authorized_users` (via direct psycopg).
- POSTs `/auth/magic/start` with the temp user's email.
- Reads `tests/mailbox.jsonl` for the verify URL OR polls a sandbox SMTP server. The slice implementation defaults to `tests/mailbox.jsonl` (the same path F3 uses; if `APAP_MAILBOX_PATH` is set in env, the SMTPMailTransport writes there).
- Asserts `apap_session` cookie is set after consuming the verify URL.

Register the check in `CI_CHECKS` + `CI_CHECK_NAMES` + `ALL_CHECK_NAMES`.

### R4. `.env.example` flips magic-link flags for production

`.env.example` MUST:

- Move `APAP_AUTH_ENABLE_MAGIC_LINK` from "Production=no" to "Production=yes" (with the explanation: "When APAP_SMTP_HOST is also set, magic-link becomes the active credential channel. Operators switching off Google OAuth set APAP_GOOGLE_CLIENT_ID='' as well.").
- Restructure the `APAP_SMTP_*` block under "M1 magic-link" with all 5 vars and a one-line "Production required: yes (when APAP_AUTH_ENABLE_MAGIC_LINK=true)".

### R5. `docs/production-env.md` and `docs/runbooks/coolify-deploy.md` reflect the new flow

`docs/production-env.md` MUST:

- Update the `APAP_AUTH_ENABLE_MAGIC_LINK` row from `Required: no` to `Required: yes (when SMTP is configured)`.
- Add rows for `APAP_SMTP_HOST` (yes), `APAP_SMTP_PORT` (no, default 587), `APAP_SMTP_USER` (no), `APAP_SMTP_PASSWORD` (no), `APAP_SMTP_FROM` (no).

`docs/runbooks/coolify-deploy.md` MUST:

- Update section 5 ("M1 magic-link (POST-M1, MONITORING-ONLY)") to reflect that the flag is now production-ready.
- Add a "Switching from Google OAuth to magic-link" subsection with the env-var changes (set `APAP_GOOGLE_CLIENT_ID=''` and `APAP_AUTH_ENABLE_MAGIC_LINK=true` + SMTP block) and the verify-fallback-ready gate that confirms the round-trip.

## Acceptance scenarios

### AS1. SMTPMailTransport sends a real email via SMTP
- GIVEN a local SMTP server (e.g. `aiosmtpd` or `smtpd` from stdlib) listens on `127.0.0.1:8025`
- WHEN `SMTPMailTransport().send_magic_link("a@apap.local", "raw-token", "https://apap.example.org")` is awaited
- THEN the SMTP server receives exactly one message
- AND the message's `To:` header is `a@apap.local`
- AND the message's body contains the URL `https://apap.example.org/auth/magic/verify?token=raw-token`

### AS2. Production lifespan wires state when flag is set
- GIVEN `APAP_AUTH_ENABLE_MAGIC_LINK=true` and `APAP_SMTP_HOST=mail.example.com` are set
- WHEN `app/main.py::lifespan` runs
- THEN `app.state.magic_link_port` is a `PostgresMagicLinkAdapter` instance
- AND `app.state.mail_transport` is an `SMTPMailTransport` instance
- AND `app.state.auth_port` is an `InsForgeAuthUsersAdapter` instance
- AND `/auth/magic/start` returns 200 (not 503)

### AS3. Production lifespan skips magic-link state when SMTP is unset
- GIVEN `APAP_AUTH_ENABLE_MAGIC_LINK=true` and `APAP_SMTP_HOST` UNSET
- WHEN `app/main.py::lifespan` runs
- THEN a warning is logged `"APAP_AUTH_ENABLE_MAGIC_LINK=true but APAP_SMTP_HOST is unset; magic-link flow disabled, OAuth path still active"`
- AND `app.state.magic_link_port` is `None`
- AND `/auth/magic/start` returns 200 with `{"status": "queued"}` (the F2 no-op path)
- AND `/auth/callback` still works (OAuth path)

### AS4. Gate check round-trips against a real SMTP server
- GIVEN a local SMTP server on `127.0.0.1:8025` and `APAP_AUTH_ENABLE_MAGIC_LINK=true` and the migration gate runs
- WHEN `check_magic_link_production_round_trip` runs
- THEN it returns `PASS` with evidence containing `magic-link production round-trip: PASS`
- AND the SMTP server received exactly one message
- AND the message's body contained a `verify_url` that the test consumed via `/auth/magic/verify`

### AS5. `.env.example` documents the production flow
- GIVEN the operator runs `grep -E "Production required: yes" .env.example`
- WHEN the result is grep'd
- THEN the lines `APAP_AUTH_ENABLE_MAGIC_LINK`, `APAP_SMTP_HOST`, plus the existing required vars (`APAP_INSFORGE_URL`, `APAP_INSFORGE_SERVICE_KEY`, `APAP_GOOGLE_CLIENT_ID`, `APAP_GOOGLE_REDIRECT_URI`, `APAP_SESSION_SECRET`, `APAP_CSRF_ENABLED`, all `APAP_RATE_LIMIT_*`, `APAP_DEBUG`, `APAP_MODE`) all match

## Out of scope

- HTML email template (M3.1)
- DKIM/SPF signing (M3.1)
- Email throttling / bounce handling (M3.2)
- Custom login page UI that surfaces the magic-link form (the current `/login` is OAuth-only; the operator can either update the template in M3.1 or have users hit `/auth/magic/start` directly via API)
- Redis auth cache (M4)
- Multi-replica Coolify deploy (M4)
- Replacing the OAuth path (operator can leave both active; `/auth/callback` and `/auth/magic/*` coexist)

## Forecast

Forecast total ≤700 LOC additions plus ≤50 deletions.

## Gates

- `ruff check .` clean
- `python scripts/check_module_size.py` clean (each F3 file ≤700 lines)
- `python scripts/check_mutation_sites.py` clean (no new BASELINE entries)
- `python scripts/check_complexity.py` clean (no function CC>15)
- `python scripts/check_layers.py` clean
- `python scripts/check_slice_completeness.py` OK
- `uv run pytest tests/integration/test_magic_link_production.py tests/migration/test_magic_link_production_round_trip.py -v` all green where SMTP+Postgres are provisioned
- `python -m migration.cli_verify_fallback_ready --ci-only` exits 0 with the new `check_magic_link_production_round_trip` check (skipped when `APAP_AUTH_ENABLE_MAGIC_LINK` is unset)
- All M0+M1+M2 pre-existing gates red remain red and unaffected
- One commit; `gentle-ai review start` lineage burned

## Forecast risk

The slice touches auth code paths that already have a F1 carry-over of 23 informational findings. The new SMTP implementation adds 2–4 more findings (e.g. "sendmail exceptions are logged but not retried"; "MIME message charset is hardcoded to utf-8"). None are blockers.
