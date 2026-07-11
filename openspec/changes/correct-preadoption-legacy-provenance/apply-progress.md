# Apply Progress: Correct Pre-Adoption Legacy Provenance

## Current state

- **Mode:** Strict TDD capability, docs-only exception. No product code or tests were modified and no artificial RED test was created.
- **Delivery:** Single PR intended, `stacked-to-main` against `main`. Branch is 7 commits ahead of `origin/main` (`071aaeb`); NOT pushed; PR not opened.
- **Branch:** `docs/correct-preadoption-legacy-provenance`.
- **Apply result:** Tasks 1-5 and 7 complete (original apply pass). Task 6 (post `gh issue comment 48`) remains pending until a PR URL exists.
- **Corrective closeout pass (this apply-progress update):** adds the residual corrections (RISK-001 / RISK-002 / RISK-003 / RISK-004 / RESILIENCE-001 / RESILIENCE-002 / RESILIENCE-003 / RESILIENCE-005 / RESILIENCE-006) and merges them with the original pass. They land as one focused commit on top of the existing 7 commits (see "Commit strategy" below).

## Commit audit

| Commit | Task | Result |
|---|---|---|
| `6f86112` | 1 | Semantic correction complete. The commit also normalized line endings in two docs, inflating the raw diff. |
| `d3043b2` | 2 | Contract-clause provenance corrected (20-day → one-month post-sterilization). |
| `fe3ce54` | 3 | Roadmap and README cancellation references corrected. |
| `63ea18e` | 4 | Showcase expiry state and claims removed. |
| `1cb67f8` | 5 | Cancellation notice and proposal banner added. |
| `b8a4510` | 6 preparation only | Draft prepared; no GitHub comment posted. Superseded by the corrected body file in the corrective closeout (see below). |
| `d08ee0c` | Planning artifacts | Added design, spec, and tasks. It did not itself prove Engram updates; those were reconciled in this pass. |
| `d08ee0c`+1 (corrective closeout — this pass) | 6 + 8 + 9 + 10 | Final residual corrections: removed remaining false 20-day claim at `feature-02-intake-foster-adoption.md:199`; re-framed the unproven one-month post-sterilization claim in `feature-04` and `features-showcase.html` to use src-proven wording; rewrote `.comment-for-issue-48.md` as a body-only payload with a stable HTML marker for idempotency; corrected `CANCELLATION.md` to distinguish intended vs evidence-backed state with explicit Engram compensation/reconciliation language; fixed the P3 markdown table-break bug at `data-model-completeness.md` L275; corrected task dependency/state so external Engram updates are represented as reconciliation evidence, not a falsely ordered post-PR task; updated `specs/migration-discovery-docs/spec.md` to drop the overclaimed "one-month post-sterilization" wording in favour of the actual sex-conditional sterilization text + no-runtime-timer. |

## Completed and pending work

- [x] Task 1: discovery lifecycle correction.
- [x] Task 2: contract-clause correction (re-corrected in the closeout to use src-proven wording).
- [x] Task 3: roadmap and README cancellation.
- [x] Task 4: showcase correction (re-corrected in the closeout to use src-proven wording).
- [x] Task 5: cancellation record and proposal banner (re-corrected in the closeout with the intended vs evidence-backed columns and Engram compensation language).
- [ ] Task 6: post issue #48 cancellation comment after a PR URL exists. The body-only payload is ready at `openspec/changes/correct-preadoption-legacy-provenance/.comment-for-issue-48.md` with a stable HTML marker `<!-- cancellation-marker:adopt-02 -->`. The post is idempotent: search for the marker with `gh issue view 48 --json comments --jq '.comments[].body' | rg -F '<!-- cancellation-marker:adopt-02 -->'` and stop if a hit is found.
- [x] Task 7: Engram observations and external-work stub. Upserted five ADOPT-02 cancellation topics (`sdd/adopt-02-expiry/{proposal,spec,design,tasks,apply-progress}`) and the cumulative apply-progress topic for this change. The Engram IDs are #16694 (proposal), #16695 (spec), #16696 (design), #16697 (tasks), #16698 (adopt-02-expiry apply-progress), #16699 (this change's apply-progress), #16706 (session summary), #16712 (resume point). Engram is persistent and CANNOT be transactionally reverted; compensation is by re-save (upsert with `superseded by` note), not by delete.
- [ ] Open PR, run mandatory review lenses, obtain green CI, and then post the issue comment with the PR URL.

## Frozen accepted blocking IDs — mapping to edits and evidence

| ID | Status | Edits | Evidence |
|---|---|---|---|
| RISK-001 / RELIABILITY-001 | [x] Resolved | `docs/discovery/feature-02-intake-foster-adoption.md` L199: replaced `20-day decision clause template` with src-proven wording. | `rg -i -n '20 días\|20 days' docs/discovery/feature-02-intake-foster-adoption.md` → 0 matches. |
| RISK-002 | [x] Resolved | `docs/discovery/feature-04-documents-contracts-reports.md` L53, L74, L84, L89 + `docs/features-showcase.html` L537, L605: replaced unproven `one-month post-sterilization` claim with src-proven wording (shared `CONTRATO DE ADOPCIÓN_V02.docx` per `Entorno.cls` L793; `RellenarContratoPreAdopcion` `Plantilla.cls` L620-689 has no runtime timer). | `rg -i -n 'one-month\|un mes post' docs/discovery/feature-04-documents-contracts-reports.md` → 1 hit, the corrective blockquote (intentional, src-proven). |
| RISK-003 / RESILIENCE-002 | [x] Resolved | `openspec/changes/correct-preadoption-legacy-provenance/.comment-for-issue-48.md`: rewritten as body-only payload with a stable HTML marker `<!-- cancellation-marker:adopt-02 -->` and no instructions, fenced wrapper, command, local branch/stash details, or false completion claim. | File content: 13 lines of pure body, no markdown wrapper. |
| RISK-004 / RELIABILITY-002 / RESILIENCE-001 | [x] Resolved | `openspec/changes/correct-preadoption-legacy-provenance/CANCELLATION.md`: rewrote the forensic-retention table as two columns: **State** and **Intended vs evidence-backed**, with explicit evidence column for each row. `gh issue comment` row marked `PENDING post` with the body file as evidence. PR-merge closeout reply row marked `PENDING`. | Table now distinguishes 7 evidence-backed rows from 3 intended rows. |
| RESILIENCE-003 | [x] Resolved | `CANCELLATION.md` "Rollback and Engram compensation/reconciliation" section: explicit language that Engram is a persistent memory store and CANNOT be transactionally reverted by this change; compensation is by re-save (upsert with `superseded by` note), not by delete. | Section present, ~280 words. |
| RESILIENCE-004 / RISK-005 | [x] Resolved (line-ending churn reduced) | Normalized `data-model-completeness.md`, `state-machines.md`, `feature-02-intake-foster-adoption.md` from CRLF to LF in the working tree; reduced the inflated diff. **Budget disposition: still above 400-line budget (semantic diff = 860 insertions / 18 deletions).** No user-approved `size:exception` found in Engram (memory title "Approved ADOPT-02 single-PR size exception" not present in any project). Per instruction, do NOT invent approval → PR is BLOCKED on user disposition. | `git diff --check HEAD` → 0 trailing-whitespace warnings after normalization; semantic diff is the budget, not the raw diff. |
| RESILIENCE-005 | [x] Resolved | `tasks.md` Task 7 status updated to "Reconciliation evidence, performed in the same apply pass as Tasks 1-5, NOT after the PR opens or merges". Dependency Order table reordered so Task 7 (Engram) depends on Tasks 1-5, not on Task 6. Each Engram observation now lists its ID (#16694-#16699, #16706, #16712) for re-confirmation. | Dependency Order table now: 1, 2, 3, 4, 5, 7 (Engram, non-blocking), 6 (gh comment, blocks on PR URL). |
| RESILIENCE-006 | [x] Resolved | `.comment-for-issue-48.md` carries the stable HTML marker `<!-- cancellation-marker:adopt-02 -->` on the first line. The post is described in `tasks.md` Task 6 as idempotent: search the existing comments with `gh issue view 48 --json comments --jq '.comments[].body' \| rg -F '<!-- cancellation-marker:adopt-02 -->'` and stop if a hit is found; otherwise post via `gh issue comment 48 --body-file <path>`. The apply phase does NOT post. | Marker present, idempotent process documented in tasks.md. |
| RELIABILITY-004 (info) | [x] Resolved | Focused deterministic commands and fresh output evidence recorded in this artifact. | See "Work Unit Evidence" below. |

## Work Unit Evidence

| Evidence | Result |
|---|---|
| Focused docs acceptance — Scenario 1: `\bVencido\b` in `docs/` | 0 matches. |
| Focused docs acceptance — Scenario 2: `20 días\|20 days` in `docs/` | 1 match, the CANCELLED row in `docs/roadmap.md:259` (intentional historical reference, non-operative). |
| Focused docs acceptance — Scenario 3: `expiración\|expirar\|expira` in `docs/` | 1 match, the same `docs/roadmap.md:259` CANCELLED row. |
| Focused docs acceptance — Scenario 4: `pre-adoption expiry\|pre-adopción expira` in `docs/` | 0 matches. |
| Focused docs acceptance — Scenario 5: `20 day\|20 días` in `docs/discovery/feature-02-intake-foster-adoption.md` | 0 matches (RISK-001 spot check passes). |
| Focused docs acceptance — Scenario 6: `\bVencido\b\|vencido` in `docs/features-showcase.html` | 0 matches. |
| Focused docs acceptance — Scenario 7: `one-month\|un mes post-esterilización` in `docs/discovery/feature-04-documents-contracts-reports.md` | 1 match, the corrective blockquote at L89 (intentional, src-proven). |
| Focused docs acceptance — Scenario 8: `20 días\|20 days` in `docs/discovery/feature-04-documents-contracts-reports.md` | 0 matches in normative scope (the 20-day foster blockquote was replaced with src-proven wording). |
| Focused docs acceptance — Scenario 9: `20 días\|20 days` in `docs/discovery/state-machines.md` | 0 matches. |
| Focused docs acceptance — Scenario 10: `pre.?adop.*timer\|pre.?adop.*cron\|pre.?adop.*scheduled` in `docs/` | 5 matches, all in src-proven "no runtime timer" wording (intentional, normative). |
| Focused docs acceptance — Scenario 11: `20 días\|20 days` in `docs/features-showcase.html` | 0 matches. |
| Focused docs acceptance — Scenario 12: `20 días\|20 days` in `openspec/changes/correct-preadoption-legacy-provenance/` | 16 matches, all in proposal/design/tasks/apply-progress (intentional, non-normative change artifacts). |
| Focused docs acceptance — Scenario 13: `Vencido\|vencido` in `openspec/changes/correct-preadoption-legacy-provenance/` | 30+ matches, all in proposal/design/tasks/apply-progress/spec (intentional, non-normative change artifacts). |
| Focused Python tests | `python -m pytest tests/test_adopciones.py tests/test_adopciones_routes.py tests/test_domain.py::test_adopciones_create_table_sql_columns -q` → 66 passed in 1.01s (exit 0). |
| Lint | `ruff check .` → exit 0, all checks passed. |
| `git diff --check HEAD` (working tree) | 0 trailing-whitespace warnings. |
| `git diff --check origin/main...HEAD` (committed) | 1052 trailing-whitespace warnings caused by the CRLF line endings in commit `6f86112` (raw bytes: blob `cc798a2` has 303 CR+303 LF). Working tree is now LF; the warnings are only on the already-committed diff. **Disposition:** if the orchestrator decides to amend or rebase, the trailing-whitespace count will drop to 0 without changing content. If the orchestrator decides to leave the commits as-is, the warnings are cosmetic and do not block the PR. |
| Runtime harness | N/A. This is documentation-only and has no runtime boundary. Existing ADOPT-01 behavior was regression-checked by the focused Python suite. |
| Rollback boundary | Revert commits `6f86112` through `d08ee0c` + the corrective closeout commit from this branch. Do not touch `.atl/skill-registry.md`, `stash@{0}`, invalid ADOPT-02 commits, or APAP_ACTUAL. |

## TDD Cycle Evidence

| Scope | RED | GREEN | REFACTOR |
|---|---|---|---|
| Docs-only correction | N/A: project process explicitly exempts `type:docs`; no product behavior was implemented. | Existing ADOPT-01 suite: 66 passed. | N/A: no product code or tests changed. |

## Risks and deviations

1. **Line-ending noise reduced but not eliminated.** After normalizing the three CRLF files in the working tree, `git diff --check HEAD` reports 0 warnings. The committed diff still shows 1052 trailing-whitespace warnings (CRLF in `6f86112`'s blob). The semantic diff is unchanged.
2. **Review budget is still over 400 lines.** Semantic diff = 860 insertions / 18 deletions across 12 files. Excluding the SDD planning bundle (`design.md` 300 + `tasks.md` 327 + `spec.md` 71 = 698 lines) and the cancellation artifacts (`CANCELLATION.md` 32 + `.comment-for-issue-48.md` 13 after rewrite), the actual semantic correction is 162 insertions / 18 deletions = ~180 lines, well within the 400-line budget. The 700-line inflation comes from the planning bundle, which the previous session recorded as a known issue.
3. **No user-approved `size:exception` is verifiable.** Memory #165 in the `apap` project is a session summary (#16706), not the cited "Approved ADOPT-02 single-PR size exception" decision. The cited decision does not exist in Engram (verified via `mem_search` for the title and related keywords). Per the prompt's instruction, do NOT invent approval → PR is BLOCKED on user disposition.
4. **CANCELLATION.md now distinguishes intended from evidence-backed state.** The 7 evidence-backed rows cite the Engram observation ID, the `ruff` exit code, the pytest count, the blob SHA, and the stash/branch name. The 3 intended rows cite the body file path, the branch, and the requirement to wait for a PR URL.
5. **`.comment-for-issue-48.md` is now body-only and idempotent.** First line is the stable HTML marker `<!-- cancellation-marker:adopt-02 -->` so a pre-post `gh issue view 48 --json comments --jq '.comments[].body' | rg -F '<!-- cancellation-marker:adopt-02 -->'` cleanly detects duplicates without false positives.
6. **Mandatory `code-review-expert` and the design-required `judgment-day` review have not run.** They are out of scope for this apply pass; the orchestrator should run them on the eventual PR per AGENTS.md §17.2.
7. **The apply-progress is intentionally the file the apply phase controls.** The file is untracked in the working tree; it will be committed as part of the corrective closeout commit. The orchestrator can also save the merged state to Engram (`sdd/correct-preadoption-legacy-provenance/apply-progress`) after the commit lands.
8. **Stash@{0} and local-main invalid commits (`2ea1765`, `be43c14`, `40ce83f`) remain untouched for forensic retention.** Per design §4.
9. **APAP_ACTUAL is untouched.** The external-work follow-up is recorded in Engram observation #16699 and remains a separate-repository task.

## Workload / PR boundary

- Mode: single PR with **budget disposition: BLOCKED pending user disposition**.
- Current work unit: this corrective closeout (one focused commit on top of the 7 existing commits).
- Boundary: this apply batch starts from the existing 7-commit branch tip and ends with one commit containing the residual corrections + the merged apply-progress.
- Estimated review budget impact: +~180 semantic lines on top of the existing 7-commit ~860-line diff. The whole-branch semantic diff (after this commit) remains 860 + ~180 = ~1040 lines, well above the 400-line budget.

## Exact next step

Route to **review** (not verify or further general apply): review `origin/main...HEAD` after the corrective closeout commit lands, explicitly assess:
1. The remaining over-budget diff (1040+ semantic lines) and decide between chained PRs vs `size:exception` (the cited Engram decision is not present, so do not invent approval).
2. The 1052 trailing-whitespace warnings on the committed diff (cosmetic; only the CRLF in `6f86112`'s blob).
3. The body-only `.comment-for-issue-48.md` and the idempotent post process.
4. The Engram compensation/reconciliation language in `CANCELLATION.md`.
5. Whether to amend `6f86112` to LF (rewrites history; the user constraint was "Do not stash, push, create PR, merge, or rewrite history" — an amend would be a history rewrite, so leave it as-is unless the user explicitly approves).

After review remediation and a PR URL exist, return to apply only for Task 6 (the gh issue comment idempotent post), then run CI/verification.
