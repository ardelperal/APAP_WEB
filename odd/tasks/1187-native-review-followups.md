# 1187 — Native-review followups issue + preflight hardening slice

Branch: pending (parent owns git). Issue: #1187 (`type:chore`, `status:approved`), refs épica #935 (B4/B11 in comments), #1145, #1143, #1131-#1133, #1141, #1121, #1119.

## Problem
The handoff (§4.2) required a single followups issue collecting the non-blocking findings of the native reviews; it did not exist. Its highest-value item (preflight) had two real defects: a lint job extracting zero steps printed the false green `PASSED (0/0 steps)`, and steps with `working-directory`/`env`/`shell`/`if` were silently ignored.

## Tasks
- [x] T1 Issue #1187 created with the canonical 6 sections and the full checklist (preflight ×5, vulture ×4, production_smoke/deploy.yml ×4, size-exception-reason ×3).
- [x] T2 RED: 8 new tests in `tests/test_preflight.py` (zero run steps fails loud ×2, `shell` warns, `if` warns and still runs, `working-directory` honored, `env` honored, `${{ }}` in env refused, `${{ }}` in working-directory refused, real ci.yml produces no warnings).
- [x] T3 GREEN: `scripts/preflight.py` — `Step` dataclass; 0-steps raises `WorkflowError` («0 steps extracted … parser drift», exit 2); `working-directory` + `env` honored; `shell`/`if`/`continue-on-error`/unknown attributes warned with reason; `${{ }}` in env/working-directory refused like in `run:`.
- [x] T4 Real check: `uv run python scripts/preflight.py` — all 20 real steps pass, no new warnings on the shipped ci.yml.
- [x] T5 Full validation: pytest, mypy, ruff, vulture guard (see Evidence).
- [ ] T6 Commit/push/PR by the parent (`Refs #1187`, partial — remaining checklist items named in the PR body).

## Decision documented in the script
Honor `working-directory` and `env` (cheap, faithful to the runner); warn on `shell` and `if` (the `bash -e` runner model cannot reproduce them), also on `continue-on-error` (flips the pass/fail contract) and on any other unknown attribute so the silent-ignore defect class stays closed. `id` and `timeout-minutes` are known-silent (cosmetic / followup listed in #1187).

## Evidence
- RED: 8 failed, 13 passed before implementation.
- GREEN: 21 passed, 2 skipped (opt-in smokes) in `tests/test_preflight.py`.
- Real world: `uv run python scripts/preflight.py` → `preflight: PASSED (20/20 steps)`, exit 0; zero WARNING/honoring lines on the real ci.yml.

## Route
Delegated writer (pi implementation subagent). Parent owns git, review and PR.
