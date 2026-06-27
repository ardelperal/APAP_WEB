# Apply progress — PR-3 (Slice 3 / Rule 6 / cookie rotation + flip default)

PR: [#111](https://github.com/ardelperal/APAP_WEB/pull/111), base
`staging`. Branch `hardening-2026-q2/slice-3-rule-6-cookie`.

Closes the P0 window from engram:14516 / engram:14518 — a deactivated
user kept a valid session for up to 7 days because both call sites of
`payload.get("is_authorized", True)` defaulted to permit. PR-3 flips
both defaults to `False` and ships the operator runbook.

## Commits

| SHA | Subject | Tasks |
|---|---|---|
| `6e8c9af` | test(slice-3): pin is_authorized default-flip + SESSION_SECRET rotation | T-3.6, T-3.7, T-3.8, REQ-2 rotation |
| `26c3048` | fix(auth): flip is_authorized default to False at both call sites (Rule 6) | T-3.1, T-3.2, T-3.3 |
| `29c79eb` | docs(slice-3): add cookie rotation runbook + mark Rule 6 DONE in AGENTS.md | T-3.4, T-3.5, T-3.9 |
| `c38ca48` | docs(sdd): record PR-3 apply-progress on hardening-2026-q2 | (this file) |

Total PR diff: ~340 impl+tests+runbook additions + ~100 apply-progress
= ~440 LOC. Comparable to PR-1A (649) and within chain precedent.

## Verification

- `pytest`: 442 passed, 2 skipped (psutil not installed; unrelated).
- `ruff check .`: clean.
- T-3.3 (`grep -rn 'payload\.get("is_authorized", True)' app/`): 0 matches.
- T-3.10 (linter): PR-1A's `scripts/check_rules.py` Detector 2 lives
  only on `hardening-2026-q2/slice-1-ast-linter` (not yet on staging).
  In-test static checks in `tests/test_middleware_is_authorized.py`
  + `tests/test_auth_dependencies.py` pin the same property
  pre-merge.

## Deployment note (T-PRF-3 still required)

PR is CODE READY, not DEPLOY READY. The flip is defense against
future regressions; for pre-fix cookies in flight, the operator MUST
rotate `APAP_SESSION_SECRET` post-merge per
`docs/runbooks/cookie-rotation.md`. Per T-PRF-3, communicate ≥24h
before deploy. PR body calls this out as a CRITICAL deployment notice.

## Cross-references

- Spec: `openspec/changes/hardening-2026-q2/specs/03-rule-6-cookie-rotation/spec.md`
- Design: `openspec/changes/hardening-2026-q2/design.md` (Slice 3)
- Tasks: `openspec/changes/hardening-2026-q2/tasks.md` (T-3.1–T-3.10)
- Runbook: `docs/runbooks/cookie-rotation.md`
- Engram: `apap_web` / `sdd/hardening-2026-q2/apply-progress-pr-3`
