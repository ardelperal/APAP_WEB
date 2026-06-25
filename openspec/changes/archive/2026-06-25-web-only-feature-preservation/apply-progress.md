# Apply progress: web-only-feature-preservation

## Status: APPLIED (6/6 PRs merged to staging)

All 6 chained PRs of this change have been implemented, code-reviewed (pre-push), pushed, and merged to `staging` (target branch per `tasks.md §PR Chain Strategy`).

## Merged PRs

| PR # | SHA (head) | Title | Coverage | Test count |
|---|---|---|---|---|
| #96 | `bf99ef4` | PR 1/6 — shadow_state + CLI skeleton | 85.14% | 197 |
| #97 | `c95678e` | PR 2/6 — derivation + semantic_events | 86.64% | 244 |
| #98 | `8ac801c` | PR 3/6 — YAMLs + strict validator | 91.55% | 275 |
| #100 | `a3593d3` | PR 4/6 — post_apply_diff hook | 86% | 340 |
| #101 | `993a5ce` | PR 5/6 — apap-migrate reconcile CLI | 85.79% | 348 |
| #102 | `31573f0` | PR 6/6 — round-trip + perf + PR 5 follow-ups | 84.40% | 373 |

Plus MIGRATION-01 PR 4/6 (#99, merged to main `16b5608`) — required dependency for the hook.

## Implementation commits (chronological)

### PR 1/6 (#96): `feat(web-only-preservation): P0 blocker tables + shadow_state CRUD + reconcile types + CLI skeleton`
- `cc25c2d` — feat: P0 blocker tables + shadow_state CRUD + reconcile types + CLI skeleton (PR 1/6)
- `0026aa5` — test: tighten PR 1 contract + mark tasks done (PR 1/6 follow-up) [P2 fix-up]

### PR 2/6 (#97): derivation + semantic_events
- `6e0bdcd` — feat(web-only-preservation): derive_estado_actual_animal priority cascade (PR 2/6)
- `638f2ac` — feat(web-only-preservation): semantic_events module mapping legacy diffs to lifecycle events (PR 2/6)
- `31c67be` — feat(web-only-preservation): integrate derivation into reconcile_after_legacy_write (PR 2/6)
- `bf68f96` — fix(web-only-preservation): P1 idempotence bug + NCHIP int coercion (PR 2/6 follow-up)

### PR 3/6 (#98): `feat(web-only-preservation): YAML web_only_strategy + strict validator (PR 3/6)`
- `637caca` — single commit (YAMLs + validator tightly coupled per work-unit-commits)

### PR 4/6 (#100): post_apply_diff hook
- `af50de1` — docs(web-only-preservation): create design.md with §6-§9 + _STRATEGY_EXEMPT_TRANSFORMS rationale
- `8c8c26c` — feat(migration): wire ReconciliationSummary onto MigrationReport (PR 4/6, T4.6)
- `4aee848` — feat(migration): post_apply_diff hook for legacy->web reconciliation (PR 4/6)
- `2547f1b` — test(migration): post_apply_diff hook integration + atomicity tests (PR 4/6)
- `66f2b06` — docs(web-only-preservation): mark PR 4 tasks complete in tasks.md (PR 4/6)
- `e9310bb` — fix(web-only-preservation): P1 contract - sentinel docs + event idempotence (PR 4/6 follow-up)

### PR 5/6 (#101): apap-migrate reconcile CLI
- `e5949c1` — feat(cli): apap-migrate reconcile --check-only lists needs_review rows (PR 5/6)
- `c3aae9f` — feat(cli): apap-migrate reconcile --interactive keep/accept/defer/quit (PR 5/6)
- `bbd5e29` — feat(cli): apap-migrate reconcile --table + --since filters (PR 5/6)

### PR 6/6 (#102): round-trip + perf + PR 5 follow-ups
- `0bc0f8b` — feat(web-only-preservation): PR 5 follow-ups (PR 6/6, T6.7-T6.13)
- `6b51f92` — test(web-only-preservation): round-trip tests (PR 6/6, T6.1-T6.3)
- `52173b7` — test(web-only-preservation): 10k animales perf budget (PR 6/6, T6.4)
- `0cbda11` — test(web-only-preservation): 11-cases derivation regression (PR 6/6, T6.5)
- `1908779` — docs(web-only-preservation): mark PR 6 tasks complete in tasks.md (PR 6/6)

## Code review history

Each PR went through `code-review-expert` skill. Verdicts:

- #96: APPROVE (after P2 follow-up)
- #97: APPROVE on re-review (after 2 P1 follow-ups: idempotence + NCHIP)
- #98: APPROVE
- #100: APPROVE on re-review (after 2 P1 follow-ups: sentinel docs + event idempotence)
- #101: APPROVE pre-push (3 commits), then merged
- #102: APPROVE pre-push (5 commits), then merged

## Capabilities delivered

The new capability `web-only-feature-preservation` is fully implemented per spec.md:

- **Shadow State CRUD**: `app/core/migration/shadow_state.py` with `upsert`, `lookup`, `list_needs_review`, `update_reconciliation_status`, `update_derived_value`, `update_derived_at`, `delete`. Table `web_only_feature_shadow` with UNIQUE `(table_name, legacy_pk, web_column)` index.
- **Derivation Engine**: `app/core/migration/derivation.py` with priority cascade (`DameSituacion()` replica), 11 parametrized cases covered, P1 idempotence bug fixed.
- **Semantic Events Layer**: `app/core/migration/semantic_events.py` (P0 from explore) — separate module, NOT extension of MIGRATION-01 diff engine. NCHIP int-coercion bug fixed.
- **Reconciliation Hook**: `app/core/migration/reconcile.py:post_apply_diff` with sentinels contract (P1 fix-up).
- **CLI**: `app/core/migration/cli.py` with `--check-only`, `--interactive`, `--table`, `--since`, lock acquisition, derived_value pre-fill.
- **Migrations applied**: `animal_current_state`, `animal_lifecycle_events` (with UNIQUE constraint for ON CONFLICT idempotence), `web_only_feature_shadow` (with `derived_value` JSONB + `derived_at` TIMESTAMPTZ).
- **YAML mappings**: all 5 (`animal`, `voluntario`, `entrada`, `acogida`, `adopcion`) with `web_only_strategy` per column. Strict validator (P2 fix-up from PR 3).

## Test verification

- **373 tests passing** (final count after PR #102).
- Coverage `app/core/migration`: **84.40%** (≥80% threshold per `openspec/config.yaml`).
- Perf test: 10,000 animales × 5 columns < 10s (measured ~0.5s).
- All 11 derivation cases from `lifecycle-state-resolver-extraction.md §4` covered by parametrized test.

## Deviations from design.md / spec.md

Resolved in code; documented in commit messages and PR descriptions:

- `_render_value` uses `str(x)` not `repr(x)` (backward compat).
- `_resolve_lock_path` reads `APAP_MIGRATION_DIR` env var (pragmatic).
- `_apply_accept_derived` pre-fills prompt with stored `derived_value` (PR 6 added the column).
- `update_derived_value` / `update_derived_at` separate methods (vs consolidated).

## Next SDD phase

`gentle-ai sdd-status web-only-feature-preservation` next phase: **verify**.