# Apply progress — PR-6B (Slice 6 Structured logging — APAP003 lint gate)

PR-6B of `hardening-2026-q2` — Slice 6 (Structured logging + redaction) **PR-B** (the APAP003 lint gate). Branches off `origin/staging` (HEAD `57ad69d`) so PR-6B can land independently once PR-6A.1 + PR-6A.2 have merged.

## Session

| Field | Value |
|-------|-------|
| **Project** | APAP_WEB |
| **Change** | `hardening-2026-q2` |
| **Branch** | `hardening-2026-q2/slice-6b-ruff-rule` |
| **Base** | `origin/staging` (HEAD `57ad69d`) |
| **PR target** | `staging` (NEVER `main`) |
| **Work unit** | Slice 6, PR-6B — APAP003 detector in `scripts/check_rules.py` + plugin visitor wiring + AGENTS.md Rule 9 + 14 new tests (T-6.3, T-6.4 in the brief's numbering; T-6.10 apap003 test; T-6.12 AGENTS.md) |

## Round-2 fix PA-2 outcome — documented

PR-1B's comment in `pyproject.toml` flagged: "Slice 6 (T-6.4) will package the plugin and add APAP003 to `select`." The expectation was that ruff 0.15+ would accept Python-defined rule selectors once the plugin was packaged correctly.

**Verified locally with ruff 0.15.17: it does not.** Adding `"APAP003"` to `[tool.ruff.lint] select` makes ruff fail to parse the config with:

```
TOML parse error at line 135, column 42
select = ["E", "F", "W", "I", "UP", "B", "APAP001", "APAP003"]
                                          ^^^^^^^^^
Unknown rule selector: `APAP001`
```

Ruff 0.15+ ships every rule as a Rust binary and does not expose a Python plugin API for `select` resolution (see https://docs.astral.sh/ruff/configuration/ — no plugin section documented). The "packaging" path that PR-1B alluded to is not available in this ruff version.

**The authoritative APAP001 + APAP003 lint gate is therefore Detector 1 + Detector 5 in `scripts/check_rules.py`**, invoked by `make check-rules`. The plugin module (`scripts/ruff_plugin/apap_rules.py`) stays tested as a plain Python AST visitor (`tests/test_ruff_apap001.py`, `tests/test_apap003.py`) so the two detectors cannot drift — they share the `_is_logger_chain` helper that decides whether a `Call` node is a logger emission chain.

The `pyproject.toml` comment block now documents this outcome for future maintainers.

## What landed (1 commit, 473 LOC)

| SHA | Subject |
|---|---|
| `3db01a4` | `feat(slice-6): APAP003 detector in scripts/check_rules.py + AGENTS.md Rule 9` |

## Files changed

| File | Action | What |
|---|---|---|
| `scripts/check_rules.py` | Modified (+110/-0 lines) | Detector 5 (`apap003_raw_logger_call`) added. Flags `logger.{info,warning,error,debug,critical,exception}(...)` calls in `app/**` except `app/core/logging.py`. The exclusion lives in `DEFAULT_EXCLUDES` so it's honoured by both the CLI invocation and any `--exclude` consumer. Shared `_is_logger_chain` helper mirrors the plugin visitor so the two detectors stay in lock-step. |
| `scripts/ruff_plugin/apap_rules.py` | Modified (+69/-24 lines) | `APAP003Visitor` is now ACTIVE in `check_tree`. The per-file exclusion (`app/core/logging.py` / `app\core\logging.py`) is computed in `__init__` so `visit_Call` short-circuits cleanly. The shared `_is_logger_chain` helper is hoisted to module scope so the AST linter can import it without going through the visitor class. |
| `pyproject.toml` | Modified (+13/-2 lines) | APAP-related comment block updated to document the round-2 fix PA-2 outcome (ruff 0.15+ limitation, AST linter is the authoritative gate, plugin module stays tested for lock-step). No `select` change. |
| `AGENTS.md` | Modified (+2/-0 lines) | New row added to the "Known conflicts" table for the new **Rule 9** ("`log_safe()` is the only allowed logging call in `app/`") with the full DONE summary: spec reference, design reference, audit reference (engram:14518), implementation files, test files, round-2 fix SB-7 known limitation. |
| `tests/test_ruff_apap001.py` | Modified (+15/-13 lines) | `test_apap003_rule_class_registered_but_not_active` renamed and updated to `test_apap003_rule_class_registered_and_active`. Asserts that `check_tree` NOW flags a `logger.warning(...)` sample (the new contract post-PR-6B). |
| `tests/test_apap003.py` | Created (224 LOC, 14 tests) | Exercises both the ruff visitor (`test_apap003_flags_*`) and the AST linter detector (`test_check_rules_*`). Parametrized over the 6 forbidden methods, asserts that `log_safe(...)` and plain `logging.getLogger(...)` retrieval are NOT flagged, and that the violation message guides the developer to `log_safe`. |

## Detector 5 contract

**Rule ID**: `apap003_raw_logger_call`

**Trigger**: any `Call` node in `app/**` (except `app/core/logging.py`) where:
- `node.func` is `ast.Attribute` with `attr` in `{info, warning, error, debug, critical, exception}`, AND
- `node.func.value` matches `_is_logger_chain(...)` (i.e. either a bare `Name` `logger` OR a chained `Call` `logging.getLogger(...)`).

**Closed forbidden-method list**: `info`, `warning`, `error`, `debug`, `critical`, `exception`. Adding a name is a deliberate code-review decision.

**Single file exclusion**: `app/core/logging.py`. The wrapper module is the ONLY legal caller of `logging.getLogger(...)` because it owns `log_safe`.

**Round-2 fix SB-7 (known limitation)**: APAP003 bans the chained `.info/.warning/.error/.debug/.critical/.exception()` call but NOT the bare `logging.getLogger(name)` retrieval. This is intentional — the wrapper module uses `logging.getLogger("app").info(...)` internally, and forbidding the bare retrieval would break the contract. The shared `_is_logger_chain` helper encodes this asymmetry: a bare `Call` to `getLogger` returns `True` (it's a logger chain), but a bare `Call` to `getLogger(...)` WITHOUT the chained `.info()` etc. is NOT flagged because it's just retrieval.

## Verification

| Gate | Status | Notes |
|------|--------|-------|
| `pytest tests/test_ruff_apap001.py tests/test_apap003.py` | Pass | 24/24 tests pass (10 pre-existing + 14 new). |
| `pytest --deselect tests/test_voluntarios_concurrent.py::test_concurrent_deactivate_one_winner -q` | Pass | 725 passed, 3 skipped, 1 deselected. (Note: lower count than PR-6A because PR-6A adds its own test files; this branch is based on `staging` which doesn't have them yet.) |
| `python scripts/check_rules.py app --exclude scripts/check_rules.py --exclude tests/_rule_helpers/fixtures --exclude tests/test_migration_004.py --exclude app/core/logging.py` | Pass | Exit 0; APAP003 detector wired, no current violations on staging. |
| `ruff check .` | Pass (clean except 3 pre-existing I001 in PR-1B test files) | The 3 remaining `I001` errors are in `tests/test_coverage_gate.py`, `tests/test_critical_helpers_have_full_coverage.py`, `tests/test_ruff_apap001.py` — pre-existing from PR-1B, not introduced by this PR. |
| Each commit independent | Pass | Single commit (`3db01a4`) ships the test files + implementation together; diff is GREEN at every push. |

## Operator checklist (post-merge)

1. Confirm PR-6B merged into `staging`.
2. Confirm PR-6A.1 + PR-6A.2 have merged BEFORE PR-6B (so `app/core/logging.py` exists when the detector runs on staging). If PR-6B lands first, the `DEFAULT_EXCLUDES` entry for `app/core/logging.py` is a harmless no-op (the path simply doesn't exist on disk yet).
3. Run `make check-rules` on `staging` HEAD to confirm 0 violations.
4. Run `pytest tests/test_ruff_apap001.py tests/test_apap003.py` to confirm the 24 APAP tests pass on the merged tree.
5. Wire `make check-rules` into `.github/workflows/ci.yml` as a required step (in `ci-cd-foundation` or a follow-up commit) so the APAP001 + APAP003 detectors are CI-enforced.

## Known limitations / follow-ups

1. **APAP rules not in ruff `select` (round-2 fix PA-2 outcome).** Documented above. The authoritative gate is `make check-rules`. If a future ruff version exposes a Python plugin API for `select` resolution, the plugin module is already structured to register and the `_is_logger_chain` helper is already shared — only the `pyproject.toml` `select` line needs to flip.

2. **Detector 5 scope is `app/` only.** Tests, scripts, and any out-of-tree code are not scanned for APAP003. This is intentional — the rule enforces a project-wide convention in the application code; tests/scripts can legitimately use raw `logging` (e.g. the test fixtures use `_Capture` loggers).

3. **PR-6B slight over budget (473 LOC vs 400).** The test suite (`tests/test_apap003.py` at 224 LOC) is the largest single cost and cannot be trimmed without losing the parametrized coverage of all 6 forbidden methods. Splitting further would force artificial seams between the AST linter detector (Detector 5 in `scripts/check_rules.py`) and the plugin visitor (`APAP003Visitor` in `scripts/ruff_plugin/apap_rules.py`); the two share `_is_logger_chain` so they must ship together.

## Persistence

Persisted to Engram:
- `apap_web` / `sdd/hardening-2026-q2/apply-progress-pr-6b` (this file)

## Cross-references

- Spec: `openspec/changes/hardening-2026-q2/specs/06-structured-logging/spec.md` (REQ-2, REQ-5)
- Design: `openspec/changes/hardening-2026-q2/design.md` Slice 6 (§"APAP003 ruff rule contract")
- Tasks: `openspec/changes/hardening-2026-q2/tasks.md` T-6.3, T-6.4, T-6.11, T-6.12
- Predecessors: PR-6A.1 + PR-6A.2 (must land first so `app/core/logging.py` exists for the exclusion to take effect)
- Round-2 fix PA-2: APAP003 select-list wiring outcome (ruff 0.15+ limitation documented in `pyproject.toml` comment block)
- Round-2 fix SB-7: APAP003 allows bare `logging.getLogger` retrieval (known limitation documented in `_is_logger_chain` docstring and AGENTS.md Rule 9 row)
- Follow-up: PR-6 of hardening-2026-q2 will close the slice once PR-6A.1 + PR-6A.2 + PR-6B merge to staging.
