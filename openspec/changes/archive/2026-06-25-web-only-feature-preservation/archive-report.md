# Archive Report: web-only-feature-preservation

**Change**: `web-only-feature-preservation`  
**Archived on**: 2026-06-25  
**Artifact store mode**: hybrid (`openspec` + Engram)  
**Branch**: `staging`  
**Archive status**: complete-with-non-blocking-warnings

## Summary

The active OpenSpec folder was inspected as a possible stale artifact because Engram records a prior archive attempt. The current `staging` branch did not contain an archive folder or the prior archive commits, so this run treated the active folder as the current source of truth and archived it after validation.

The implementation is complete: `tasks.md` has no unchecked implementation tasks, `verify-report.md` verdict is **APPROVE**, and no CRITICAL findings are present. The delta spec is a new domain spec and was promoted to `openspec/specs/web-only-feature-preservation/spec.md`.

## Artifact traceability

### OpenSpec artifacts read

| Artifact | Path | Status |
|---|---|---|
| Proposal | `openspec/changes/archive/2026-06-25-web-only-feature-preservation/proposal.md` | Present |
| Spec | `openspec/changes/archive/2026-06-25-web-only-feature-preservation/specs/web-only-feature-preservation/spec.md` | Present |
| Design | `openspec/changes/archive/2026-06-25-web-only-feature-preservation/design.md` | Present |
| Tasks | `openspec/changes/archive/2026-06-25-web-only-feature-preservation/tasks.md` | Present; no unchecked implementation tasks |
| Apply progress | `openspec/changes/archive/2026-06-25-web-only-feature-preservation/apply-progress.md` | Present; 6/6 PRs merged to staging |
| Verify report | `openspec/changes/archive/2026-06-25-web-only-feature-preservation/verify-report.md` | Present; APPROVE |

### Engram artifacts read

| Artifact | Observation ID | Topic / note |
|---|---:|---|
| Proposal | `#13550` | `sdd/web-only-feature-preservation/proposal` |
| Spec | `#13553` | `sdd/web-only-feature-preservation/spec` |
| Design | `#13554` | `sdd/web-only-feature-preservation/design` |
| Tasks | `#13555` | `sdd/web-only-feature-preservation/tasks`; initial summary observation, not the final checkbox source |
| Verify report | `#13811` | Verify artifact persisted as `sdd/web-only-feature-preservation/verify` |
| Prior archive memory | `#13976`, `#13977` | Stale/prior archive attempt context; prior archive commits are not reachable from current `staging` |

## Completion gates

| Gate | Result | Evidence |
|---|---|---|
| Tasks completion | PASS | Archived `tasks.md` contains no `- [ ]` implementation tasks |
| Verification | PASS WITH WARNINGS | `verify-report.md` line 15 says **APPROVE**; P0 findings: none |
| Critical findings | PASS | `verify-report.md` states no CRITICAL implementation findings |
| Spec sync | PASS | New domain spec promoted to `openspec/specs/web-only-feature-preservation/spec.md` |
| Active folder archival | PASS | Moved to `openspec/changes/archive/2026-06-25-web-only-feature-preservation/` |

## Implementation commits

Reachability checked with `git merge-base --is-ancestor <sha> staging` on 2026-06-25.

| Commit | Work unit | SDD tasks | Verification / note | Reachable from `staging` |
|---|---|---|---|---|
| `cc25c2d` | PR 1 schema + shadow_state + reconcile types + CLI skeleton | 1.1-1.10 | PR #96 evidence | Yes |
| `0026aa5` | PR 1 follow-up | P2 fix-up | PR #96 evidence | Yes |
| `6e0bdcd` | PR 2 derivation | 2.1-2.3, 2.9 | PR #97 evidence | Yes |
| `638f2ac` | PR 2 semantic events | 2.4-2.6, 2.9 | PR #97 evidence | Yes |
| `31c67be` | PR 2 integration | 2.7-2.8 | PR #97 evidence | Yes |
| `bf68f96` | PR 2 P1 follow-up | P1 idempotence + NCHIP | PR #97 evidence | Yes |
| `637caca` | PR 3 YAML strategy validation | 3.1-3.4 | PR #98 evidence | Yes |
| `af50de1` | PR 4 design docs | 4.11 | PR #100 evidence | Yes |
| `8c8c26c` | PR 4 ReconciliationSummary | 4.6 | PR #100 evidence | Yes |
| `4aee848` | PR 4 `post_apply_diff` hook | 4.1-4.5 | PR #100 evidence | Yes |
| `2547f1b` | PR 4 hook tests | 4.7-4.8 | PR #100 evidence | Yes |
| `66f2b06` | PR 4 task completion docs | 4.9-4.10 | PR #100 evidence | Yes |
| `e9310bb` | PR 4 P1 contract fixes | F.1-F.7 | PR #100 follow-up | Yes |
| `e5949c1` | PR 5 `--check-only` | 5.1, 5.6 | PR #101 evidence | Yes |
| `c3aae9f` | PR 5 `--interactive` | 5.2-5.4, 5.7 | PR #101 evidence | Yes |
| `bbd5e29` | PR 5 `--table` + `--since` | 5.5, 5.8 | PR #101 evidence | Yes |
| `0bc0f8b` | PR 6 PR 5 follow-ups | 6.7-6.13 | PR #102 evidence | Yes |
| `6b51f92` | PR 6 round-trip tests | 6.1-6.3 | PR #102 evidence | Yes |
| `52173b7` | PR 6 performance test | 6.4 | PR #102 evidence | Yes |
| `0cbda11` | PR 6 11-case regression | 6.5 | PR #102 evidence | Yes |
| `1908779` | PR 6 task completion docs | 6.6 | PR #102 evidence | Yes |
| `81e934c` | Housekeeping: mark all tasks complete | Task gate cleanup | PR #103 evidence | Yes |
| `8870cff` | Add apply-progress/proposal/verify artifacts | SDD artifact completion | PR #104 evidence | Yes |
| `008a656` | Merge PR 104 | SDD artifact merge | Current staging history | Yes |

### Prior archive-attempt commits

Engram references prior archive commits `ac848d1` and `ee56ca5`, but both are **not reachable** from current `staging`; no matching archive folder exists in the current filesystem state. This run does not rely on those commits as source-of-truth evidence.

## Specs synced

| Domain | Action | Details |
|---|---|---|
| `web-only-feature-preservation` | Created | Copied full new-domain spec from the change folder to `openspec/specs/web-only-feature-preservation/spec.md` |

## Archive contents

- `proposal.md` ✅
- `specs/web-only-feature-preservation/spec.md` ✅
- `design.md` ✅
- `tasks.md` ✅
- `apply-progress.md` ✅
- `verify-report.md` ✅
- `archive-report.md` ✅

## Non-blocking warnings / limitations

1. `verify-report.md` still contains historical stale-dispatcher lines (`41/63` and archive blocked) in its body, but the same report also records the later resolution: PR #103 flipped all stale tasks and the current `tasks.md` file has all implementation tasks checked.
2. Engram tasks observation `#13555` is an initial summary and does not contain the final checkbox state. The final OpenSpec `tasks.md` on `staging` is the authoritative completion artifact for this archive gate.
3. Prior archive memories `#13976`/`#13977` appear to describe work on a branch/PR that is not reachable from current `staging`; this archive run records that limitation instead of inventing continuity.
4. Deferred P2/P3 items remain non-blocking: `MigrationReport.reconciliation_summary.duration_ms`, combined shadow + sync_state integration test, and cleanup follow-ups from PR #102 review.

## Result

The SDD change `web-only-feature-preservation` is complete and archived. Source of truth now lives in:

- `openspec/specs/web-only-feature-preservation/spec.md`
- `openspec/changes/archive/2026-06-25-web-only-feature-preservation/`
