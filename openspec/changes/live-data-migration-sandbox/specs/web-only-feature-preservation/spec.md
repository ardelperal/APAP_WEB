# Delta for web-only-feature-preservation

## ADDED Requirements

### Requirement: Reverse Direction post_apply_diff Reuses Preserve/Derived/Fixed Strategies Symmetrically

The `post_apply_diff` hook MUST handle `direction="web-to-legacy"` symmetrically to `direction="legacy-to-web"` for all three `web_only_strategy` values:

| Strategy | Forward (legacy→web) behavior | Reverse (web→legacy) behavior |
|---|---|---|
| `preserve` | Write `preserved_value` into shadow; populate web column from legacy if `legacy_column` set | NEVER write `preserved_value`; only advance `last_legacy_snapshot_at`; web-only column remains untouched in legacy |
| `derived` | Run derivation engine; compare vs stored; mark `matched` / `divergent` / `needs_review` | DO NOT re-derive; preserve current `current_state`; emit `LIFECYCLE_REVERSED` event with pre/post if state changed in web post-forward-apply |
| `fixed` | Write static value from YAML once; never re-derive | NEVER write; `fixed` is a one-shot bootstrap, not a sync target |

For reverse direction the hook MUST also: (a) update `sync_state.json` with `last_sync_at` per affected table in the same transaction as the legacy write; (b) emit `animal_lifecycle_events` for any state transition that occurred in web between forward and reverse apply; (c) record `needs_review` for any divergence between forward-applied state and reverse-applied state.

(Previously: REQ-Hook described `web-to-legacy` as "preserve shadow values without re-derivation" but did not specify per-strategy behavior, sync_state update timing, or lifecycle event emission.)

#### Scenario: preserve column on reverse preserves shadow

- GIVEN a `voluntarios.DNI` shadow row with `preserved_value="12345678A"`, `last_legacy_snapshot_at=T1` (set by manual web entry post-bootstrap; `DNI` has NO legacy source per `TbVoluntariosParaAutorrellenables` Dysflow `get_schema`)
- WHEN `post_apply_diff(direction="web-to-legacy", applied_diffs=[voluntario_diff_with_email_change_only])` runs
- THEN `preserved_value` is still `"12345678A"`
- AND `last_legacy_snapshot_at` advances to `T2 > T1`
- AND `DNI` is NOT written to legacy (legacy has no DNI column — `legacy_column=null` in `voluntario.yaml`)
- AND the legacy write only affects columns with `legacy_column` set (`Voluntario, Tel1, Tel2, Email`)

#### Scenario: derived column on reverse does not re-derive

- GIVEN an `animal_current_state.current_state="Acogida"` from a prior forward apply
- WHEN `post_apply_diff(direction="web-to-legacy", applied_diffs=[animal_diff_with_no_lifecycle_change])` runs
- THEN the derivation engine is NOT invoked
- AND `current_state` remains `"Acogida"` in web
- AND no `LIFECYCLE_REVERSED` event is emitted (no state change)

#### Scenario: derived column with state change emits LIFECYCLE_REVERSED

- GIVEN `animal_current_state.current_state="Albergue"` from forward apply
- WHEN between forward and reverse apply, web `current_state` is edited to `"Acogida"` (e.g., manual override)
- AND `post_apply_diff(direction="web-to-legacy", applied_diffs=[animal_diff])` runs
- THEN `LIFECYCLE_REVERSED` event is emitted with `pre_state="Albergue"`, `post_state="Acogida"`, `source_direction="web-to-legacy"`
- AND the legacy write updates the legacy columns that map to `current_state` (if any)
- AND shadow state records `needs_review` with `review_reasons=["web_manual_override_detected"]`

#### Scenario: fixed column on reverse is never written

- GIVEN a fixed column `foo` with `web_only_strategy: fixed`, value `"X"` set once at bootstrap
- WHEN `post_apply_diff(direction="web-to-legacy", applied_diffs=[...])` runs
- THEN `foo` is NOT written to legacy
- AND no shadow update for `foo`

### Requirement: Reverse Direction Sync_state Update Is Transactional With Legacy Write

For `direction="web-to-legacy"`, the applier MUST update `sync_state.json` (`tables[<table>].last_sync_at = <UTC now>`) AFTER the legacy write commits successfully, and MUST roll back the sync_state update if the legacy write fails. The shadow state update (`last_legacy_snapshot_at`) is independent and uses UTC timestamps consistent with forward direction.

#### Scenario: Sync_state advances after successful legacy write

- GIVEN a web→legacy apply of 50 rows for table `voluntarios`
- WHEN all 50 legacy writes commit successfully
- THEN `sync_state.json` has `tables.voluntarios.last_sync_at = <UTC now>`
- AND shadow rows for affected `preserve` columns have `last_legacy_snapshot_at` advanced

#### Scenario: Legacy write failure rolls back sync_state

- GIVEN 50 rows; row 25 fails in the legacy executor
- WHEN the apply handles the failure
- THEN `sync_state.json` is NOT updated (or is rolled back to pre-apply state)
- AND the operator sees the 50th-row error in the CLI output

#### Scenario: Sync_state and shadow timestamps stay consistent

- GIVEN a successful reverse apply of 100 voluntarios
- WHEN the apply completes
- THEN for each affected shadow row, `last_legacy_snapshot_at == sync_state.tables.voluntarios.last_sync_at`
- AND no shadow row has `last_legacy_snapshot_at` ahead of `sync_state` (no future-dated shadows)

### Requirement: Round-Trip CLI Reconcile Lists Both Directions

`apap-migrate reconcile [--check-only] [--interactive] [--filter-direction {legacy-to-web,web-to-legacy}]` MUST enumerate `needs_review` cases for both directions. The `--filter-direction` flag is OPTIONAL; without it, both directions are listed. Each case MUST carry an `origin_direction` field. The three resolutions (`keep web`, `accept derived`, `defer`) work symmetrically regardless of origin direction.

(Previously: REQ-005 specified CLI for forward-direction `needs_review` only; reverse direction was implied but not specified.)

#### Scenario: Reconcile lists both directions by default

- GIVEN 4 forward `needs_review` and 2 reverse `needs_review` cases
- WHEN `apap-migrate reconcile --check-only` runs
- THEN all 6 cases are listed
- AND each case has `origin_direction` ∈ `{"legacy-to-web", "web-to-legacy"}`

#### Scenario: --filter-direction narrows the list

- GIVEN 4 forward and 2 reverse cases
- WHEN `apap-migrate reconcile --check-only --filter-direction legacy-to-web` runs
- THEN only 4 forward cases are listed

#### Scenario: Interactive resolution works for reverse-direction case

- GIVEN a reverse `needs_review` row with `review_reasons=["web_manual_override_detected"]`
- WHEN the operator runs `apap-migrate reconcile --interactive` and selects `keep web`
- THEN `reconciliation_status="matched"`, `reconciled_at=<UTC now>` are written
- AND the case does not appear on subsequent `reconcile --check-only` runs

## Out of Scope (delta)

- New derivation rules beyond the existing `derive_estado_actual_animal` — design can add new rules but is bounded by `derive_*` purity contract.
- Multi-legacy simultaneous support or real-time sync.
- UI for `needs_review` resolution.
- Auto-resolution or batch resolution across multiple cases.
