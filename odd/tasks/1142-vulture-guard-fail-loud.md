# 1142 — check_vulture_guard: fail loud when vulture did not run

Branch: `fix/1142-vulture-guard-fail-loud` (worktree `apap-app-worktrees/1142-vulture-guard-fail-loud`), off origin/main.
Issue: #1142 (refs #935 item A9, #424). Single PR, `Closes #1142`.

## Problem
With an interpreter lacking `vulture`, `python3 scripts/check_vulture_guard.py` prints `OK (0 confirmed-dead symbol(s), within BASELINE of 5)` plus "NOTE: 5 below BASELINE — update BASELINE to lock in the improvement", exit 0. `python -m vulture` with the module missing exits 1, the same code vulture uses for "dead code found", so the exit code alone cannot tell them apart.

## Tasks
- [x] T1 RED: tests for the five branches (module missing, exit 1 with stderr and no findings, exit 1 with valid findings, exit 0, unexpected exit) using a stubbed subprocess.
- [x] T2 GREEN: fail loud (non-zero exit, message naming the cause and the fix `uv sync --extra dev` / `uv run`); never print the lower-the-BASELINE note when the measurement is unreliable.
- [x] T3 real check: `python3 scripts/check_vulture_guard.py` (system interpreter) must FAIL; `uv run python scripts/check_vulture_guard.py` must still pass with 5.
- [x] T4 full suite + every lint step of ci.yml locally + ruff.
- [x] T5 one commit 3026a66; review/push/PR by the parent (pending).

## Route
Delegated writer. Engram mirror: pending.

## Evidence
- Commit: 3026a66 (scripts/check_vulture_guard.py +45/-4, tests/test_check_vulture_guard.py +98).
- RED: 7 new tests failed (no `_vulture_available`); GREEN: 30 passed in the file.
- Real world: system python3 (no vulture) -> `FAIL check_vulture_guard: vulture is not importable by ...; install the dev extra (uv sync --extra dev) or run through uv run`, exit 1. `uv run` -> OK (5 confirmed-dead, BASELINE 5), exit 0.
- Discovery: vulture 2.16 exits 3 for dead code (1 = invalid input), so accepted codes are {0, 1, 3}; the first draft ({0, 1}) broke the guard on the real tree.
- Full suite: 5189 passed, 19 skipped. All ci.yml lint steps OK. `ruff format --check` on the two files already fails on base (pre-existing), not reformatted.
- Route: delegated writer. Engram mirror: pending.

## Outcome (2026-09-30)
Merged as PR #1143 (merge commit ddf90b6c), issue #1142 closed; friction A9 of the #935 consolidation is resolved. Native review approved without corrections. Correction to the issue text: vulture 2.16 exits 3 when it finds dead code (1 = invalid input), found by running the guard on the real tree. Follow-ups left by the review: protect find_spec, test the real find_spec, tighten the stderr-limit assertion, cover findings plus non-empty stderr.
