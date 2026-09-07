# Quality harness — roadmap and handoff

**Purpose.** This document lets a different agent (or a future session) continue
the code-quality hardening work without re-deriving what was already measured.
Everything below was verified by running it on 2026-08-06, not inferred.

Read this before touching `scripts/check_*.py`, `docs/quality/`, the `mutation`
job in `ci.yml`, or AGENTS.md §34.

Source of the discipline: [unclebob/swarm-forge](https://github.com/unclebob/swarm-forge),
adapted from its agent-role model to this repo's gate model. Tracking issues:
#428 (PR #1), #431 (PR #2), #433, #434, #435.

---

## 1. State of play

### Done and pushed

PR #432 (DRAFT, branch `feat/quality-gates-mutation`, stacked on
`feat/quality-gates-foundations` — **do not merge before PR #1 / #428**):

| Artifact | What it does |
|---|---|
| `scripts/check_mutation.py` | Degenerate-run guard + shrink-only survivor ratchet |
| `tests/test_check_mutation.py` | 24 tests over synthetic sessions; green on Windows |
| `docs/quality/cosmic-ray.toml` | Pilot target + mandatory equivalent-mutant filter |
| `docs/quality/mutation-baseline.json` | `migration/derivation.py: 38`, platform-labelled, PROVISIONAL |
| `docs/runbooks/mutation-testing.md` | WSL setup, acquisition, failure decoding |
| `ci.yml` → `mutation` job | Schedule + `workflow_dispatch` only, never per-PR |
| `tests/test_ci_workflow.py` | 4 pins: gate, filter, triggers, `PYTHONHASHSEED` |
| `Makefile` → `mutation` | Refuses to run outside Linux |
| `AGENTS.md` §34 | The doctrine behind all of it |

### The open wound — fix this first

```
$ git log --all --oneline -- scripts/check_layers.py
(empty)
```

`scripts/check_layers.py` (556 lines), `tests/test_layers.py` (14.5 KB) and
`docs/architecture/capas-y-slices.md` (5.6 KB) exist **only as uncommitted files
in the main checkout's working tree**. Never committed on any branch. `rg -c
check_layers` returns 0 against both `origin/main`'s and this branch's `ci.yml`.

**Consequence: there is no deterministic architecture enforcement running
anywhere today.** AGENTS.md §33 (slice location) is on `origin/main`; its gate is
not. That is §32.P3 applied to the most important rule in the repo, and the
harness survives only as local disk state on one machine.

The gate itself is good — three explicit axes, `ALLOWED_IMPORTS` rather than an
implied ordering, only 4 baseline entries each with a written justification, a
test that detects stale entries. It is a well-built gate that is switched off.

**Also note:** the main checkout has ~204 uncommitted files (the hexagonal
vertical-slice refactor of epic #420 in flight). Do not clobber it. Work in a
worktree.

---

## 2. Ordered plan

### Step 1 — Commit the hexagonal harness (severity: everything else is secondary)

- Rescue `scripts/check_layers.py`, `tests/test_layers.py`,
  `docs/architecture/capas-y-slices.md` from the working tree onto a branch.
- Wire `python scripts/check_layers.py` into the `lint` job of `ci.yml`, after
  the route-size ratchet.
- Pin the step with `tests/test_layers.py::test_ci_workflow_lint_job_runs_layers_gate`
  using the `_job_executable(workflow, "\n  lint:", "\n  security:")` helper
  already in `tests/test_ci_workflow.py`.
- Update AGENTS.md §33's Enforcement line: it currently says PR review; it should
  name the gate.

Until this lands, every later step rests on nothing.

### Step 2 — Slice-completeness gate (the real gap)

`check_layers.py` proves *"no forbidden import"*. That is necessary and nowhere
near sufficient for "real hexagonal". Nothing today proves a slice is **complete**.

Build a gate that, for each slice under `app/core/<layer>/<slice>/` and
`app/modules/<slice>/`, asserts:

- a port Protocol is declared in `ports/` for every outbound dependency;
- the adapter is constructed in `app/core/di/` and **injected**, never imported
  by the application layer (partially covered by axis 1 — make it explicit);
- the application layer imports no concrete adapter symbol;
- each layer of the slice has at least one test file.

Shrink-only `BASELINE` for slices that predate the gate, same contract as the
other ratchets. This is what turns "hexagonal" from declarative into verifiable.

### Step 3 — Extend the layer gate to `migration/`

`SCAN_DIRS = ("app",)` today. `migration/` is excluded by a comment calling it a
standalone ETL tool — but it holds the most complex code in the repo
(`reconcile.py` 976 LOC, `apply.py` 869, `diff_engine.py` 642). Either extend the
gate or give `migration/` its own explicit boundary gate. Do not leave it
unstated.

### Step 4 — Architecture reviewer agent (complement, never the guarantee)

A skill/subagent that reviews a diff against §31/§33/§34 and reports findings,
referenced from AGENTS.md.

**State its scope honestly in the file itself:** an LLM reviewer is
non-deterministic and cannot be the thing that "cannot be deviated from". It is a
second read for judgement-level concerns no AST can see. If the guarantee rests
on it, there is no guarantee — the determinism lives in the gates. This is
AGENTS.md §34.3 applied to the reviewer itself.

### Step 5 — Grow the mutation target set (#434)

Ordered by measured density. One module per PR, each with its baseline entry
acquired **on Linux**.

### Step 6 — Kill the pilot's survivors (#433) and close the query-test gap (#435)

---

## 3. Hard-won facts — do not re-derive these

### Mutation tooling

1. **cosmic-ray 8.4.6 does not work on native Windows.** 100% of mutants come
   back `INCOMPETENT` — measured 27/27 on a 12-line control module and 233/233
   on `migration/derivation.py`. The same control module on WSL returns 27/27
   `KILLED`.
2. **`cr-rate` cannot detect this.** It reports `0.00` and exits 0 for both a
   perfect run and a run where nothing executed. `cr-rate --fail-over 20` passes
   on the broken session. This is why `scripts/check_mutation.py` exists.
3. **`mutmut` 3.7.0 refuses to start on Windows** by design (upstream
   boxed/mutmut#397). Not an alternative.
4. **`cosmic-ray exec` has no `--worker-count` option** in 8.4.6, and the `local`
   distributor is already sequential. TASK-2.1's W-5 flag does not exist.
   `PYTHONHASHSEED=0` is real and is kept.
5. **The worker spawns without a shell**, so a bare `python` in `test-command`
   may not resolve. `cosmic-ray baseline` then fails with a near-empty error
   block. When that happens, run the `test-command` by hand — the real cause
   surfaces only that way. (It was a missing `pytest-cov` making `--no-cov`
   unrecognised.)
6. **PEP 604 annotation mutants are unkillable.** `ReplaceBinaryOperator_BitOr_*`
   mutates the `|` in `str | None`; with `from __future__ import annotations`
   those never evaluate. On the pilot they were **66 of 104 reported survivors**
   — 63% noise. `cr-filter-operators` between `init` and `exec` is mandatory.
7. **Filtered mutants carry `worker_outcome = SKIPPED` and a NULL
   `test_outcome`.** They are neither pending nor results. Reading them as
   pending rejects every filtered session as incomplete — a real defect that was
   found and fixed in `check_mutation.py`.
8. **Session schema** (verified against a real session): tables `work_items`,
   `mutation_specs`, `work_results`; outcomes stored as SQLAlchemy member
   **names** (`KILLED`), while `TestOutcome` is a `StrEnum` whose values are
   lowercase. Normalise both.
9. **`Path.as_posix()` is OS-dependent on Windows-recorded SQLite paths.**
   `Path("app\\modules\\m.py").as_posix()` returns `"app/modules/m.py"` on
   Windows but `"app\\modules\\m.py"` on Linux. Cross-platform session reads
   need an explicit `.replace("\\", "/")` before `.as_posix()` — added during
   PR #432 rebase after CI failed `test_read_session_normalizes_windows_module_paths`.

### Where mutation testing pays, and where it does not

Measured mutable AST sites (`Compare`/`BoolOp`/`BinOp`/`not`/`AugAssign`/branch):
**3579 across 217 files** in `app/` + `migration/`. A whole-tree session runs for
days — `module-path = "app"` is not viable.

The §22 "pure seam" is almost empty of mutable sites, because no mainstream
Python engine mutates string literals:

| Module | LOC | Sites |
|---|---:|---:|
| `salud/queries.py` | 313 | **2** |
| `sanidad/queries.py` | 308 | 4 |
| `adopciones/queries.py` | 272 | 14 |
| `animals/queries.py` | 238 | **65** |

Highest-value targets, by density:

| Module | LOC | Sites | /100 LOC |
|---|---:|---:|---:|
| `migration/derivation.py` | 396 | 84 | 21.2 ✅ pilot |
| `app/modules/adopciones/service.py` | 527 | 110 | 20.9 |
| `migration/diff_engine.py` | 642 | 131 | 20.4 |
| `app/core/local_backend.py` | 690 | 112 | 16.2 |

### Environment

- **WSL recipe that works** (Ubuntu 22.04, `python3-venv` is absent and needs
  sudo, so use user-site):
  ```bash
  pip3 install -q --user --break-system-packages pytest pytest-cov pytest-asyncio \
      cosmic-ray fastapi starlette jinja2 pydantic pydantic-settings \
      python-multipart httpx itsdangerous rapidfuzz
  ```
- **Copy the tree to WSL's native filesystem.** Measured on the same test:
  `~/` 0.10 s, Windows native 0.16 s, **`/mnt/c` 4.52 s (45× penalty)**. Also,
  cosmic-ray mutates files in place — never point it at a live worktree.
- **`pytest-randomly` is pinned on `feat/quality-gates-foundations`.** If it is
  missing locally, the suite aborts on `--randomly-dont-reorganize`. Run with
  `-o addopts=""`. CI is the authority for a full-suite verdict.
- **`make` is not installed on the Windows workstation.** Verify Makefile recipes
  by reasoning or under WSL.

### Parallel PRs and rebase

- **Two PRs developed in parallel out of order will silently delete each other
  on rebase.** PR #438 (hexagonal) and PR #429 (foundations) both touched
  `ci.yml`, `AGENTS.md`, `Makefile`, `pyproject.toml`. PR #438 was branched off
  main before PR #429 existed, so it DELETED 8 files PR #429 added (`scripts/check_crap.py`,
  `scripts/check_jscpd.py`, `scripts/check_mutation_sites.py`, plus 5 test files,
  `git-hooks/pre-commit`, `openspec/changes/quality-gates-expansion/tasks.md`).
  An automated rebase would have honored the deletions. Resolution: cherry-pick
  PR #438's ADDITIONS only, discard the deletions. This is what #444 does.

---

## 4. Standing judgement on the harness

Recorded so the next agent inherits the assessment, not just the artifacts.

**Genuinely strong:** mypy at zero errors over 216 files (binary, no ratchet, no
escape). The ratchet pattern itself — better brownfield engineering than the
source repo, which has no such story.

**Weak, and honestly so:**

- **Architecture is not enforced at all today** (§1 above). Highest severity.
- **The mutation gate covers 1 module of 217 — 0.46%.** It is a real instrument
  at pilot scope. It does not yet provide assurance about the codebase; it
  provides a method and a first measurement. Do not oversell it.
- **Ratchets freeze debt, they do not reduce it.** `check_ruff_ratchet` tolerates
  434 findings; jscpd tolerates 1.88% duplication. The repo can sit at baseline
  forever with every gate green. Ratchets stop growth; a separate, deliberate
  effort reduces the stock.
- **Coverage floors measure execution, not assertion.** That gap is exactly what
  the mutation gate exists to close, and it is 0.46% closed.

**The rule to carry forward (AGENTS.md §34.3):** when you add a quality metric,
write down what a broken measurement looks like and make the gate fail on it. A
metric whose failure mode is silence is worse than no metric, because it
manufactures confidence.

---

## 4. Session log — 2026-08-06

Continuation session, ~5 hours, user out of house partway through.

### Done

| # | PR | Commit | What |
|---|---|---|---|
| A1 | #439 | `e653904` (squash `e94c34c`) | Integration job fix: `--override-ini` + `tests/integration` collection. Merged to `feat/quality-gates-foundations`. |
| A2 | #429 | `fde7c42` | Merge to `main` (squash of foundations). |
| A3 | #432 | `ba489c6` | Rebase onto post-#429 main. Added **tag trigger** to `mutation` job (`startsWith(github.ref, 'refs/tags/')`) — missing from the original PR. Added **backslash normalization** in `scripts/check_mutation.py` (Linux `Path` doesn't treat `\` as a separator, so `as_posix()` on Windows-recorded session SQLite was OS-dependent — `test_read_session_normalizes_windows_module_paths` failed in CI until `.replace("\\", "/")` was added). Merged. |
| B1 | #444 | `91e6f79` | Rebase-and-merge of PR #438's hexagonal layer gate onto post-#429 + post-#432 main. The PR #438 branch was developed in parallel to PR #429 and DELETED 8 files + 17 lines of `pyproject.toml` that PR #429 added — resolution was to bring only the additions (check_layers.py, test_layers.py, capas-y-slices.md, ci.yml step, AGENTS.md §33 enforcement, Makefile check-layers target). Plus a lint-clean refactor of `scripts/check_layers.py` (C901/PLR0911/PLR2004/SIM102) with **zero baseline bump** — Path A only, no Path B. File grew 609 → 673 lines (still under §21 cap). |
| B2 | #447 | `61e1ad1` | Resolve #437: `_check_slice` recognises a target under `app/core/` as cross-cutting (asymmetric: `modules/.../delivery → core/...` allowed; `core/<slice_a>/<file> → core/<slice_b>/<submodule>` for non-di still banned). New helper `_is_cross_cutting_core_target(module, layer)` — `layer == "delivery"` guard makes it one-directional. Removed `@pytest.mark.xfail(strict=True)` from `test_delivery_may_import_inward`. BASELINE entries removed: **none** (issue text mentions animals/acogidas routes, but actual code imports `app.core.auth_dependencies`, not `app.core.application.auth.get_user`). |
| C1 | #446 | `4e2863a` | Added 36 cases for the former animal query shim. Epic #420 later retired that shim in favor of the LocalBackend adapter query seam. |
| C2 | #448 | `c5ad0bc` | 36 table-driven test cases in `tests/test_derivation.py` that exercise each surviving-mutation cluster independently (priority-cascade clauses, `==`/`!=` boundary literals, identity operators, missing-vs-zero key fallbacks). Plus a baseline-pin test in `tests/test_ci_workflow.py` (AGENTS.md §32.P3) that asserts `mutation-baseline.json[migration/derivation.py]` stays ≤ 38. **Baseline left at 38 (Path X)** — Linux acquisition required for a real number; CI `mutation` job (schedule+dispatch+tag) will corroborate the new count on its next run; a follow-up PR narrows the entry. |
| CI | #452 | `b53109b` | Migrate basic CI gates from `runs-on: [self-hosted, Linux, ARM64, apap, oracle]` to `runs-on: ubuntu-latest` because the Oracle VPS runner developed a chronic session-renewal problem. Also fixed `tests/test_security_scanning.py` (still asserting the old runner) and refactored `migration/lock.py::acquire_lock` to lower its CRAP score from 26.54 to 1.00 (CC 14 → 1, 5 small helpers, 100% coverage). |
| B3 | #449 | `e430140` | Slice-completeness gate (`scripts/check_slice_completeness.py`, 759 LOC since `scripts/` is exempt from the §21 cap). Four assertions per slice: port Protocol declared, adapter wired from `di/`, application layer adapter-free, every occupied layer has a test file. 23 tests pass; gate OK with 4 baselined violations. |
| A4 | #450 | `1822222` | Add `app/modules/adopciones/service.py` (110 sites / 527 LOC = 20.9/100 LOC) to cosmic-ray target set with `PENDING LINUX ACQUISITION` baseline marker (14-day grace period via `check_pending_overdue()` in `scripts/check_mutation.py`). |
| B4 | #451 | `cce67b3` | Migration boundary gate (`scripts/check_migration_boundaries.py`, 672 → 699 LOC after jscpd refactor). Three file classes (pure / access-bound / orchestration) each with its forbidden-import set, plus tests-per-module. The jscpd refactor collapsed three Type-2 clones (`_check_pure` / `_check_access_bound` / `_check_orchestration`) into a single `_RULES` data tuple; jscpd dropped from 1.93% (FAIL) to 1.74% (PASS against 1.88% baseline) on Linux Python 3.14. |

### Open after this session

| # | PR | What |
|---|---|---|
| B3 | (next) | Slice-completeness gate (the real gap): port Protocol declared, adapter injected from `di/`, test per layer. New script `scripts/check_slice_completeness.py` to keep `check_layers.py` under the §21 cap. |
| B4 | (next) | Layer gate for `migration/` as a separate file (`scripts/check_migration_boundaries.py`), not extending `check_layers.py`. `migration/` is not hexagonal — it has derivation (pure), legacy access (Access-bound), orchestration (apply/reconcile/cli). Forcing hexagonal rules on ETL breaks §32.P3. |
| A4 | (next) | Add `app/modules/adopciones/service.py` to mutation target set (#434, 20.9 sites/100 LOC). **Linux baseline acquisition required — can't run cosmic-ray on Windows**. PR lands the `module-path` change with a `PENDING LINUX ACQUISITION` marker in `mutation-baseline.json`, pinned by a test that fails if the marker survives past the first schedule run after the PR lands. |

### Decisions taken while the user was out (reversible)

| # | Decision | Why |
|---|---|---|
| D1 | Delegated B-track and C-track to subagents in fresh worktrees, per §17.1 | orchestrator coordinates, subagents write |
| D2 | A4 PR lands with `PENDING LINUX ACQUISITION` baseline marker, not skipped | §32.P3 — a measurement whose failure mode is silence is worse than no measurement |
| D3 | B4 is a separate gate (`check_migration_boundaries.py`), not an extension of `check_layers.py` | `migration/` is not hexagonal; forcing hexagonal rules on ETL manufactures false confidence |
| D4 | C2 tests written without local verification that mutations die (Windows-broken cosmic-ray). Baseline entry pinned to the pre-PR main-branch measurement | Same as D2; CI `mutation` job (Linux, scheduled) will corroborate |
| D5 | For C1, `codegraph_explore` preceded inspection of the then-current animal query shim | §14 — CodeGraph is Read-equivalent |

All five are reversible. Tell me when you're back if any of them should be undone.

### Facts learned that aren't in this roadmap yet

1. **The original PR #432's `mutation` job was missing the tag trigger.** The rebase revealed it: `if: schedule || workflow_dispatch` only. Added `startsWith(github.ref, 'refs/tags/')` because §32.P7 and AGENTS.md §34.2 require release tags to bundle mutation evidence. The test that pins "no pull_request" trigger still passes.
2. **Linux `Path` doesn't treat backslashes as separators.** `Path("app\\modules\\m.py").as_posix()` returns `"app\\modules\\m.py"` on Linux but `"app/modules/m.py"` on Windows. CI test `test_read_session_normalizes_windows_module_paths` was written assuming the cross-platform equivalence; the implementation needed an explicit `.replace("\\", "/")` before `as_posix()`.
3. **Parallel-universe PRs.** PR #438 (hexagonal gate) was developed in parallel to PR #429 (foundations). When PR #429 landed first, the rebase of PR #438 onto main revealed 8 file deletions + 17 lines of pyproject.toml removed that PR #429 added. Resolution was to bring only the additions. Lesson: when two PRs touching similar files land out of order, the second rebase must be done by someone with the full spec — an automated rebase will silently delete.
4. **The extended ruff ratchet scope excludes `tests/` by design.** `SCOPE = ("app", "migration", "scripts")`. In `tests/`, `assert` (S101), magic values (PLR2004), and unused args (ARG*) are idiomatic. Including them would add ~4200 baseline entries with no signal. Discovered while reading `check_ruff_ratchet.py` during B1's refactor.

### Open worktrees to clean up

- `C:/00repos/codigo/APAP_WEB_worktrees/wt-rebase-pr432` (A3, merged)
- `C:/00repos/codigo/APAP_WEB_worktrees/wt-fix-pr438-lint-and-437` (B1, merged)
- `C:/00repos/codigo/APAP_WEB_worktrees/wt-roadmap-update` (this PR)
- `C:/00repos/codigo/APAP_WEB_worktrees/wt-fix-437` (B2, merged)
- `C:/00repos/codigo/APAP_WEB_worktrees/wt-test-animals-queries` (C1, merged)
- `C:/00repos/codigo/APAP_WEB_worktrees/wt-fix-derivation-survivors` (C2, merged)
- `C:/00repos/codigo/APAP_WEB_worktrees/wt-ci-move-to-github` (PR #452, open)
- `C:/00repos/codigo/APAP_WEB_worktrees/wt-slice-completeness-gate` (B3, waiting on CI)
- `C:/00repos/codigo/APAP_WEB_worktrees/wt-migration-boundaries-gate` (B4, waiting on CI)
- `C:/00repos/codigo/APAP_WEB_worktrees/wt-mutation-target-adopciones` (A4, waiting on CI)

Run after session: `git worktree remove <path> --force` then `git branch -d <local-branch>`.

### CI infrastructure incident — 2026-08-06 afternoon

The project-owned self-hosted runner (`apap-web-oracle-arm64`, Oracle VPS) developed a zombie session: the listener process reported "Connected to GitHub" but GitHub-side the runner stayed `offline` and never picked up queued jobs. Three PRs (#449, #450, #451) hit the 1.5h timeout and got auto-cancelled. Cause: when systemd restarts the runner service, the orphaned listener PIDs from the previous session survive in the cgroup (they were reparented to PID 1 when the original parent exited), and they continue to hold the GitHub session. systemd restart does not reap them. The new listener reports "Connected to GitHub" but actually gets `Runner connect error: Error: Conflict. Retrying until reconnected` on every retry.

Workaround that worked: `sudo systemctl stop` + `sudo kill -9 <old PIDs>` + `sudo systemctl start`. But the underlying fragility remains.

**Decision:** PR #452 (open) migrates the basic gates from `runs-on: [self-hosted, ...]` to `runs-on: ubuntu-latest`. The self-hosted choice was historical (#355 double-Postgres billing); every job in this repo is pure Python or Postgres-service-container, all portable to GitHub-hosted. The e2e job keeps its conditional self-hosted fallback. APAP_WEB is private; estimated CI usage is well below the 2,000 min/month free tier.

**Open follow-up:** investigate whether to keep the self-hosted runner registered. The VPS is paid for; if no job uses it, the runner is dead weight. Decision deferred to the user.

### See also

- `docs/quality/pendientes-2026-08-06.md` — the running file the agent left for the user while out of house.
