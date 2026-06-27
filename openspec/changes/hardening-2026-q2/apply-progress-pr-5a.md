# Apply progress — PR-5A (Slice 5 Auth hardening — audit doc)

PR-5A of `hardening-2026-q2` — Slice 5 (Auth hardening) **PR-A
(audit-only)**. Branch `hardening-2026-q2/slice-5a-audit-doc` cut
from `staging` (bd8a98e). PR: [#116](https://github.com/ardelperal/APAP_WEB/pull/116)
(OPEN) targeting `staging`.

## Summary

Audit-only slice that ships the formal audit of
`app/core/auth_dependencies.py`, closes the Rule 7 follow-up row in
`AGENTS.md`, and pins Rule 7 compliance with a characterization
regression test. PR-5B (the next slice, in this same chain)
implements the CSRF middleware that addresses the HIGH finding
identified by this audit.

This split follows the design §Slice 5 risk callout: the CSRF + tests
slice is ~600 LOC and would breach the 400-line review budget; PR-A
ships the ~120 LOC audit-only deliverable that the apply phase
contractually owes the reviewers.

## Commits (work-unit structure)

| SHA | Subject | SDD tasks | Notes |
|-----|---------|-----------|-------|
| `4059e2c` | `docs(slice-5a): auth_dependencies audit + Rule 7 follow-up closure` | T-5A.1, T-5A.2, T-5A.3, T-5A.4, T-5A.5, T-5A.6 | Single combined commit: audit doc + AGENTS.md update + characterization test. The test pins current good behaviour (green from day one; characterization, not TDD red->green). Test must precede the AGENTS.md update semantically because the "DONE" claim depends on the test asserting the property. |

Total PR diff: +306 insertions, -1 deletion across 3 files (audit doc
184 LOC + characterization test 121 LOC + AGENTS.md 1 row update).
**Under the 400-line review budget.**

## Verification

- `pytest tests/test_rule_7_compliance.py` → **6 passed**
- `pytest` (full suite) → **674 passed, 3 skipped, 1 pre-existing
  PG-only E2E failure**. The failure
  (`tests/test_voluntarios_concurrent.py::test_concurrent_deactivate_one_winner`)
  is unrelated to this PR — it requires PostgreSQL row-level locking
  and fails by design when running against SQLite/mocks per round-2
  fix REG-S-3 (HARD FAIL not skip). The same test fails on staging
  HEAD without this PR's changes.
- `ruff check tests/test_rule_7_compliance.py docs/audits/` → **clean**
- `python scripts/check_rules.py app/` → **0 violations** (Rule 1/6/7
  linter from PR-1A is operational; Rule 7 detector passes against
  current code)
- `grep -rn "HTTPException(status_code=302" app/` → **0 matches**
  (Rule 7 confirmed compliant)
- Pre-slice form audit (T-5A.6): 8 distinct `<form method="post">`
  tags in `app/templates/`, mapping to 10 POST handlers (animals/form.html
  and entradas/form.html are reused for create + update). None carry
  `csrf_token` today → PR-5B's `test_all_post_forms_have_csrf_input`
  will fail on 10/10 until PR-5B lands. Baseline captured in audit
  doc §"Pre-slice form audit".

## Files changed

| File | Action | What changed |
|------|--------|--------------|
| `docs/audits/auth-dependencies-audit-2026-Q2.md` | NEW (184 LOC) | The audit deliverable. Scope, methodology, 4 public functions catalogued, 7 findings classified (1 HIGH / 3 MEDIUM / 3 LOW), pre-slice form audit, resolution log, verdict PASS |
| `AGENTS.md` | MODIFIED | Rule 7 row at line 308 — original outdated row replaced with strikethrough + DONE note + reference to the audit doc and the new regression test |
| `tests/test_rule_7_compliance.py` | NEW (121 LOC) | Six parametrized `inspect.getsource(require_authorized_user)` checks. Pins Rule 7 compliance so future PRs that revert to `HTTPException(302)` fail CI |

**Zero production code changes.** By design — Slice 5 PR-A is the
audit-only deliverable that the apply phase owes the reviewers; PR-B
owns the CSRF middleware implementation.

## Findings summary (full table in the audit doc)

| # | Severity | Title | Status |
|---|---|---|---|
| F-1 | HIGH | No CSRF defense on POST forms | **TRACKED** — PR-5B (T-5B.1..27) |
| F-2 | MEDIUM | `return_early_if_response` parameter typed `object` | FOLLOW-UP #1 — post PR-5B |
| F-3 | MEDIUM | Triple duplication of "read session cookie + decode" | FOLLOW-UP #2 — recommend co-ship with PR-5B |
| F-4 | MEDIUM | Missing `Iterator[InsForgeClient]` annotation | FOLLOW-UP #1 — same as F-2 |
| F-5 | LOW | `_redirect()` consolidation deferred | DOCUMENTED (spec §"Out of scope") |
| F-6 | LOW | Two `RedirectResponse` calls in `require_authorized_user` | NO ACTION |
| F-7 | LOW | Stale test import in `test_auth_session_is_authorized.py:52` | DOCUMENTED |

## Known limitations

1. **Characterization test not a TDD red->green signal.** PR-5A ships
   no production change; the test passes immediately because current
   code is already correct. The "RED signal" would be an artificial
   one (revert the redirect, watch the test fail, then revert the
   revert) and was skipped for audit-only hygiene. The static-source
   test catches future regressions by design.

2. **Manual browser review (audit doc §"Manual review") deferred.**
   The audit doc includes a §"Manual review" checklist for the
   operator (open each template in a browser, paste XSS payloads,
   verify no JS fires). This is a defense-in-depth backstop, not a CI
   gate, and is the operator's responsibility post-merge.

3. **Pre-slice form audit baseline is grep-only.** The audit doc
   enumerates the 8 form tags / 10 handlers via `grep`; PR-5B will
   create the parametrized test that runtime-renders each form via
   `TestClient` and asserts the hidden input. The grep is the static
   baseline; the test is the dynamic gate.

4. **PR-1B (ruff plugin) not yet on staging.** The dynamic APAP003
   detector (banning raw `logger.*`) from PR-1B will activate when
   PR-1B merges; PR-5A does not depend on it but PR-5B's logging
   placeholder will benefit from the gate.

## Persistence

Persisted to Engram:
- `apap_web` / `sdd/hardening-2026-q2/apply-progress-pr-5a` (this file)

## Cross-references

- Spec: `openspec/changes/hardening-2026-q2/specs/05-auth-hardening/spec.md` (REQ-AH-1..4)
- Design: `openspec/changes/hardening-2026-q2/design.md` §Slice 5
- Tasks: `openspec/changes/hardening-2026-q2/tasks.md` T-5A.1..6
- Audit: `docs/audits/auth-dependencies-audit-2026-Q2.md`
- Tests: `tests/test_rule_7_compliance.py`
- Motivation: engram:14518 (security audit), engram:14516 (rule-compliance audit)
- PR: https://github.com/ardelperal/APAP_WEB/pull/116 (OPEN, 2026-06-27, targets `staging`)
- Predecessor: PR-3 (#111 Rule 6, merged), PR-XSS (#112 XSS audit, OPEN)
- Successor slice: PR-5B (CSRF middleware, T-5B.1..27)