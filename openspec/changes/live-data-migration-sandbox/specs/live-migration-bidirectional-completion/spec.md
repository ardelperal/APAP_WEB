# live-migration-bidirectional-completion

## Purpose

M2 fallback-readiness gate. Defines the reverse path `apply_web_to_legacy`, the `post_apply_diff` hook symmetry for direction `"web-to-legacy"`, round-trip invariants (legacy→web→legacy preserves NCHIP, Voluntario, source_hash), CLI reconciliation for reverse-direction `needs_review`, the no-fallback-ready-claim gate, and web-only shadow preservation across the round-trip. M1 forward usable ≠ fallback ready; M2 must be green.

## Requirements

### Requirement: Reverse Path apply_web_to_legacy

The system MUST provide `apply_web_to_legacy(client, table_name, *, web_snapshot, dry_run, lock_path)` that reads web rows via the existing web-reader seam, computes the diff vs the legacy snapshot, and writes changes back to the legacy `.accdb` via the legacy executor. The reverse path MUST reuse the same executor seam (`execute_legacy_sql` for writes is write-only; see design), the same lock discipline, and the same dry-run semantics as the forward path.

#### Scenario: Reverse apply writes a web-only change back

- GIVEN a web row was edited post-forward-apply (e.g., new email set in web)
- WHEN `apap-migrate apply --direction web-to-legacy --table voluntario` runs
- THEN the row is UPDATEd in legacy via the legacy executor
- AND `log_safe("sync.applied", direction="web->legacy", ...)` is emitted with count + hash, no raw PII

#### Scenario: Reverse apply dry-run reports without writes

- GIVEN 10 web rows differ from legacy
- WHEN `apap-migrate apply --direction web-to-legacy --table voluntario --check-only` runs
- THEN `would_apply=10` is reported
- AND no write to legacy occurs

### Requirement: post_apply_diff Symmetric Direction Support

The `post_apply_diff` hook MUST support both `direction="legacy-to-web"` and `direction="web-to-legacy"` per `web-only-feature-preservation` REQ-Hook. For `web-to-legacy`, the hook MUST preserve shadow values without re-derivation (no `derive_estado_actual_animal` call), update `web_only_feature_shadow.last_legacy_snapshot_at` for affected rows, and emit `animal_lifecycle_events` for the reverse-direction transitions.

#### Scenario: Web→legacy preserves DNI shadow

- GIVEN a `voluntarios.DNI` shadow row with `preserved_value="12345678A"`
- WHEN `post_apply_diff(direction="web-to-legacy", applied_diffs=[...])` runs
- THEN `web_only_feature_shadow.preserved_value` remains `"12345678A"`
- AND `last_legacy_snapshot_at` advances to `<UTC now>`
- AND no derivation engine call occurs

#### Scenario: Web→legacy emits LIFECYCLE_REVERSED event for animal state

- GIVEN an `animal_current_state` change in web post-forward-apply
- WHEN `post_apply_diff(direction="web-to-legacy", applied_diffs=[...])` runs
- THEN `animal_lifecycle_events` receives a `LIFECYCLE_REVERSED` event with the pre/post states
- AND the event includes `source_direction="web-to-legacy"`

### Requirement: Round-Trip Invariants

For each migrated row in `animal`, `entrada`, `voluntario`, the round-trip `legacy → web → legacy` MUST preserve: `NCHIP` (or `Voluntario` / `IdEntrada`), `source_hash`, and `count_legacy == count_web == count_legacy_after_round_trip`. Any divergence MUST be flagged as `needs_review` in `web_only_feature_shadow`.

#### Scenario: NCHIP preserved across round-trip

- GIVEN legacy row L with `NCHIP="12345"` and 6 mapped columns
- WHEN `apply_legacy_to_web --table animal` runs, then `apply_web_to_legacy --table animal`
- THEN the legacy row's `NCHIP` after round-trip equals `"12345"`
- AND the source_hash of the legacy row before forward apply equals the source_hash after reverse apply (deterministic mapping)

#### Scenario: Voluntario with DNI preserved across round-trip

- GIVEN legacy row L with `Voluntario="V1"`, `DNI="12345678A"`
- WHEN `apply_legacy_to_web --table voluntario` then `apply_web_to_legacy --table voluntario`
- THEN `DNI` in legacy after round-trip equals `"12345678A"`
- AND shadow row for `DNI` retains `preserved_value="12345678A"`

#### Scenario: Round-trip detects drift as needs_review

- GIVEN a forward apply inserted 100 voluntarios with hashed source
- WHEN a manual edit changes 5 web rows' email between forward and reverse
- THEN reverse apply records 5 divergence rows in shadow with `reconciliation_status="needs_review"`
- AND `apap-migrate reconcile --check-only` lists them

### Requirement: Round-Trip Test Suite

`tests/migration/test_round_trip.py` MUST contain fixture-first tests that:
1. Set up a legacy snapshot (in-memory via fake executor) with N rows per table.
2. Run `apply_legacy_to_web` against an in-memory web (FakeLocalBackend).
3. Optionally mutate some web rows to simulate in-flight edits.
4. Run `apply_web_to_legacy` against the same fake executor.
5. Assert: counts preserved per table, NCHIP/Voluntario/IdEntrada preserved, source_hash preserved, no orphan shadow rows.

#### Scenario: 100-animal round-trip with no in-flight edits

- GIVEN a legacy snapshot of 100 animales with all mapped columns
- WHEN the full round-trip runs with no web edits
- THEN `count_legacy == count_web == 100`
- AND per-row `source_hash` equal pre and post
- AND `web_only_feature_shadow` contains only the rows expected (DNI for voluntarios only)

#### Scenario: Round-trip with 3 in-flight web edits

- GIVEN 100 legacy voluntarios; 3 web rows' email edited between forward and reverse
- WHEN the full round-trip runs
- THEN 3 rows are UPDATED in legacy with the new email
- AND 97 rows are no-op
- AND shadow state records 0 `needs_review` (the 3 edits were intentional and reverse-applied cleanly)

### Requirement: Reconciliation CLI Symmetric Across Directions

`apap-migrate reconcile --check-only` MUST enumerate `needs_review` cases for both `legacy-to-web` and `web-to-legacy` directions. `--interactive` MUST work symmetrically: the operator can choose `keep web`, `accept derived`, or `defer` for any case regardless of origin direction.

#### Scenario: Reconcile lists both directions

- GIVEN 5 `needs_review` from forward and 3 from reverse
- WHEN `apap-migrate reconcile --check-only` runs
- THEN all 8 cases are listed with `origin_direction` field
- AND `--filter-direction legacy-to-web` returns the 5 forward cases only

#### Scenario: Interactive resolves a reverse-direction case

- GIVEN a reverse-direction `needs_review` row
- WHEN the operator selects `keep web`
- THEN the system writes `reconciled_at=<UTC now>`, `reconciliation_status="matched"`
- AND the web value is preserved (not overwritten)

### Requirement: Fallback-Ready Gate (HARD CI + Publication Gate)

NO claim of "fallback ready" SHALL be made unless ALL of the following are true:
- **CI-runnable conditions** (executed in `.github/workflows/ci.yml` as a dedicated job):
  - Round-trip test (`tests/migration/test_round_trip.py`) green for `animal`, `entrada`, `voluntario`.
  - `apply_web_to_legacy --check-only` symmetric to forward (same set of tables, same columns, same collision policy).
  - `docs/audits/pii-live-migration-2026-Q3.md` Verdict `PASS` (per `live-migration-pii-controls`; parsed from the markdown).
- **Operator-attested conditions** (cannot be exercised in CI without exposing real PII):
  - At least 1 real cycle executed with operator assist; recorded in `migration_report.json` PLUS `migration_report_signature.json` containing `operator_id`, `sha256_of_report`, `signed_at`.
  - The signature file is checked in to the repo at the operator's discretion (it does NOT contain PII — only operator_id + report hash + timestamp).

The gate MUST be enforced by a verification script `apap-migrate verify-fallback-ready` that returns exit 0 only when ALL conditions hold. The script supports two modes:
- `verify-fallback-ready --ci-only` → runs CI-runnable subset (no operator attestation required). This is the mode the CI job uses.
- `verify-fallback-ready` (no flag) → runs CI-runnable + operator-attested. Exit 0 only when BOTH pass. This is the mode the publication gate uses.

The M2 milestone is NOT claimable without the full `verify-fallback-ready` (no flag) returning exit 0. The CI gate (`--ci-only`) is a stricter signal than the publication gate: it MUST be green before the PR merges.

#### Scenario: verify-fallback-ready rejects partial M2 in CI

- GIVEN round-trip test green, audit doc PASS, but CI mode (`--ci-only`) hits a regression
- WHEN `apap-migrate verify-fallback-ready --ci-only` runs in `.github/workflows/ci.yml`
- THEN exit code is 1
- AND the CI job fails the build
- AND `missing_ci_condition=<which>` is reported

#### Scenario: verify-fallback-ready --ci-only passes (interim OK)

- GIVEN all CI-runnable conditions green
- WHEN `apap-migrate verify-fallback-ready --ci-only` runs
- THEN exit code is 0
- AND a receipt is printed listing the CI-runnable verdicts
- AND the operator-attested conditions are listed as PENDING (not blocking CI)

#### Scenario: verify-fallback-ready rejects partial M2 (full mode, missing real cycle)

- GIVEN CI-runnable conditions green, but no `migration_report_signature.json` exists
- WHEN `apap-migrate verify-fallback-ready` (no flag) runs
- THEN exit code is 1 with `missing_real_cycle=true`
- AND "fallback ready" claim is forbidden
- AND the runbook instructs the operator to run `apap-migrate apply --direction web-to-legacy --operator-attest` once

#### Scenario: verify-fallback-ready accepts complete M2

- GIVEN all CI-runnable conditions green AND `migration_report_signature.json` exists with a valid `operator_id`
- WHEN `apap-migrate verify-fallback-ready` (no flag) runs
- THEN exit code is 0
- AND a structured receipt is printed citing: round-trip test run, audit verdict, real-cycle report path, web-to-legacy check-only output, operator signature hash

### Requirement: Web-Only Shadow Preservation Across Round-Trip

The `web_only_feature_shadow.preserved_value` for any column with `web_only_strategy: preserve` MUST be byte-identical after a full `legacy→web→legacy` round-trip. The reverse path MUST NOT overwrite `preserved_value`; it only advances `last_legacy_snapshot_at`.

#### Scenario: DNI preserved_value unchanged after round-trip

- GIVEN shadow row with `preserved_value="12345678A"`, `last_legacy_snapshot_at=T1`
- WHEN the full round-trip runs (no in-flight web edits to DNI)
- THEN shadow row has `preserved_value="12345678A"`, `last_legacy_snapshot_at=T2 > T1`

#### Scenario: Reverse path never writes preserved_value

- GIVEN the reverse applier code path
- WHEN a static test greps for any `UPDATE web_only_feature_shadow SET preserved_value=` in reverse-direction branches
- THEN zero matches are found
- AND the test fails the build on any match

## Acceptance Evidence

- `tests/migration/test_round_trip.py` with fixtures: empty source, 100 animales, 100 voluntarios, 100 entradas; in-flight web edits (3) and reverse-applied; drift detection (2 unsynced edits).
- `tests/migration/test_reverse_apply.py` for the web→legacy path.
- `tests/migration/test_fallback_ready_gate.py` for `verify-fallback-ready`.
- Real-cycle report captured in `migration_report.json` with operator signature.
- Audit doc PASS verdict.

## Out of Scope

- Multi-legacy simultaneous support or real-time sync (inherited from MIGRATION-01 §12).
- Bitemporal modeling for retroactive audit.
- UI for resolving `needs_review` (CLI-only per `web-only-feature-preservation`).
- Auto-resolution of `needs_review` (operator-in-the-loop per Q8-A).
- Production release/tag — the user makes that call after M2 is green and validated.
