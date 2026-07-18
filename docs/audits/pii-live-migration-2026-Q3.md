# PII Audit — Live Migration (2026 Q3, PR4b)

> **Verdict**: PASS
> **Scope**: M1 forward migration PII surface (legacy → web); authenticated
> photo display route; storage redaction invariants; `log_safe` redaction
> list. **Out of scope**: M2 reverse path (PR6/PR7), production release
> tags, public galleries, anonymization, encryption-at-rest beyond InsForge
> defaults.

## Scope

### PII columns in scope

| Column    | Source (legacy)               | Web column   | web_only_strategy | Forward path             |
|-----------|-------------------------------|--------------|-------------------|--------------------------|
| `email`   | `TbVoluntariosParaAutorrellenables.Email` | `voluntarios.email` | mapped 1:1        | forward + reverse        |
| `tel1`    | `TbVoluntariosParaAutorrellenables.Tel1`  | `voluntarios.tel1`  | mapped 1:1        | forward + reverse        |
| `tel2`    | `TbVoluntariosParaAutorrellenables.Tel2`  | `voluntarios.tel2`  | mapped 1:1        | forward + reverse        |
| `dni`     | (NO legacy column — verified via Dysflow `get_schema` on 2026-07-11) | `voluntarios.dni` | `preserve` (web-only shadow; round-trip) | NEVER forward-migrated; preserved on web-side; reverse-path collision is recorded as `needs_review` |

> **Why no `DNI` column in legacy.** `TbVoluntariosParaAutorrellenables`
> returns exactly four columns (`Voluntario, Tel1, Tel2, Email`, all
> `type=10 text size=255`). Any future claim that DNI exists in this
> legacy table MUST be re-verified via the same Dysflow `get_schema`
> tool. The `migration/mappings/voluntario.yaml` mapping already encodes
> this reality (`DNI` has `legacy_column: null`,
> `web_only_strategy: preserve`).

### Display routes in scope (PII can be reached via these)

| Route                                  | Auth required | Without session |
|----------------------------------------|---------------|-----------------|
| `GET /voluntarios`                     | yes           | 302 `/login`    |
| `GET /voluntarios/{id}`                | yes           | 302 `/login`    |
| `GET /animales`                        | yes           | 302 `/login`    |
| `GET /animales/{animal_id}` (UUID)     | yes           | 302 `/login`    |
| `GET /animales/{animal_id}/foto` (UUID)| yes           | 302 `/login`    |
| `GET /entradas`                        | yes           | 302 `/login`    |
| `GET /login`                           | no            | 200            |

`PUBLIC_PATHS` at `app/main.py:148` is the closed set of
intentionally-unauthenticated endpoints: `{/healthz, /login,
/auth/google, /auth/callback, /logout}` (5 entries). Only `/login`
exposes application content; the other four are protocol/operational
surfaces (liveness probe, OAuth flow start, OAuth callback, session
clear) that do not leak PII by design.

### Storage in scope

- `apap-photos` private bucket (`isPublic=false`); pre-flight invariant
  is `isPublic == False` and the apply aborts on `True` or absent.
- Object keys are client-derived as `<sha256>.<ext>` (SHA-256 of the
  bytes + detected extension). Server may rename on collision; the
  canonical key is the `key` field returned by the upload-strategy.
- `animales.nombrefoto` stores the **returned** key (not the legacy
  filename, not the proposed key if the server renamed).
- Sentinel `__missing__` is set when the source photo is missing,
  corrupt, or unsupported; the route serves a 1x1 PNG placeholder
  without any storage I/O.

### Redaction list (`app/core/logging.py::REDACTED_FIELDS`)

After PR4b the closed list has 15 entries: `email, session_token, jwt,
oauth_code, pkce_verifier, csrf_token, pkce_challenge, authorization,
cookie, referer, ip_address, x_forwarded_for, dni, tel1, tel2`.
Comparison is case-insensitive and treats `-` and `_` as equivalent.

## Methodology

Six invariants are pinned by automated atoms. Each atom is a fixture
that pre-loads the relevant fake, exercises the contract, and asserts
the post-state with a concrete value (not absence-of-error).

1. **Redaction list shape** — `tests/test_logging.py` +
   `tests/test_log_safe_redaction.py` (15 atoms after parametrization
   expansion). The list has exactly 15 entries; every new PII field
   (`dni`, `tel1`, `tel2`) is present; mixed-case variants
   (`DNI`, `Tel1`, `TEL2`) are redacted; descriptive names that merely
   CONTAIN a redacted substring (`dni_lookup_table`,
   `telefono_secundario`) pass through unchanged.
2. **Authorization invariant** —
   `tests/test_animals_foto_route.py::TestFotoRouteAuthorizationInvariant`
   pins that an anonymous request redirects to `/login` BEFORE
   any DB or storage call. No SQL queries, no storage calls.
3. **No-presigned-URL leak** —
   `tests/test_animals_foto_route.py::TestFotoRouteDoesNotLeakPresignedUrl`
   pins that no header or body of the response ever contains the
   storage URL or any presigned token, even when the storage
   surface raised with that URL in its error body.
4. **Fail-closed on every storage-stream error category** —
   `tests/migration/test_insforge_storage_methods.py` parameterises
   401, 403, 404, 405, 500 on the upload strategy; `download_object_stream`
   raises `InsForgeError` on 401/404/5xx and `httpx.TimeoutException` on
   network timeout. The route layer's
   `tests/test_animals_foto_route.py::TestFotoRouteMidStreamFailClosed`
   covers four placeholder emission paths: streamed-GET 5xx
   (`test_foto_route_placeholder_when_streamed_get_5xx_on_first_chunk`),
   mid-iteration network drop
   (`test_foto_route_placeholder_when_stream_mid_iteration_network_error`),
   streamed-GET succeeds for headers but fails on first-iteration
   (`test_foto_route_placeholder_when_stream_fails_on_first_iteration`),
   and per-chunk read timeout
   (`test_foto_route_placeholder_on_per_chunk_timeout`). The route
   consumes the storage generator eagerly so a mid-stream
   `PhotoStreamError` always becomes the placeholder PNG — never a 5xx.
   The service-level wrapping is pinned by
   `tests/test_animals_foto_route.py::TestFotoServiceMidStreamWrapping`.
   **PR4b 4R WARN-3:** unexpected exceptions on the animales SELECT
   (`animals_service.get_animal_by_id`) ALSO fail closed to the
   placeholder, for consistency with the storage-stream contract.
   `tests/test_animals_foto_route.py::TestFotoRouteSqlLookupFailClosed`
   pins both `InsForgeError` (transport-flavoured) and a non-InsForge
   `RuntimeError` (invariant-violation-flavoured). The error is
   recorded via `log_safe("animal_foto.sql_lookup_failed", reason=...)`
   so the operator still sees it in the audit stream. A genuinely
   missing animal (the service returns `None`) STILL surfaces as 404
   because the absence is a domain signal, not a transport failure.
5. **Idempotent upload** —
   `tests/migration/test_insforge_storage_methods.py::test_upload_object_reuses_existing_key_via_client_derived_filename`
   asserts the same bytes uploaded twice carry the same client-side
   filename so server-side dedup can fire.
6. **No raw `logger.*` / `print(...)` in `app/core/insforge.py`** —
   `tests/migration/test_insforge_storage_methods.py::test_storage_methods_never_log_secrets_urls_or_paths`
   uses the AST detector from `scripts/check_rules.py` (the same
   detector that runs in CI) to pin the absence of forbidden logging
   patterns in the production storage surface.

In addition, the operator runbook
`docs/runbooks/live-migration-apply.md` carries the canonical
operator workflow; `tests/test_runbook_links.py` pins that every
operator-facing runbook reference resolves to an authored file
with the AGENTS.md §13 headings (`## When to trigger`,
`## Pre-deploy checklist`, `## Deploy steps`, `## Verification`,
`## Rollback`).

## Findings

| Severity | Finding                                                                                  | Evidence                                                                                          | Status     |
|----------|-------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------|------------|
| P0       | None — no critical findings.                                                              | n/a                                                                                               | n/a        |
| P1       | None — no high-severity findings.                                                          | n/a                                                                                               | n/a        |
| P2       | Sentinel placeholder is a static 1x1 transparent PNG; users see no "broken image" hint.   | `app/modules/animals/routes.py::_PLACEHOLDER_PHOTO_PNG`; `app/modules/animals/photo_service.py::SENTINEL_KEY`. UX improvement, not a security defect. | Acknowledged (out of PR4b scope) |
| P2       | `delete_object` 404 returns `None` (idempotent) — if the operator logs the return value they see no signal of "already absent". | `tests/migration/test_insforge_storage_methods.py::test_delete_object_404_is_idempotent_noop`. No PII or secret leakage; only operator UX. | Acknowledged (out of PR4b scope) |
| P3       | `content_type_for_key` falls back to `application/octet-stream` for unknown extensions; browsers will download instead of inline. | `app/modules/animals/photo_service.py::content_type_for_key`. Defensive default, no security impact. | Acknowledged |
| P3       | `voluntarios.dni` is web-only shadow (verified via Dysflow `get_schema` 2026-07-11: zero DNI column in `TbVoluntariosParaAutorrellenables`). Forward legacy apply MUST leave `dni=NULL`; collisions only arise from manual web entry (UNIQUE constraint) or reverse-path (no legacy column to receive). | `migration/mappings/voluntario.yaml` (`DNI: legacy_column: null`); `tests/test_log_safe_redaction.py::test_log_safe_redacts_each_new_pii_field_value[dni]`; the `dni` row in the Scope table above. | By design — preserves P1 fidelity to the verified legacy schema |
| P3       | Audit doc rendered in English per artifact default; the project's preferred register for operator docs is castellano de España. The default (English) was chosen because the artifact-language rule (technical artifacts default to English unless the project explicitly requests another language) takes precedence over the operator-doc preference for this audit. | `docs/audits/pii-live-migration-2026-Q3.md` (this file). | Acknowledged — operator may request a castellano render in a follow-up |

## Verdict

**PASS** — every PR4b PII control is pinned by an automated atom.
The M1 milestone gate accepts the PII contract on the basis of:

- The closed redaction list (15 entries) is verified end-to-end by
  parametrized atoms in `tests/test_log_safe_redaction.py` (**15
  atoms** after parametrization: 1 list-shape invariant + 3
  per-field-presence + 3 per-field-redaction + 6 mixed-case variants +
  1 record-message non-leak + 1 descriptive-name passthrough).
- The `GET /animales/{animal_id}/foto` route is verified by
  `tests/test_animals_foto_route.py` (**18 atoms** across 5 classes:
  `TestFotoRouteAuthAndRouting` 6, `TestFotoRouteDoesNotLeakPresignedUrl`
  1, `TestFotoRouteIsolatedService` 1, `TestFotoRouteAuthorizationInvariant`
  1, `TestFotoRouteMidStreamFailClosed` 4, `TestFotoRouteSqlLookupFailClosed`
  2, `TestFotoServiceMidStreamWrapping` 3).
- The production storage methods on `InsForgeClient` are verified by
  `tests/migration/test_insforge_storage_methods.py` (**30 atoms**:
  happy/sad/edge for upload_object (4 + 6 parametrized fail-closed +
  transfer/confirm/network), download_object_stream (7 + 2 per-chunk
  timeout), delete_object (3); unsafe-bucket pre-network × 3;
  idempotent re-upload; bearer auth on the strategy request; AST
  detector pins the absence of forbidden logging patterns).
- The migration operator path is documented in
  `docs/runbooks/live-migration-apply.md` with the AGENTS.md §13
  headings and the `MIGRATION_RUNBOOK_REF` constant surfaces this
  canonical path on every typed-exception line. The PR4b-specific
  photo display + storage sections extend that runbook on top of
  the existing apply / pre-flight / rollback / escalation sections.

### Acceptance evidence index

| Invariant                                              | Atom file                                            | Atoms |
|--------------------------------------------------------|------------------------------------------------------|-------|
| REDACTED_FIELDS has exactly 15 entries                 | `tests/test_log_safe_redaction.py`                   | 1     |
| Each new PII field is in the closed list               | `tests/test_log_safe_redaction.py`                   | 3     |
| `log_safe` redacts each new field value                | `tests/test_log_safe_redaction.py`                   | 3     |
| Mixed-case variants are redacted                       | `tests/test_log_safe_redaction.py`                   | 6     |
| PII never leaks via the formatted message              | `tests/test_log_safe_redaction.py`                   | 1     |
| Descriptive names pass through unchanged               | `tests/test_log_safe_redaction.py`                   | 1     |
| Storage methods happy/sad/edge                         | `tests/migration/test_insforge_storage_methods.py`   | 30    |
| Per-chunk read timeout pins ``connect=5/read=10/...``  | `tests/migration/test_insforge_storage_methods.py`   | 1     |
| Stalled stream surfaces `httpx.TimeoutException`       | `tests/migration/test_insforge_storage_methods.py`   | 1     |
| Auth gate redirects anonymous to `/login`             | `tests/test_animals_foto_route.py`                   | 2     |
| Animal-not-found returns 404                          | `tests/test_animals_foto_route.py`                   | 1     |
| Route streams bytes for real keys                     | `tests/test_animals_foto_route.py`                   | 1     |
| Sentinel + null → placeholder, no I/O                 | `tests/test_animals_foto_route.py`                   | 2     |
| Storage error → placeholder (fail-closed)             | `tests/test_animals_foto_route.py`                   | 1     |
| Mid-stream error → placeholder (CRIT-1, 4R)            | `tests/test_animals_foto_route.py`                   | 4     |
| SQL lookup error → placeholder (WARN-3, 4R)            | `tests/test_animals_foto_route.py`                   | 2     |
| `stream_animal_photo` wraps mid-stream errors         | `tests/test_animals_foto_route.py`                   | 3     |
| No presigned URL leak                                 | `tests/test_animals_foto_route.py`                   | 1     |
| Service isolation (no photo/bucket SQL)                | `tests/test_animals_foto_route.py`                   | 1     |
| Audit doc structure (Scope / Methodology / ...)        | `tests/test_pii_audit_doc.py`                        | 7     |
| Runbook references resolve to authored files           | `tests/test_runbook_links.py`                        | 12    |

## PR5 Additions (2026-07-15)

PR5 (`feat/migration-pr5-pii-controls`, PR #196) re-scopes the
M1 collision contract and adds five new PII controls on top of
the PR4b surface. This section enumerates the new invariants,
the new tests, and reconfirms the verdict.

### New invariants

| Invariant | Surface | Where it lives |
|---|---|---|
| Per-table counter wiring with DI seam | `apply_legacy_to_web(dni_collision_counter: DniCollisionCounter \| None = None)` exposes the counter for the PR6 reverse applier; the forward applier never bumps it (legacy has no DNI). | `migration/apply.py` signature; `migration/dni_collision.py::DniCollisionCounter`; `tests/migration/test_dni_collision.py::test_forward_legacy_produces_zero_dni_collisions` pins the zero-bump contract. |
| `--filter-direction {legacy-to-web, web-to-legacy, both}` CLI flag | Defaults to `"both"` so PR4 callers see the same combined listing; PR5 adds the narrowing path. | `migration/cli.py::build_parser` + `migration/shadow_state.py::list_needs_review(origin_direction=...)`. |
| `PUBLIC_PATHS` 5-entry shape pinned | Exactly `{/healthz, /login, /auth/google, /auth/callback, /logout}`; no PII route is in the set. | `app/main.py:148`; `tests/test_public_paths.py::EXPECTED_PUBLIC_PATHS`. |
| `_is_pii_web_column` / `_mask_pii_value` CLI helpers | Apply the closed-list comparison against `web_column` to keep the operator stdout free of raw PII. | `migration/cli.py`; consumed by both formatters. |
| 5-route 302-to-`/login` parametrisation | Every PII-displaying route (`/voluntarios`, `/voluntarios/{id}`, `/animales`, `/animales/{id}/foto`, `/entradas`) returns 302 to `/login` without a session. | `tests/test_public_paths.py::PII_ROUTES_PARAMETRIZE`; the route layer at `app/modules/*/routes.py`. |
| `origin_direction` stamp on `list_needs_review` rows | Every listed row carries the producer direction so the operator dashboard can route by migration scope. | `migration/shadow_state.py::list_needs_review` sets `row["origin_direction"] = "legacy-to-web"` by default; PR6 reverse applier will start stamping `"web-to-legacy"`. |
| `record_dni_collision(direction=...)` persists `origin_direction` | The `direction` kwarg is persisted verbatim on the shadow row (`origin_direction` column carries a closed three-value CHECK: `legacy-to-web`, `web-to-legacy`, `web-only`). | `migration/dni_collision.py::record_dni_collision`; `migration/shadow_state.py::ShadowStateRepository.upsert(origin_direction=...)`. |
| `legacy_pk` / `web_pk` PII masking in CLI output | A new `_looks_like_pii(value)` helper matches DNI / email / phone regexes and masks the value to `[REDACTED]`; UUIDs and NCHIPs do not match and pass through unchanged. | `migration/cli.py::_PII_VALUE_PATTERNS` + `_looks_like_pii`; consumed by `_format_row_for_check_only` and `_format_row_for_interactive`. |
| `derived_value` PII masking in CLI output | Same closed-list comparison as `preserved_value`: when `web_column` is in `REDACTED_FIELDS`, `derived_value` is masked to `[REDACTED]`. | `migration/cli.py` formatters; `tests/migration/test_pii_redaction.py::test_cli_reconcile_check_only_output_has_no_raw_pii` pins the contract. |

### New tests (29 atoms + 3 CLI atoms)

| Suite | Atoms | Coverage |
|---|---|---|
| `tests/migration/test_pii_redaction.py` | 10 | log_safe redaction on `sync.applied` payload (parametrised over 4 PII fields); shadow `preserved_value` masking; `MigrationReport.to_json()` no-PII regex; CLI stdout no-PII (including the new `derived_value` masking); redaction-list-covers-all-PII (parametrised over the full closed list); synthetic-payload-emits-redacted-payload; collision-marker-in-log-payload. |
| `tests/migration/test_dni_collision.py` | 9 | Forward-zero-collision (wires the DI seam); web-only shadow routing (asserts `origin_direction="web-only"`); reverse-path counter increment (asserts `origin_direction="web-to-legacy"`); interactive CLI resolution; helper invariants (NOW default, first-wins-does-not-overwrite); counter initial state; CLI parser `--filter-direction` surface (default `"both"`). |
| `tests/test_public_paths.py` | 10 | PUBLIC_PATHS 5-entry shape invariant; `_is_public_path` recognition; no-PII-route-in-PUBLIC_PATHS; parametrised 302-to-`/login` over 5 PII routes; `/healthz` and `/login` happy-path sanity. |
| `tests/migration/test_cli.py` | 3 new atoms | `--filter-direction` default (`both`); `--filter-direction legacy-to-web` narrowing; `--filter-direction web-to-legacy` empty-listing in PR5. |

### Verdict (re-confirmed)

**PASS** for M1 forward path. The collision-routing helper
(`migration/dni_collision.py::record_dni_collision`) is fully
unit-tested (9 atoms covering both scopes, the counter increment,
and the helper invariants) but is **NOT invoked by the forward
applier** — legacy `TbVoluntariosParaAutorrellenables` has no `DNI`
column (Dysflow-verified 2026-07-11). The DI seam
`apply_legacy_to_web(dni_collision_counter=...)` is wired today
so the PR6 reverse applier can invoke the helper on
`web-to-legacy` collisions; the seam is exercised by the
zero-bump atom in `tests/migration/test_dni_collision.py`.

### PR6 Additions (2026-07-18, reverse apply + round-trip)

PR6 (`feat/live-migration-reverse-apply`) ships the symmetric
`apply_web_to_legacy` path and adds five round-trip invariants
on top of the PR5 surface. This section enumerates the new
invariants, the new tests, and reconfirms the verdict.

#### New invariants

| Invariant | Surface | Where it lives |
|---|---|---|
| `apply_web_to_legacy(client, table_name, *, web_snapshot, dry_run, lock_path)` is a public reverse-applier entry point | Reuses `execute_legacy_sql` (PR1) and a new symmetric `execute_legacy_write` seam (`migration.dysflow_client.execute_legacy_write`); MSACCESS pre-flight + lock + snapshot all mirror the forward path | `migration/apply_reverse.py`; `migration/dysflow_client.py::execute_legacy_write`; `migration/legacy_reader.py::set_legacy_write_executor` |
| `migration.semantic_events.record_lifecycle_reversed(...)` emits a `LIFECYCLE_REVERSED` event with `source_direction="web-to-legacy"` | Reverse applier invokes the emitter once per derived-column state change observed between forward and reverse apply | `migration/semantic_events.py`; `migration/apply_reverse.py::_emit_reversed_lifecycle_events_for_changed_derived` |
| `migration.cli.APPLY_DIRECTION_WEB_TO_LEGACY` flag threaded through `run_apply` | CLI default remains `legacy-to-web` (backward compat); `--direction web-to-legacy` dispatches to `apply_web_to_legacy` | `migration/cli.py::build_parser` + `run_apply` |
| Per-strategy table honoured symmetrically on reverse (`preserve` advances `last_legacy_snapshot_at`, `derived` does NOT re-derive, `fixed` is never written) | The reverse applier never writes `preserved_value` (pinned by `tests/migration/test_reverse_apply.py::test_preserve_column_not_written_to_legacy` static grep); the derivation engine is never invoked on reverse (pinned by `test_derived_column_no_rederive_on_reverse`) | `migration/apply_reverse.py::_advance_preserve_shadow_state` |
| Drift detection on reverse: rowcount=0 → record `needs_review` shadow row with `review_reasons=["reverse_drift_legacy_row_missing"]` | Operator resolves via `apap-migrate reconcile --filter-direction web-to-legacy` | `migration/apply_reverse.py::_record_drift_needs_review` (pinned by `tests/migration/test_round_trip.py::test_round_trip_detects_unsynced_edits_as_needs_review`) |

#### M2 verdict (re-confirmed)

**PASS** for the M2 reverse path. The round-trip invariants
(`tests/migration/test_round_trip.py`, 5 atoms) are exercised via
`FakeInsForge` + injected legacy executor + injected legacy write
seam; no real backend mutation. PII redaction discipline
(15-field closed list) and authorization invariants from PR4b /
PR5 are unchanged — the reverse applier goes through
`app.core.logging.log_safe` (15 fields scrubbed) and never
touches the storage bucket (forward-only).

### Operator acknowledgement

The operator MUST review and accept this verdict as part of the M1
acceptance gate before claiming "Usable ya". The acceptance is
recorded in the migration report (`migration_report.json` +
`migration_report_signature.json`) per the apply runbook's
"Escalation" section.
