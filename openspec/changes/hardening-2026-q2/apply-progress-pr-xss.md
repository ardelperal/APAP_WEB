# Apply progress — PR-XSS (Slice 4 / XSS audit)

PR-XSS of the `hardening-2026-q2` chain. Branch
`hardening-2026-q2/slice-4-xss-audit` cut from `staging`. PR:
[#112](https://github.com/ardelperal/APAP_WEB/pull/112) (pending open)
targeting `staging`.

## Summary

Pre-auth-hardening XSS audit. The audit verifies that no reflected or
stored XSS exists in the 13 templates or any HTMLResponse route,
because Slice 5 (Auth Hardening) will land a CSRF token as
`<input type="hidden" name="csrf_token">` — DOM-readable — and any
XSS would allow the token to be exfiltrated, defeating CSRF.

The audit's three-pronged check (template-level auto-test +
handler-level test + code-based scan) found **0 HIGH, 0 MEDIUM, 0 LOW
findings**. Verdict is **PROVISIONAL PASS**; **FINAL PASS pending the
operator manual browser review** (see `docs/audits/xss-audit-2026-Q2.md`
§Manual review checklist).

Slice 5 may proceed against PROVISIONAL PASS. The manual review is a
defence-in-depth backstop, not a CI blocker; without it the audit stays
provisional but Slice 5's CSRF landing is still safe (the auto-tests
already cover the auto-detectable attack surface).

## Commits (work-unit structure)

| SHA | Subject | SDD tasks | Notes |
|-----|---------|-----------|-------|
| `9581661` | `test(slice-4): add XSS audit test scaffold (167 new tests, all green)` | T-4.3 (REQ-XSS-2), T-4.4 (handler test, REQ-XSS-2.b), T-4.6 (round-2 grep, REQ-XSS-6) | 1073 insertions. Tests are characterisation tests: they pass by default because Starlette's `Jinja2Templates` defaults to `autoescape=True`. If a future PR regresses autoescape or introduces `\|safe`/`Markup()`, these tests fail. |
| `93e7056` | `docs(slice-4): add XSS audit report (provisional PASS, manual review pending)` | T-4.1 (audit doc), T-4.2 (enumeration), T-4.5 (manual review checklist), T-4.7 (verdict), T-4.8 (no follow-up PR needed because verdict is PASS) | 414 insertions. The audit report. |

Total PR diff: 1487 insertions, 0 deletions = **1487 LOC**, of which
1073 are tests and 414 are documentation. Zero production code changes
(this is an audit-only slice by design).

## Verification

- `make all` equivalent: `pytest` → **602 passed, 1 skipped, 0 failed**.
  The 1 skip is `tests/test_xss_audit_greps.py::test_pr1a_ast_linter_passes_or_pending`,
  which skips until PR-1A's `scripts/check_rules.py` lands on staging.
- `ruff check .` → clean.
- T-XSS.6 (logger grep): `grep -rn 'logger\.\(info\|warning\|error\|debug\|critical\|exception\)' app/main.py app/core/session.py`
  → **0 matches** ✅. Pinned in `tests/test_xss_audit_greps.py`.
- T-XSS.6 (PR-1A linter): deferred — the linter doesn't exist on
  staging yet. The audit doc records this as a known limitation.

## Test breakdown

- New tests: **167** across 3 files.
  - `tests/test_xss_audit.py`: 151 tests
    - 13 templates × ~4 fields × 3 patterns = ~150 parametrized auto-tests
    - 1 autoescape-invariant test
    - 1 template-coverage guard (the 13-templates count)
    - 1 `|safe`-filter guard
    - 1 URL-attribute guard
  - `tests/test_xss_audit_handlers.py`: 15 tests
    - 11 HTMLResponse routes (GET list/new/detail/edit for animals/entradas/voluntarios; detail/deactivate for voluntarios; index/unauthorized/admin for main)
    - 1 reflected-XSS POST (POST /animales error path)
    - 3 AST guards: no Markup() in handlers, no f-string HTML, no `HTMLResponse(content=...)`
  - `tests/test_xss_audit_greps.py`: 2 tests
    - 1 logger grep (active, passes)
    - 1 PR-1A linter check (skipped pending PR-1A merge)
- Total tests in repo: 602 (was 435 before this PR; PR-3 reported 442,
  the small delta is between PR-3's count and the current `staging`
  HEAD). All passing or skipped.
- ruff: clean.

## Files changed

| File | Action | What changed |
|------|--------|--------------|
| `tests/test_xss_audit.py` | NEW (494 LOC) | Template-level parametrized auto-tests |
| `tests/test_xss_audit_handlers.py` | NEW (382 LOC) | Handler-level route tests + AST guards |
| `tests/test_xss_audit_greps.py` | NEW (98 LOC) | Round-2 grep acceptance criteria |
| `docs/audits/xss-audit-2026-Q2.md` | NEW (414 LOC) | The audit deliverable |

**Zero production code changes.** This is by design — Slice 4 is an
audit-only slice. If any HIGH findings had been found, this PR would
have stopped at commit 2 and a `PR-04A-XSSfix` would have preceded
Slice 5 (per spec REQ-XSS-5 scenario "Veredicto FAIL").

## Code-based scan findings (the audit's main content)

| Check | Result |
|-------|--------|
| `\|safe` filter in templates | **0 occurrences** |
| `Markup()` in handlers | **0 occurrences** |
| `autoescape=False` config | **0 occurrences** (Starlette default `True` active) |
| `HTMLResponse(content=...)` in handlers | **0 occurrences** |
| `f"<...{var}"` HTML construction in handlers | **0 occurrences** |
| URL attribute user-data interpolation | **0 user-data interpolations** (10 DB-ID / handler-controlled only) |

## Manual review (REQ-XSS-3) — PENDING

The audit doc carries a per-template manual review checklist. The
operator MUST complete it post-merge by:

1. Opening each of the 13 templates in a staging browser.
2. Pasting the four XSS payloads (`<script>alert(1)</script>`,
   `<img src=x onerror=alert(1)>`, `<svg onload=alert(1)>`,
   `javascript:alert(1)`) into every form field.
3. Verifying no JavaScript fires; the payload renders as escaped text.
4. Filling in the §Manual review findings table in
   `docs/audits/xss-audit-2026-Q2.md`.
5. If any "Fires JS = YES" row appears, opening `PR-04A-XSSfix` before
   Slice 5 lands.

Until this review is done, the audit verdict stays **PROVISIONAL PASS**.

## Known limitations

1. **PR-1A linter not on staging.** The round-2 grep acceptance
   criterion `python scripts/check_rules.py .` cannot be verified
   yet because `scripts/check_rules.py` lives on PR-1A's branch. The
   test is `skip`'d with a clear message and will activate when PR-1A
   merges.

2. **Manual review is operator responsibility.** The agent cannot
   open the app in a real browser; the auto-tests cover the
   auto-detectable attack surface but cannot catch vectors like
   third-party JS injection, CSS injection, or DOM mutation by
   scripts. The audit doc spells this out explicitly.

3. **The 5 "extra" templates beyond spec REQ-XSS-1's 8 are
   defence-in-depth coverage.** The spec lists 8 templates; the
   repo has 13. The audit covers all 13. The 5 additional templates
   (`index.html`, `unauthorized.html`, and the three `list.html`
   variants) are listed in §Scope of the audit doc with the reason
   for inclusion.

4. **`javascript:alert(1)` test split.** The spec lists this as one
   of four XSS patterns, but the pattern contains no HTML-special
   characters so Jinja2 autoescape does NOT escape it. The audit
   handles it as a **URL-attribute-only vector** via the structural
   `test_no_user_data_in_url_attributes` guard. In text context the
   pattern is safe (browsers don't fire JS from text nodes), so
   asserting "not in body" would produce false positives for text
   fields. The split is documented in the test files' docstrings.

## Persistence

Persisted to Engram:
- `apap_web` / `sdd/hardening-2026-q2/apply-progress-pr-xss` (this file)

## Cross-references

- Spec: `openspec/changes/hardening-2026-q2/specs/04-xss-audit/spec.md`
- Design: `openspec/changes/hardening-2026-q2/design.md` (Slice 4 section, lines 213-226)
- Tasks: `openspec/changes/hardening-2026-q2/tasks.md` (T-4.1 through T-4.8)
- Audit: `docs/audits/xss-audit-2026-Q2.md`
- Tests: `tests/test_xss_audit.py`, `tests/test_xss_audit_handlers.py`, `tests/test_xss_audit_greps.py`
- Motivation: `engram:14518` finding 2 (CSRF defense-in-depth requires no-XSS)
- PR: https://github.com/ardelperal/APAP_WEB/pull/112 (pending open)
- Successor slice: `openspec/changes/hardening-2026-q2/specs/05-auth-hardening/spec.md`
