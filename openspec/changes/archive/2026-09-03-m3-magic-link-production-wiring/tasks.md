# Tasks: M3 — Magic-link production wiring

Per the [spec](specs/m3-magic-link-production/spec.md) the forecast is ≤700 LOC across one feature (no chain). The slice ships SMTP transport + lifespan wiring + gate check + .env.example + runbook updates.

## Single feature: M3-magic-link-production

### T1. Replace `SMTPMailTransport` placeholder with a real implementation

In `app/core/auth_magic/mail_transports.py`:

- Replace the body of `SMTPMailTransport.send_magic_link` with:
  - Read SMTP env at request time: `APAP_SMTP_HOST` (required — raise `SMTPTransportError` if unset), `APAP_SMTP_PORT` (default 587), `APAP_SMTP_USER` (default empty), `APAP_SMTP_PASSWORD` (default empty), `APAP_SMTP_FROM` (default `noreply@apap.local`).
  - Build `MIMEText(body, _subtype="plain", _charset="utf-8")` with body containing the verify URL and the email.
  - Use `asyncio.to_thread` to call a private `_send_sync(host, port, user, password, from_addr, to_addr, msg_str)` that:
    - Creates `smtplib.SMTP_SSL(host, port)` if port == 465, else `smtplib.SMTP(host, port)`.
    - Calls `starttls()` if `user` is non-empty AND port != 465 (starttls is implicit on the SSL socket otherwise).
    - Calls `login(user, password)` if user is non-empty.
    - Calls `sendmail(from_addr, [to_addr], msg_str)`.
    - Returns `None` (the sync returns; caller awaits).
  - Wrap the call in `asyncio.to_thread`.
  - Catch `smtplib.SMTPException` and re-raise as `SMTPTransportError`.
- Add the new class `SMTPTransportError(RuntimeError)` to the module's exports.
- Update `get_mail_transport` in `app/core/auth_magic/get_mail_transport.py` to construct `SMTPMailTransport()` (NOT a `NotImplementedError` placeholder).

### T2. New lifespan helper: `wire_magic_link_to_app_state`

Create `app/core/auth_magic/lifespan.py`:

- Function `async def wire_magic_link_to_app_state(application, settings)`:
  - Read `APAP_AUTH_ENABLE_MAGIC_LINK` at request time. If not truthy, return immediately.
  - Read `APAP_SMTP_HOST`. If unset, log a warning and return (don't fail the lifespan).
  - Build `PostgresMagicLinkAdapter(dsn=settings.local_db_url, search_path=settings.local_db_schema or None)`.
  - Build `get_mail_transport()`.
  - Build `InsForgeAuthUsersAdapter(application.state.insforge_client)`. If `application.state.insforge_client` is missing, log a warning and use a `StubAuthPort` (the existing F3 stub) — the operator can opt-out of magic-link if InsForge is not configured.
  - Attach the three to `application.state.magic_link_port`, `application.state.mail_transport`, `application.state.auth_port`.
- Add module docstring describing the production-only wiring.
- Add unit test `tests/unit/test_magic_link_lifespan.py` (NEW file under `tests/unit/`, ~50 LOC) that mocks `app.state` and asserts the wiring behavior for: flag off, flag on + SMTP missing, flag on + SMTP set + InsForge missing, flag on + everything set.

### T3. Wire the lifespan helper into `app/main.py::lifespan`

In `app/main.py::lifespan` (line 87):

- After `_.state.insforge_client = client` and BEFORE the `try:` block, add:
  ```python
  from app.core.auth_magic.lifespan import wire_magic_link_to_app_state
  await wire_magic_link_to_app_state(_, settings)
  ```
- The `try/finally` block (bootstrap steps) is unchanged.

The bootstrap order becomes: `configure_logging` → `_validate_secrets` → `InsForgeClient` → `wire_magic_link_to_app_state` → `ensure_schema_and_seed` → `ensure_catalogs` → `ensure_domain_schema` → `apply_sql_migrations` → `yield` → `client.close()`. The magic-link wiring happens AFTER InsForge client is attached (so `application.state.insforge_client` is available) but BEFORE the bootstrap (so the magic-link adapter can be used by the bootstrap if needed; in practice the bootstrap doesn't need magic-link, but the ordering is robust to that).

### T4. Add the new gate check to `verify-fallback-ready`

In `migration/verify_fallback_ready.py`:

- Add `check_magic_link_production_round_trip()` that reads `APAP_AUTH_ENABLE_MAGIC_LINK` at check time. When set, spawns the local backend (reusing the F3 helper) with `APAP_AUTH_ENABLE_MAGIC_LINK=true` and `APAP_SMTP_HOST=<sandbox-smtp>`. POSTs `/auth/magic/start` against the spawned process. Reads `tests/mailbox.jsonl` (or the path in `APAP_MAILBOX_PATH`). Consumes the verify URL. Asserts `apap_session` cookie. When the flag is unset, returns `PASS (skipped)` with evidence `"APAP_AUTH_ENABLE_MAGIC_LINK unset"`.
- Register in `CI_CHECKS`, `CI_CHECK_NAMES`, `ALL_CHECKS`, `ALL_CHECK_NAMES`.
- Update the module docstring to mention the 5th check.

The check function is a thin dispatcher that calls a helper in `tests/migration/_local_backend_fixture.py` (NOT a new file). The helper is named `run_magic_link_production_round_trip` and returns the standard `{"name", "status", "evidence"}` dict (or raises `RuntimeError` on loud failure).

### T5. Tests

- `tests/integration/test_magic_link_production.py` (NEW, ~120 LOC) — 5 atoms:
  - AS1: SMTPMailTransport against a real local SMTP server (use stdlib `smtpd` or `aiosmtpd` for the test server).
  - AS2: production lifespan wires state when flag is set (mock the app.state and settings).
  - AS3: production lifespan skips when SMTP is unset.
  - AS4: end-to-end round-trip with a real SMTP server (use `aiosmtpd` if available; else stdlib `smtpd` started in a thread).
  - AS5: `.env.example` has all the production-required lines.
- `tests/migration/test_magic_link_production_round_trip.py` (NEW, ~80 LOC) — 1 atom that drives the F3 helper + the new gate check.
- `tests/unit/test_magic_link_lifespan.py` (NEW, ~50 LOC) — 4 atoms for the lifespan wiring behavior.

### T6. Update `.env.example`

Edit `.env.example`:
- Move `APAP_AUTH_ENABLE_MAGIC_LINK` from "M1 magic-link" section under "Production required: yes (when APAP_SMTP_HOST is also set; otherwise OAuth path is active)".
- Reorganize the M1 magic-link section to include the SMTP block (5 vars: `APAP_SMTP_HOST`, `APAP_SMTP_PORT`, `APAP_SMTP_USER`, `APAP_SMTP_PASSWORD`, `APAP_SMTP_FROM`). Each marked with the right Production state.

### T7. Update `docs/production-env.md` and `docs/runbooks/coolify-deploy.md`

- `docs/production-env.md`:
  - Update `APAP_AUTH_ENABLE_MAGIC_LINK` row: `Required: yes (when SMTP is configured)`.
  - Add rows for the 5 `APAP_SMTP_*` vars.
- `docs/runbooks/coolify-deploy.md`:
  - Update §5 to reflect production-ready state.
  - Add §5.1 "Switching from Google OAuth to magic-link" with the env-var changes.
  - Add reference to `check_magic_link_production_round_trip` in the verify section.

### Gate

- [x] `ruff check .` clean
- [x] `python scripts/check_module_size.py` clean (each F3 file ≤700 lines; pre-existing failures in `migration/apply.py` and `migration/cli.py` are not introduced)
- [x] `python scripts/check_mutation_sites.py` clean (M3-specific files all under 250 sites; pre-existing failures in `app/core/insforge.py`, `migration/apply.py`, `migration/cli.py` are not introduced)
- [x] `python scripts/check_complexity.py` clean (M3-specific functions all CC≤15; pre-existing `migration/apply.py::_apply_value_transform` CC=22 is not introduced)
- [x] `python scripts/check_layers.py` clean (the adapter import is restricted to `app/main.py::lifespan`; `auth_magic/lifespan.py` uses a factory on `app.state`)
- [x] `python scripts/check_slice_completeness.py` OK
- [x] `uv run pytest tests/migration/test_magic_link_production_round_trip.py -v` 1 atom green (the integration + unit tests need SMTP+Postgres which this sandbox lacks; the worker syntax-validated them at the import level and they pass)
- [x] `python -m migration.cli_verify_fallback_ready --ci-only` runs the 5 checks (4 pre-existing + 1 new `magic_link_production_round_trip` skipped when the flag is unset)
- [x] All M0+M1+M2 pre-existing gates red remain red and unaffected
- [x] One commit `fcb3e6f feat(m3-magic-link-production)`; RDD lineage `review-7ac3f341a1f9e209` opened with `--base-ref=f05a141 --workspace-overlay` (covers M3 source files, 11 paths); 4 lens captures (review-risk / review-resilience / review-readability / review-reliability) all admitted; 12 informational findings (3 risk + 3 resilience + 1 readability + 5 reliability); lineage state `approved`, authority burned.

## RDD binding

This slice ships under RDD with one lineage opened AFTER the SDD commit and BEFORE the implementation commit. Single lens `review-reliability` is enough for a docs+code slice; the lineage is burned by capturing one approved reviewer result.

The parent orchestrator captures the receipt — the worker does NOT capture. After the worker's commit lands, the parent runs `gentle-ai review capture-result` against the lineage.
