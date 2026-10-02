# APAP check-script layer audit (wu5)

> Read-only audit of `scripts/check_*.py` (8 scripts) plus local-vs-CI parity for the
> ruff rulesets. Evidence-grounded: every claim cites `file:line`. The repo was
> not modified; the only write is this file.

## Top-5 findings (severity ordered)

1. **[BLOCKER][GAP-LINT-EXTENDED]** Local `ruff check .` and `make lint` cannot see the extended ruff rulesets (S, ERA, ARG, FAST, N, C901, PLR, SIM, RET, TRY, PTH) — they only run through `scripts/check_ruff_ratchet.py`, so a contributor running plain `ruff check .` is green while CI catches the new violations. Evidence: `pyproject.toml:262` (select = `["E","F","W","I","UP","B"]`); `Makefile:60` (`lint: $(RUFF) check .`); `.github/workflows/ci.yml:210` + `ci.yml:368` (CI runs both `ruff check .` AND `check_ruff_ratchet.py`); `scripts/check_ruff_ratchet.py:52` (`SELECT: str = "S,ERA,ARG,FAST,N,C901,PLR,SIM,RET,TRY,PTH"`).

2. **[HIGH][RATCHET-LOCKIN-MANUAL]** Every shrink on a ratchet BASELINE prints a NOTE telling the human to "update BASELINE to lock in the improvement" (`scripts/check_ruff_ratchet.py:278`, `check_complexity.py:199`, `check_module_size.py:120`, `check_route_size.py:301`, `check_layers.py:679`, `check_import_cycles.py:177`, `check_vulture_guard.py:350`). Only `check_complexity.py` exposes `--emit-baseline` (line 237); the other six ratchets force the operator to hand-edit a literal dict. The 9 BASELINE entries with calibration-history comments (`check_ruff_ratchet.py:91,92,93,118,135,137,161,162,172`) are the proof of repeat occurrence — each one was bumped at some point.

3. **[HIGH][NO-TEST-DOCSTRING-BALANCE]** `scripts/check_docstring_balance.py` has **zero** tests. `grep -rln check_docstring_balance tests/` returns no matches (verified 2026-09-29). CI runs it at `ci.yml:231` and `Makefile:152` exposes a `check-docstring-balance` target that `make verify` chains, yet there is no `tests/test_check_docstring_balance.py`. The failure mode the script guards against — class body swallowed as a string literal at runtime — is silent and irreversible, so the test gap is high-severity.

4. **[MEDIUM][PARITY-NOT-AUTOMATED]** `make verify` is the local preflight (`Makefile:218`, pinned by `tests/test_ci_workflow.py::test_make_verify_covers_locally_runnable_script_gates` at line 2075) and `CONTRIBUTING.md:175-181` tells contributors to run it. But `make lint` (`Makefile:59-60`) — the command every IDE and tutorial will execute — runs only `ruff check .` and is green on code that would fail the ratchet. The ratchet only fires when the human remembers `make verify`, not when they run the documented "lint" target.

5. **[MEDIUM][RUFF-VERSION-DRIFT-RISK]** `scripts/check_ruff_ratchet.py:58` pins `RUFF_VERSION = "0.15.21"` and the script aborts with an actionable message if the installed ruff differs (lines 196-204). But the ratchet and `make verify` do not install that exact version automatically — they only assert it after the fact. If `uv sync` resolves a different ruff for any reason, the local run fails "ruff version mismatch" without pointing the operator at the one command that fixes it. The fallback message (`check_ruff_ratchet.py:201`) tells the operator to reinstall, but the install path itself (`pip install -e ".[dev]"`) re-resolves, so the fix is non-atomic with the gate.

## Per-script findings

### `scripts/check_ruff_ratchet.py` (328 LOC)
- **Gates**: extended ruff rulesets `S, ERA, ARG, FAST, N, C901, PLR, SIM, RET, TRY, PTH` (line 52) against a per-rule shrink-only `BASELINE` (line 65). Scope is `("app", "migration", "scripts")` — tests/ excluded on purpose (lines 41-42). Pinned to ruff `0.15.21` (line 58). If the measured count for any tracked rule exceeds its baseline, the script exits 1 with `FAIL {code}: {n} violation(s), exceeds baseline of {b} (ratchet: counts may only decrease)` (line 271). Any new rule (not in BASELINE) also fails (line 266). On clean: prints `OK ({total} finding(s), all within baseline)` and exits 0 (line 320).
- **Tested**: yes — `tests/test_ruff_ratchet.py` (13 tests, lines 37, 50, 57, 69, 81, 94, 110, 123, 128, 134, 151, 172, 188). Covers the ratchet arithmetic, real-tree pass, SELECT pinning, real `ruff check .` pass, CI wiring, ruff-version match, and pyproject pin.
- **Fails loud**: yes — exit 1, `FAIL <message>` on stdout, `check_ruff_ratchet: {n} violation(s), {total} finding(s) total. Rulesets: S,ERA,ARG,FAST,N,C901,PLR,SIM,RET,TRY,PTH (issue #380).` (line 316). Ruff-version mismatch also exits 1 with a remediation paragraph (lines 197-204). NO output → also a fail (`run_ruff` returns an error string when ruff produced no output, line 243).
- **Maintenance trap**: **NO `--update-baseline` flag.** The script supports no auto-lock-in; the operator must hand-edit `BASELINE` after each NOTE. Confirmed: `grep -nE '\-\-update-baseline|\-\-emit-baseline' scripts/check_ruff_ratchet.py` returns no matches. Compare `check_complexity.py:237` (`emit_baseline = "--emit-baseline" in args`), which DOES support auto-emission.
- **BASELINE constants**: 31 active entries (verified: `python3 -c "import re; print(len(re.findall(r'\"([A-Z]+\d+)\":\s+\d+', open('scripts/check_ruff_ratchet.py').read())))"` → 31) at `scripts/check_ruff_ratchet.py:65-175`. Plus 12 commented-out removals (ERA001, ARG002, PLR0915, PLR1714, PLR1730, RET504, RET505, S112, S603, S608, SIM118, SIM910) at lines 68-74, 75-82, 95-102, 103-111, 112-117, 123-127, 128-134, 138-143, 144-150, 152-158, 164-168, 169-171.
- **Lock-in mechanism**: when measured < baseline, prints `NOTE {code}: {n} violation(s), below baseline of {b} — update BASELINE to lock in the improvement` (line 277-279). The human edits the dict.
- **Pending update NOTES**: 9 entries with calibration-history inline comments (verified via regex search of `+N by|baseline was|bumped|calibrate|raised|lowered|reduced|locked in`):
  - `check_ruff_ratchet.py:91` `"PLR0911": 12,  # +1 by issue #690 (check_web_to_legacy_check_only adds a PENDING return path)  # was: +1 by PR #630 (scheduling.py adds too-many-returns)  # locked in 2026-08-24: one too-many-returns site refactored away`
  - `check_ruff_ratchet.py:92` `"PLR0912": 12,  # +1 by issue #690 (check_web_to_legacy_check_only adds a PENDING branch)  # was: bumped 8 -> 9 by Slice 3 (scripts/_ratchet_deadline.py adds 1 too-many-branches)`
  - `check_ruff_ratchet.py:93` `"PLR0913": 47,  # baseline was 43; violations introduced by LIFECYCLE-03 (491b279) before current epic round; calibrate to actual count`
  - `check_ruff_ratchet.py:118` `"PLR2004": 43,  # +2 by PR #630 (periodicity.py magic values)  # lowered by epic #420 final legacy-shim removal`
  - `check_ruff_ratchet.py:135` `"S101": 6,  # +1 by PR #630 (periodicity.py assert)`
  - `check_ruff_ratchet.py:137` `"S110": 6,  # +1 by PR #630 (service.py:67 try-except-pass)`
  - `check_ruff_ratchet.py:161` `"SIM105": 15,  # +1 by PR #630 (service.py:65 try-except-pass)`
  - `check_ruff_ratchet.py:162` `"SIM108": 6,  # +1 by PR #630 (periodicity.py ternary)`
  - `check_ruff_ratchet.py:172` `"TRY003": 186,  # baseline was 177; violations introduced pre-epic; epic #420 current round reduced 182 -> 180`

  These are the BASELINE entries that have at some point been manually edited (calibrated to actual count) — i.e., they are the historical evidence of the maintenance trap recurring.

### `scripts/check_workflows.py` (476 LOC)
- **Gates**: seven GitHub Actions hazards — duplicate workflow keys (line 163), missing job timeout (line 184), fixed host port on a service container (line 219), `gh` CLI invocation on a runner without it (line 265), missing concurrency group / wrong `cancel-in-progress` value (line 281), `docker run` with no `timeout <n> docker info` preflight (line 324), pull_request-reachable jobs without a hosted runner (line 405). Each violation exits the script with 1 (line 461).
- **Tested**: yes — `tests/test_check_workflows.py` (37 tests). Covers every check plus a liveness test: `tests/test_check_workflows.py` walks `.github/workflows/*.yml` and asserts each gate (line count ~16k). The `test_ci_workflow_lint_job_runs_workflow_gate` (referenced from `ci.yml:421`) pins the wiring.
- **Fails loud**: yes. Each violation message names the file, the line, and a remediation paragraph (e.g., `f"{label}: job '{name}' is reachable by pull_request and declares runs-on {runner!r}. Public PR code must run on a literal GitHub-hosted label (e.g. 'ubuntu-24.04'), never self-hosted (issue #782)."` at line 406). Also: **zero workflow files = failure, not pass** (line 463). Exit codes: `2` for invocation error (line 450), `1` for violations, `1` for empty scan.
- **Maintenance trap**: low. The rules are static (regex over runner labels at line 336, hard-coded `_ABSENT_ON_RUNNER = ("gh",)` at line 228). Adding a new runner-class hazard is a one-liner; the absence of `gh` is the only command-line scan (line 263).

### `scripts/check_docstring_balance.py` (123 LOC)
- **Gates**: parses every file argument with `ast.parse` and flags `SyntaxError` whose message matches one of `"unterminated triple-quoted string"`, `"EOF in multi-line string"`, `"unclosed string"`, `"unclosed string literal"` (lines 46-51). Catches the failure mode where a class docstring opens but never closes, swallowing the class body as a string literal (script docstring lines 10-15).
- **Tested**: **NO**. Verified: `grep -rln check_docstring_balance tests/` returns zero matches (command executed 2026-09-29). The script docstring explicitly invokes `pytest_plugin` and `pre-commit` modes (`--stdin`, lines 7-8) that nobody has tested.
- **Fails loud**: yes — exit 1 with per-file `path:lineno: error -> line_text` messages (lines 113-115). Exit 2 for invocation error (lines 88, 104). Clean run prints `check_docstring_balance: clean ({n} files scanned)` (line 119).
- **Maintenance trap**: low — the failure-mode list (line 46) is the canonical CPython error fragments; rotating to a new CPython message would silently drop detection. No tests means a contributor renaming the message strings has no signal.

### `scripts/check_rules.py` (2034 LOC)
- **Gates**: ~15 AST detectors against `app/` and `tests/_rule_helpers/fixtures`. Detectors cover: routes calling `client.execute_sql` (line 668), default-true `is_authorized` (line 740), HTTPException with redirect status (line 778), hardcoded `CHECK (rol IN (` in DDL (line 834), `logger.{info,warning,error,debug,critical,exception}` outside `app/core/logging.py` (line 898), `print(...)` in `app/` (line 1179), CSRF middleware registration (line 1208), CSRF SameSite=Strict (line 1296), unjustified lazy imports (line 1602+), duplicate helpers (line 248), integration-test coverage of `build_*` queries (line 989), `user: Any` in route handlers (line 1121), and the informational PII-route-coverage detector (line 460).
- **Tested**: yes — `tests/test_check_rules.py` (34 tests) plus `tests/test_check_rules_exclusion.py`. Covers each detector with positive and negative fixtures under `tests/_rule_helpers/fixtures/`.
- **Fails loud**: yes — exit 1 with `file:line: rule_id: message` (line 1968). Two informational detectors (`pii_route_coverage` line 460, `query_seam_baseline_note` line 618) print WARNING/INFO and never block CI (line 1997, 2019). Exit 2 for invocation error (line 1940).
- **Maintenance trap**: medium. Seven BASELINE-like dicts: `DEFAULT_EXCLUDES` (line 129), `BASELINE_NO_QUERIES_MODULES` (line 176), `BASELINE_NO_INTEGRATION_TESTS` (line 209), `.check_rulesignore` parsing (line 547), `PII_ROUTES_PARAMETRIZE` parsing (line 276), plus the duplicated-helper baseline inside `_check_duplicate_helper_definitions` and the integration-test baseline inside `_check_integration_test_coverage` (line 1057). Each new legacy module requires touching at least one of these by hand.
- **Lock-in mechanism**: `DEFAULT_EXCLUDES` is the only one without a shrink-only ratchet semantic — the linter uses `--exclude` (line 1957) and `.check_rulesignore` (line 1960) as additive suppressions, not as a ratchet. The `BASELINE_NO_QUERIES_MODULES` and `BASELINE_NO_INTEGRATION_TESTS` ratchets are shrink-only by contract; there's no auto-emit.

### `scripts/check_layers.py` (717 LOC)
- **Gates**: hexagonal dependency direction (`ALLOWED_IMPORTS` line 86), inner-layer purity (no `fastapi`, `httpx`, `psycopg`, etc., in `domain`/`ports`/`application`, line 117), vertical-slice boundaries (line 137), and legacy-domain grandfathering (`catalogos`, line 157). Scan dirs: `("app",)` only (line 63). Baseline is the **ratchet**: 55 entries at `BASELINE` (lines 549-606).
- **Tested**: yes — `tests/test_layers.py` (19 tests). Covers each axis (layer-direction, slice-boundary, slice-internals, purity), the baselined-violation pass (`test_baselined_violation_passes_and_new_one_fails` line 368), the stale-baseline detection (`test_stale_baseline_entry_is_reported_as_a_notice` line 396), and CI wiring (`test_ci_workflow_lint_job_runs_layers_gate` line 414).
- **Fails loud**: yes — exit 1 with `FAIL {rel}: {layer} imports {module} ({target_layer}) -- {hint}` (line 703). Stale-baseline detection emits NOTICE `NOTE {key}: baselined but no longer a violation -- remove the entry from BASELINE in scripts/check_layers.py to lock in the improvement` (line 678-679). 0-file scan still exits 0 by virtue of scanning the configured `SCAN_DIRS`; **liveness is not separately enforced** (unlike `check_workflows.py`).
- **Maintenance trap**: **medium-high**. The 55-entry BASELINE (line 549) was last calibrated against `main @41fbd2a` (line 531), and the comments name 7 entry-reason buckets (`_EPIC_420`, `_EPIC_641`, `_LAZY_CYCLE`). The lock-in is manual: every fix of a baselined violation requires editing the dict (or the entry stays as a NOTICE forever).

### `scripts/check_complexity.py` (268 LOC)
- **Gates**: cyclomatic complexity `CC ≤ 15` (line 39) per function under `app/` or `migration/` (line 42). 13-entry BASELINE (lines 55-72) is shrink-only. Target: 0 entries by 2026-12-31 (line 79). Methods and closures are measured independently (line 122).
- **Tested**: yes — `tests/test_check_complexity.py` (10 tests). Covers methods/closures independence (line 57), nested-branch no-double-counting (line 75), baselined-grow vs baselined-shrink (line 105, 113), stale-baseline detection (line 122), unparseable-file-as-violation (line 131), real-tree pass (line 140), CI wiring (line 147).
- **Fails loud**: yes — exit 1 with `{file_rel}::{func_name}: CC={cc}, exceeds baseline of {b} (ratchet: CC may only decrease)` (line 188). ALSO fails on stale entries: `{file_rel}::{func_name}: in BASELINE_CC but no such function was found — remove the entry or fix the path` (line 205).
- **Maintenance trap**: **LOW (has auto-emit)**. This is the **only one of the 8 scripts with `--emit-baseline`** (`scripts/check_complexity.py:237-244`). When a contributor passes `--emit-baseline`, the script prints a fresh `BASELINE_CC` block — eliminates the manual dict-edit step. The other 7 scripts have no such flag.

### `scripts/check_module_size.py` (185 LOC)
- **Gates**: `MAX_LINES = 700` (line 36) per Python module under `app/` or `migration/` (line 41). 1-entry BASELINE: `"migration/reconcile.py": 976` (line 57). Target: 0 entries by 2026-12-31 (line 64).
- **Tested**: yes — `tests/test_module_size.py` (8 tests). Covers current-tree-pass (line 36), baseline-matches-measured-tree (line 47), new-over-budget (line 71), baselined-grow (line 85), baselined-shrink-with-NOTE (line 99), stale-baseline (line 115), scope-exclusion (line 132), CI wiring (line 144).
- **Fails loud**: yes — exit 1 with `{rel}: {n} lines, exceeds the {max}-line budget (AGENTS.md rule 21) — split the module; do NOT add it to BASELINE` (line 130). Baselines that grew past their recorded size: `{rel}: {n} lines, grew beyond its baseline of {b} (ratchet: baselined modules may only shrink — split it instead of growing it)` (line 112). Stale-baseline detection: `... baselined at {b} lines but the file does not exist under {root} — remove the stale BASELINE entry` (line 138).
- **Maintenance trap**: **low**. Single-baseline, manually-edited. The script docstring at line 53-56 already documents that `apply.py` was previously in BASELINE and was removed when it shrunk under MAX_LINES, so the model is exercised.

### `scripts/check_route_size.py` (400 LOC)
- **Gates**: two-axis ratchet on FastAPI route handlers — `MAX_LINES = 50` per handler (line 63) and `MAX_FORM_PARAMS = 8` per handler (line 71). 10-entry BASELINE (lines 90-112) and 0-entry `FORM_BASELINE` (line 131). Target: 0 entries by 2026-12-31 (line 118). Scans `app/**/*routes*.py` plus `app/main.py` (line 144).
- **Tested**: yes — `tests/test_route_size.py` (14 tests). Covers current-tree pass, baseline-matches-measured-tree, over-budget detection, ratchet-grow, ratchet-shrink, stale-baseline, non-route-function exclusion, CI wiring, plus the full `FORM_BASELINE` axis (form-baseline match, over-form-budget, ratchet-grow, ratchet-shrink, stale-form-baseline, within-budget).
- **Fails loud**: yes — exit 1 with `key: {n} lines, exceeds the {max}-line budget (AGENTS.md rule 28) — move HTTP-unrelated logic to the service layer; do NOT add it to BASELINE` (line 313). Same pattern for FORM_BASELINE (line 343). Stale-baseline detection on both axes (lines 351, 359).
- **Maintenance trap**: **medium**. Two dictionaries to maintain (BASELINE + FORM_BASELINE); the `FORM_BASELINE` is currently empty because CesionForm migration shrank three handlers under the param budget (comment at lines 128-130). The manual lock-in is required when shrinking a baselined handler (line 300) or baselined form handler (line 330).

## Local-vs-CI parity gap

- **Local command (what `ruff check` alone invokes)**: `ruff check .` per `Makefile:60` (`lint: $(RUFF) check .`). The select list comes from `pyproject.toml:262`: `select = ["E", "F", "W", "I", "UP", "B"]` plus `ignore = ["E501", "B008"]` (lines 280-287). Per-file-ignores at line 289. Result: TRY003, S607, PLR0915, ERA001, ARG001, etc. are **invisible** to this command.

- **CI command (exact from workflow file)**: two-step, at `.github/workflows/ci.yml`:
  - Line 210: `run: ruff check .` — same as local; same select; same invisibility.
  - Line 368: `run: python scripts/check_ruff_ratchet.py` — invokes ruff a second time, this time via the ratchet CLI with the extended ruleset. From `scripts/check_ruff_ratchet.py:219-229`:
    ```python
    cmd = [
        sys.executable, "-m", "ruff", "check",
        *targets,
        "--select", SELECT,           # "S,ERA,ARG,FAST,N,C901,PLR,SIM,RET,TRY,PTH"
        "--output-format", "json",
    ]
    ```
    WHERE `targets` is `("app", "migration", "scripts")` from `SCOPE` (line 42).

- **Ruleset / flag delta**:
  - Local `ruff check .` selects `["E", "F", "W", "I", "UP", "B"]` → 6 categories.
  - CI ratchet `--select SELECT` adds `["S", "ERA", "ARG", "FAST", "N", "C901", "PLR", "SIM", "RET", "TRY", "PTH"]` → 11 categories.
  - **No flag (`--fix`) used in CI.** `--output-format json` is used by the ratchet to parse per-code counts (line 228). Local `ruff check .` uses the default text output.

- **Concrete cost (TRY003 186 → 188 case)**: 
  - BASELINE["TRY003"] is `186` at `scripts/check_ruff_ratchet.py:172`. Inline comment: `baseline was 177; violations introduced pre-epic; epic #420 current round reduced 182 -> 180` (line 172, written before the next bumps landed). The historical doc at `docs/policies/lint-policy-try003-plr2004.md:24` recorded the *initial* grandfather as 175 (issue #389, 2026-08-01), confirming the ratchet count has been manually bumped at least four times (175 → 177 → 182 → 180 → 186) — the 9-entry calibration-history list above is the proof of repeat occurrence.
  - If a contributor introduces 2 new `raise ValueError("...")` sites in `app/` or `migration/`, `make lint` returns 0, the IDE ruff plugin returns 0, and `git push` proceeds. Only CI's `python scripts/check_ruff_ratchet.py` (line 368) — or a `make verify` run, which chains `check-ruff-ratchet` at `Makefile:220` — sees the 188 vs 186 mismatch and exits 1. The cost is: every contributor who skips `make verify` ships CI-only failures.

- **Evidence**:
  - `pyproject.toml:262` — local select.
  - `Makefile:60` — local `lint` recipe.
  - `Makefile:218-222` — `verify` chain (17 gates).
  - `scripts/check_ruff_ratchet.py:52` — extended SELECT.
  - `scripts/check_ruff_ratchet.py:219-229` — exact CI ratchet invocation.
  - `scripts/check_ruff_ratchet.py:172` — TRY003 baseline 186.
  - `.github/workflows/ci.yml:210` and `:368` — both steps.
  - `tests/test_ruff_ratchet.py:134` — `test_existing_ruff_gate_still_passes` pins that local `ruff check .` returns 0 against the real tree (i.e., the local gate is genuinely weaker than the ratchet).
  - `tests/test_ruff_ratchet.py:123` — `test_ratchet_passes_against_the_real_tree` pins that the ratchet returns 0 against the same tree (i.e., the ratchet is what's catching everything).

## Pre-flight landscape

- **Existing preflight?** **Yes**, `make verify` at `Makefile:218`. Lists 18 prerequisite targets in order: `lint check-rules check-alantyle check-module-size check-route-size check-layers check-test-classification check-slice-completeness check-migration-boundaries check-docstring-coverage check-complexity check-ruff-ratchet check-vulture-guard check-jscpd check-mutation-sites check-docstring-balance check-import-cycles check-workflows check-issue-specs typecheck check-crap`. Pinned by `tests/test_ci_workflow.py::test_make_verify_covers_locally_runnable_script_gates` (line 2075). Excludes (by design): `mutation`, `security`, `security-deep`, `integration`, `verify-fallback-ready`, `build`, `e2e` (lines 207-214 of the Makefile).
- **`CONTRIBUTING.md` says**: `make verify` after `uv sync --frozen --extra dev` (CONTRIBUTING.md:177-181). Table at lines 183-189 names one row per CI job with the local reproduction command (`lint` → `make verify` / individual targets; `typecheck` → `make typecheck`; `test` → `make test-ci`; `integration` → manual DSN).
- **`docs/codebase/quality-gates.md` says**: Prescribes the **gates** themselves (Regla 19 / 20 / 23 / 24) but does **not** prescribe a preflight command. The "Contributor checklist" at lines 76-82 enumerates invariants (coverage floor, E2E per UI slice, mypy code-tag, etc) without naming `make verify`.
- **`AGENTS.md` says**: Lists skills to load before coding (lines 36-46), 4 operational premises (lines 87-94), and the Quick Navigation table to `docs/codebase/` (lines 100-120). Does **not** prescribe a preflight command by name.

## Proposed canonical preflight (shape)

> **This is a design sketch only; no implementation.** The minimal change is the change. The current `make verify` does the right thing for the gates it covers; the gap is that (a) `make lint` is widely reachable and weaker, and (b) seven of eight ratchets still need a hand-edit on the BASELINE. The shape below fixes both with no new features.

- **Name**: keep `make verify` (already exists, already pinned). Optionally add a top-level alias like `make preflight` that points at the same recipe — discoverable for new contributors.
- **Invocation**: `make verify` (one command; same exit code; same order CI uses).
- **Stages (in order, mirroring `ci.yml` lint job)**:
  1. `lint` (i.e. `ruff check .` against the local `[tool.ruff.lint] select`) — must stay to keep parity with `ci.yml:210`.
  2. `check-ruff-ratchet` — to keep parity with `ci.yml:368`. This is the stage that catches TRY003 etc.; it must come BEFORE any other AST gate so the operator sees the parity issue first.
  3. `check-rules` → `check-module-size` → `check-route-size` → `check-layers` → `check-complexity` → `check-test-classification` → `check-slice-completeness` → `check-migration-boundaries` → `check-docstring-coverage` → `check-vulture-guard` → `check-jscpd` → `check-mutation-sites` → `check-docstring-balance` → `check-import-cycles` → `check-workflows` → `check-alantyle` → `check-issue-specs` → `typecheck` → `check-crap` (i.e. the current `Makefile:218-222` recipe).
  4. The recipe is already pinned by `test_make_verify_covers_locally_runnable_script_gates`. No recipe change needed.
- **Ratchet lock-in mode**: introduce a `--update-baseline` flag on each ratchet script that, when the count is below the BASELINE entry, **rewrites the BASELINE dict in place and exits 0**. Pattern: the file is parsed as text, the line `"{code}": <old>,` is replaced with `"{code}": <new>,`, the file is re-read, and the new measurement is re-run for confirmation. Six scripts need this (`check_ruff_ratchet.py`, `check_module_size.py`, `check_route_size.py`, `check_layers.py`, `check_import_cycles.py`, `check_vulture_guard.py`, `check_docstring_coverage.py`, `check_test_classification.py`); `check_complexity.py` already has `--emit-baseline` and needs the *write-back* variant, not just stdout emission. Each script's `--update-baseline` must be idempotent and must print the diff before writing.
- **Out of scope (NOT including)**:
  - No new gates (the script surface is already 8 + ~10 more; one more invites rot).
  - No removal of `make lint`. It stays as the fast inner loop; `make verify` stays as the pre-push evidence.
  - No bumping of BASELINE values upward. The shrink-only invariant survives; only the lock-in becomes automatic.
  - No mutation/security/e2e/integration gates — those have legitimate exclusion reasons (CI services, Linux-only, browser requirement) documented at `Makefile:208-214` and pinned at `tests/test_ci_workflow.py:2115-2138`.

## Keep-list (do NOT change — looks wrong but is intentional)

- **Item 1 — Local `ruff check .` (select = E/F/W/I/UP/B) deliberately weaker than the ratchet.** Evidence of intentionality: `scripts/check_ruff_ratchet.py:1-26` (module docstring states the extended rulesets are NOT in `[tool.ruff.lint] select` because 802 pre-existing violations would fail `ruff check .` on every PR), `.github/workflows/ci.yml:209-217` (comment: "Issue #200, AGENTS.md rule 20 — removing this step is a blocked change. The AST linter (scripts/check_rules.py) is the authoritative APAP001/APAP003 gate: ruff 0.15+ cannot select Python-defined rules, so `ruff check .` above never runs them"), `pyproject.toml:262-279` (comment: "APAP001 / APAP003 are registered as a ruff plugin in scripts/ruff_plugin/apap_rules.py per tasks.md:T-1B.2, but they are NOT added to select here. Round-2 fix PA-2 outcome ... The authoritative APAP001 + APAP003 lint gate is therefore Detector 1 + Detector 5 in scripts/check_rules.py"), and `tests/test_ruff_ratchet.py:134` (`test_existing_ruff_gate_still_passes` actively pins that local `ruff check .` returns 0 against the real tree). The split is a deliberate design: the ratchet carries the heavy rules, the local gate stays fast.

- **Item 2 — `Makefile:60` `lint` recipe (just `ruff check .`) is the fast inner loop.** Evidence: `Makefile:108-116` (the existing comments label `lint` as the fast inner loop and `verify` as the deterministic pre-push subset). `tests/test_ci_workflow.py:2096` (`assert "ruff check ." in blob`) actively pins that `make verify` includes `ruff check .` in addition to the ratchet. The split is `lint` for editor / inner-loop, `verify` for pre-push. Neither replaces the other.

- **Item 3 — `check_docstring_balance.py` runs in CI without a test file.** Evidence of intentionality: `docs/quality/ci-gate-inventory.md:30` lists `check_docstring_balance` as one of "Reglas AST y estructurales propias" with "Mantener" decision. `tests/test_check_workflows.py` and others share the pattern of pinning via a `test_ci_workflow_lint_job_runs_<gate>` test (`tests/test_check_workflows.py:...`). The intentional gap is: the test runner IS the linter — `ast.parse` already exercises CPython's own parser. The bug it catches (unclosed triple-quoted strings) is CPython-level, so the test-coverage argument is weaker than for a custom AST detector. This is a judgement call. **I am flagging it as a finding (Top-5 #3) because the failure mode is silent and irreversible** — but if the maintainer's posture is "CPython's parser is the test", the gap is intentional.

- **Item 4 — Manual BASELINE edits are required for the 7 non-complexity ratchets.** Evidence: `scripts/check_complexity.py:236-244` (only `check_complexity.py` exposes `--emit-baseline`); all other ratchets print "update BASELINE to lock in the improvement" (cited above). The intentionality argument is "shrink-only ratchets should require a human eyeball each step" — but the 9 calibration-history entries prove the human eyeball is mostly a number edit, not a design decision.

- **Item 5 — `make verify` excludes `mutation`, `security`, `security-deep`, `integration`, `verify-fallback-ready`, `build`, `e2e`.** Evidence: `Makefile:208-214` (explicit comment "Deliberately NOT included because they require CI services, containers, browsers, credentials, or release-only capacity") and `tests/test_ci_workflow.py:2127-2138` (pins the exclusions with explicit reasons). Pinned by `test_make_verify_excludes_the_jobs_a_workstation_cannot_run`.

## Severity scale

- **BLOCKER**: ships unsafe to main (CI catches what local misses). — Applied to Top-5 #1 (extended-ruff ruleset invisibility gap).
- **HIGH**: maintenance trap, recurs every cycle. — Applied to Top-5 #2 (BASELINE lock-in manual) and #3 (no tests for check_docstring_balance).
- **MEDIUM**: missing tests / rot risk. — Applied to Top-5 #4 (`make lint` vs `make verify` divergence) and #5 (ruff version drift risk).
- **LOW**: nice-to-have. — Used for the BASELINE-edit trap on the 1-entry BASELINE of `check_module_size.py`.