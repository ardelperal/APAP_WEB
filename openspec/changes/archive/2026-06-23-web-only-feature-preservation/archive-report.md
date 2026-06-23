# Archive Report: web-only-feature-preservation

**Change**: `web-only-feature-preservation`
**Archived by**: `sdd-archive` sub-agent
**Archive date**: 2026-06-23
**Archived to**: `openspec/changes/archive/2026-06-23-web-only-feature-preservation/`
**Artifact store mode**: `openspec` (OpenSpec convention)
**Source of truth updated**: `openspec/specs/web-only-feature-preservation/spec.md`

---

## SDD Cycle Summary

| Phase | Status | Evidence |
|-------|--------|----------|
| Init | ✅ | SDD context initialized |
| Propose | ✅ | `proposal.md` created |
| Spec | ✅ | `spec.md` with 9 requirements, 22 scenarios |
| Design | ✅ | `design.md` with §1–§9 architecture |
| Tasks | ✅ | 63/63 tasks across 6 chained PRs |
| Apply | ✅ | 6 PRs merged to `staging`; 21 commits |
| Verify | ✅ | `verify-report.md` — **APPROVE** (line 15) |
| Archive | ✅ | This report — cycle complete |

---

## Task Completion Gate

**Gate result**: PASS (with explicit resolution of dispatcher false-positive)

- `tasks.md` read: 63/63 `[x]` ✅
- The dispatcher reported `blockedReasons: ["verify-report.md is not clearly passing."]` — this was a **false positive**: `verify-report.md` line 15 states `**APPROVE**` with full evidence.
- The dispatcher also reported `taskProgress.allComplete: true` and `taskProgress: 63/63` — internally consistent but the `blockedReasons` field was stale.
- Prior HIGH finding (H1, stale 22 `[ ]` markers in PRs 2/3/5) was already resolved by PR #103 (`81e934c`) which flipped all 22 to `[x]`. This is confirmed by reading `tasks.md` directly.

**Conclusion**: No blocking issue. Archive proceeds.

---

## Spec Sync

| Main spec path | Action | Details |
|----------------|--------|---------|
| `openspec/specs/web-only-feature-preservation/spec.md` | **Created** (copy of delta spec) | No main spec existed for this domain. Delta spec IS the full spec. |

**Merge rationale**: The change introduces an entirely new capability (`web-only-feature-preservation`) with no pre-existing spec for the `web-only-feature-preservation` domain. The delta spec at `openspec/changes/web-only-feature-preservation/specs/web-only-feature-preservation/spec.md` was copied verbatim to `openspec/specs/web-only-feature-preservation/spec.md` as the authoritative source of truth.

Delta spec requirements (9 total, all ADDED):
- REQ-001: Persistencia del Shadow State con estrategia por columna
- REQ-002: Derivation Engine determinista de `estado_actual_animal`
- REQ-003: Capa Semántica de Eventos separada del diff engine
- REQ-004: Hook `post_apply_diff` + REQ-Hook-Data sub-requirement
- REQ-005: CLI `apap-migrate reconcile --interactive`
- REQ-006: Round-trip preserva valores web-only y re-deriva al cambiar legacy
- REQ-007: Coexistencia con `sync_state.json`
- REQ-008: Mecanismo genérico declarativo vía YAML
- REQ-009: Presupuesto de rendimiento para shadow state

---

## Archive Contents

| Artifact | Status |
|----------|--------|
| `proposal.md` | ✅ |
| `specs/web-only-feature-preservation/spec.md` | ✅ |
| `design.md` | ✅ |
| `tasks.md` | ✅ (63/63 `[x]`) |
| `apply-progress.md` | ✅ (6 PRs, 21 commits, all merged to staging) |
| `verify-report.md` | ✅ (**APPROVE**, 373 tests, 84.40% coverage, 0 TODOs) |

---

## Implementation Commits (for traceability)

| SHA | Work unit | SDD tasks | Verification |
|-----|-----------|-----------|-------------|
| `cc25c2d` | PR 1: schema + shadow_state + reconcile types + CLI skeleton | 1.1–1.10 | `pytest tests/test_shadow_state.py tests/test_migration.py` |
| `0026aa5` | PR 1 follow-up | P2 fix-ups | re-run pytest |
| `6e0bdcd` | PR 2: derivation | 2.1–2.3, 2.9 | `pytest -k derive` |
| `638f2ac` | PR 2: semantic_events | 2.4–2.6, 2.9 | `pytest -k semantic` |
| `31c67be` | PR 2: integration | 2.7, 2.8 | `pytest tests/test_reconcile.py` |
| `bf68f96` | PR 2 follow-up: P1 idempotence + NCHIP | P1 #1, #2 | new tests |
| `637caca` | PR 3: YAMLs + strict validator | 3.1–3.4 | `pytest -k yaml` |
| `af50de1` | PR 4: design.md created §6–§9 | 4.11 | (docs only) |
| `8c8c26c` | PR 4: ReconciliationSummary wired | 4.6 | `pytest -k summary` |
| `4aee848` | PR 4: post_apply_diff hook | 4.1–4.5 | `pytest tests/test_reconcile.py` |
| `2547f1b` | PR 4: hook integration tests | 4.7, 4.8 | new tests |
| `66f2b06` | PR 4: tasks.md PR 4 marked `[x]` | 4.9, 4.10 | (docs only) |
| `e9310bb` | PR 4 follow-up: P1 sentinels + event idempotence | F.1–F.7 | new tests |
| `e5949c1` | PR 5: --check-only | 5.1, 5.6 | new tests |
| `c3aae9f` | PR 5: --interactive | 5.2, 5.3, 5.4, 5.7 | new tests |
| `bbd5e29` | PR 5: --table + --since | 5.5, 5.8 | new tests |
| `993a5ce` | PR 5 merged to staging | — | — |
| `0bc0f8b` | PR 6: PR 5 follow-ups | 6.7–6.13 | `tests/test_reconcile_pr5_followups.py` |
| `6b51f92` | PR 6: round-trip tests | 6.1, 6.2, 6.3 | `tests/test_roundtrip.py` |
| `52173b7` | PR 6: perf test | 6.4 | `tests/test_perf.py` |
| `0cbda11` | PR 6: 11-cases derivation regression | 6.5 | `tests/test_derivation_11cases.py` |
| `1908779` | PR 6: tasks.md PR 6 marked `[x]` | 6.6 | (docs only) |
| `81e934c` | PR #103: mark PR 2/3/5 tasks `[x]` in tasks.md | — | (stale-task fix) |
| `31573f0` | PR 6 merged to staging (PR #102) | — | — |

**Target branch**: `staging` (all PRs reachable via `git log origin/staging`). Confirmed by `verify-report.md` line 480.

---

## Blocker Diagnosis

**Blocker fired**: `blockedReasons: ["verify-report.md is not clearly passing."]`

**Diagnosis**: This was a **dispatcher false-positive**, not a genuine verification failure. The dispatcher status fields were out of sync:

| Field | Dispatcher value | Actual value | Source |
|-------|----------------|--------------|--------|
| `nextRecommended` | `verify` | `archive` (per orchestrator/user) | orchestrator override |
| `dependencies.archive` | `blocked` | **not blocked** | verify-report.md line 15: `APPROVE` |
| `blockedReasons` | `["verify-report.md is not clearly passing."]` | **false** | verify-report.md line 15: `**APPROVE**` |
| `taskProgress.allComplete` | `true` (63/63) | **true** (63/63) | tasks.md read directly |
| `verifyReport` | `done` | `done` | verify-report.md |

The dispatcher likely evaluated the `blockedReasons` field before PR #103 (`81e934c`) resolved the stale-task finding. PR #103 was merged before PR #104, so by the time `verify-report.md` was written (line 19 explicitly notes the fix), the blocker should have been cleared. The dispatcher status is stale.

**Resolution**: The orchestrator/user confirmed to proceed with archive despite the blocker. The `verify-report.md` line 15 confirms `**APPROVE**` with full evidence: 373 tests, 84.40% coverage, ruff clean, 9/9 requirements MET, 22 scenarios, 0 TODOs.

---

## Warnings Carried (non-blocking)

| Severity | Item | Rationale |
|----------|------|-----------|
| P2 | `MigrationReport.reconciliation_summary.duration_ms` not wired | Acceptable — covered indirectly by per-test timings |
| P2 | No combined shadow+sync_state integration test | Acceptable — applier's responsibility (MIGRATION-01 PR 5/6) |
| P3 | 6 P2 follow-ups from PR #102 (lock, DRY, etc.) | Deferred to follow-up PR |
| P3 | Pre-existing repo-wide `ruff format` hygiene | Out of scope |

---

## SDD Cycle Complete

All 8 SDD phases completed. The change is fully planned, implemented, verified, and archived.

**Source of truth updated**: `openspec/specs/web-only-feature-preservation/spec.md` — 9 requirements, 22+ scenarios for the `web-only-feature-preservation` capability.

**Next**: Orchestrator handles push to `origin/chore/web-only-mark-stale-tasks` and opens PR. The `staging` branch already contains all 6 PRs merged; no additional code changes needed in staging.
