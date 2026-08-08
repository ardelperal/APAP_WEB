# Proposal: Quality Gates Expansion

## 1. Summary

Add five new deterministic quality gates (CRAP score, mutation testing, property-based testing, formal DRY detection, mutation-sites count) plus two refinements to existing gates (adapter exclusion from global coverage, "QA-through-UI only" crystallised in AGENTS.md §23). Every new detector ships with a shrink-only baseline so the first CI run cannot break the build.

## 2. Why now

Source analysis of `unclebob/swarm-forge` (Engram observation **#24073**, topic `sdd/quality-gates-expansion/source`) surfaced a catalogue of deterministic checks that project-owned rules (§11, §19, §20, §21, §24, §25–§28, §23) do not yet cover. Existing 80% line coverage proves only that **lines** were executed; it does not prove that **assertions** exist. CRAP score, mutation testing, and property tests close that gap without teaching the codebase new patterns.

## 3. Scope

### In scope

| # | Feature | Tool | New surface |
|---|---------|------|-------------|
| 1 | CRAP score threshold = A | `radon cc -s -n A` + `xenon` | CI `lint` job + pre-commit |
| 2 | Mutation testing | `cosmic-ray` (baseline + diff) | new nightly CI job + pre-push |
| 3 | Property-based testing | `hypothesis` | `tests/property/` + first targets = `_row_to_*` helpers |
| 4 | Formal DRY detection | `jscpd` | new `scripts/check_jscpd.py` (mirrors §21) |
| 5 | Mutation-sites count pre-PR | AST/scan counter | new `scripts/check_mutation_sites.py` |
| Bonus A | Adapter exclusion from coverage floor | `pyproject.toml` + `ci.yml` | `app/core/insforge.py` excluded from `fail_under` |
| Bonus B | "QA-through-UI only" explicit in §23 | AGENTS.md text clarification | feature branch + PR (per §17.3) |
| Hooks | Pre-commit (advisory) + Pre-push (advisory) | git hooks | touches `git-hooks/` (per §15.5; user OK granted this session) |

### Out of scope

- Gherkin/BDD (project uses pytest), Speclj (Clojure only), AI-judgment architectural reviews (already covered by `code-review-expert` + `judgment-day`).
- Replacing or relaxing any existing gate (§19, §20, §21, §24, §25–§28).
- Any business-domain change — no routes, services, slices, or templates touched.
- Editing `git-hooks/` outside the explicit user-granted scope this session.

## 4. Approach (3 chained PRs, independently revertable)

**PR #1 — Foundations.** CRAP gate + jscpd baseline + mutation-sites count + adapter exclusion + §23 text update + pre-commit hook. All new detectors ship with shrink-only baselines that match the current measured tree, so `make ci` stays green on the first PR. AGENTS.md edit goes through the feature-branch + PR flow per §17.3.

**PR #2 — Mutation real.** `cosmic-ray` baseline acquisition (one full run, captures surviving mutants into a checked-in manifest), nightly CI job that **only fails on regression vs the manifest**, pre-push hook doing a fast `mutmut` scan on the diff. No source code changes unless the baseline is empty.

**PR #3 — Property tests.** `hypothesis` dev-dep + `tests/property/` skeleton + first target set = the `_row_to_*` helpers already in `CRITICAL_HELPERS` (§11). Each property proves an invariant the existing example-based tests check by hand (e.g. "all-None row yields model with default scalars", "string normaliser is idempotent").

Delivery strategy: `exception-ok` (per preflight). Review budget: waived by user. Each PR remains an independent revert unit.

## 5. Capabilities

This change adds **tooling** (CI gates, scripts, hooks, dep pins) and **clarifies** an existing rule (AGENTS.md §23). No business spec changes.

- **New capabilities:** None.
- **Modified capabilities:** None.

## 6. Risks & mitigations

| # | Risk | Sev | Mitigation |
|---|------|-----|------------|
| 1 | First CRAP run flags existing offenders | High | Baseline ratchet (mirrors §21). Detectors enter `mode=warn` for the first PR, `mode=block` after the baseline is committed. |
| 2 | First mutation run shows many surviving mutants | High | Same baseline pattern. Gate only on regression. |
| 3 | Hypothesis flakes in CI | Med | Seed control via `pytest-randomly` + `hypothesis` profile; same fixtures as atomic suite. |
| 4 | `git-hooks/` touched (§15.5) | Med | User OK granted this session; PR body cites it. |
| 5 | AGENTS.md §23 edit (§17.3) | Med | Feature branch + PR flow; orchestrator does not edit inline. |
| 6 | Adapter exclusion lowers the visible coverage floor | Med | PR body names the excluded set explicitly; global stays 80%. |
| 7 | New deps cross §8 (no deprecated libs) | Med | Verify `cosmic-ray`, `hypothesis`, `radon`, `xenon`, `jscpd` floors via context7 before pinning. |

## 7. Open questions

1. `mutmut` vs `cosmic-ray` — `cosmic-ray` has a built-in differential manifest matching the "block on regression" pattern, but heavier setup. `mutmut` is simpler but needs a custom baseline wrapper. User preference?
2. Initial `jscpd` threshold — default 5% will likely flag 8–15% until issue #227 lands. Acceptable starting threshold: 15% (matches measurement) or 5% (forces the cleanup)?
3. Hypothesis CI profile — `dev` (fast, default) vs `ci` (slower, with shrinking). Default to `dev` to keep test budget honest, or `ci` to give property tests real teeth?

## 8. Rollback

Each PR is independently revertable. Shrink-only baselines mean the detectors can be deleted by reverting their PR without touching production code. The hook files live in `git-hooks/` and can be removed without recompiling. The nightly mutation job can be disabled by deleting the workflow step. PR #1's merge preserves the current global coverage floor and the `CRITICAL_HELPERS` 100% gate (§11/§19 unchanged).

## 9. Success criteria

- [ ] `make ci` (or equivalent) green on `main` after PR #1 lands.
- [ ] PR #1 ships shrink-only baselines for CRAP, jscpd, and mutation-sites.
- [ ] PR #2 ships a checked-in cosmic-ray manifest; nightly CI blocks on regression.
- [ ] PR #3 ships ≥5 property tests covering `_row_to_*` helpers; they run in the standard CI suite.
- [ ] AGENTS.md §23 explicitly enforces "QA-through-UI only" via the feature-branch + PR flow.
- [ ] Engram topic `sdd/quality-gates-expansion` carries the decision record + the user's parameter choices.

---

**Preflight traceability:** SDD Session Preflight — pace=`auto`, delivery_strategy=`exception-ok`, artifact_store=`hybrid` (engram + openspec), review_budget=waived. Source observation: Engram `#24073` (topic `sdd/quality-gates-expansion/source`). User choices captured: CRAP threshold = A; mutation = nightly only; no Gherkin/Speclj; git-hooks touch is §15.5-gated with session-level user OK.
