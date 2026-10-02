# feat-1005-magic-link-flag

Issue: #1005 — `Settings.auth_enable_magic_link` (default-deny §6), deferred
from #917 by operator decision (2026-09-26). Refs #911.

## Tasks

1. [x] Worktree `apap-app-worktrees/1005-magic-link-flag` + branch
       `feat/1005-magic-link-flag` off origin/main @ c1cfdcc.
2. [ ] Worker (background): flag default False; conditional router registration
       + PUBLIC_PATHS entries; fix stale middleware comment; runbook env var;
       RED→GREEN tests (404 fail-closed off / parity on).
3. [ ] Verification: gates + focused magic-link suite + full suite.
4. [ ] Work-unit commit(s), push, PR with `Closes #1005` (no merge) and a
       prominent deploy-order warning.

## Merge-time operator decision (BLOCKER for merge, not for PR)

Production currently serves magic-link login unconditionally. Merging this PR
WITHOUT setting `APAP_AUTH_ENABLE_MAGIC_LINK=true` in production breaks the
login on next deploy (fail-closed by design). The operator must set the env
var in Coolify BEFORE the next deploy. Do not merge before that coordination.

## Evidence log

- Background worker task: muk9q64p-4-9zv1 (gentle-ai-worker) — COMPLETED.
- Files: config.py +15, middleware.py +29/-11, main.py +24/-4, tests/test_magic_link_flag.py +206 (7 tests), conftest.py +8 (DEVIATION, documented), docs/runbooks/operator-deploy-2026.md +26.
- Gates (worker): ruff/mypy/check_rules/module+route size OK, focused suites 56+60+26 passed, pr_size 332<=400.
- Independent verify task: mukacwev-6-rebk (gentle-ai-verify, background) — pending.
- Verify mukacwev-6-rebk: FIX-NEEDED (docs only) — glued runbook heading (anchor broken), missing env var in coolify yaml + integrations.md. All fixed; alantyle OK; 34 focused tests green.
- Decisión aplicada: yaml declara APAP_AUTH_ENABLE_MAGIC_LINK=true (paridad con prod pre-#1005); Settings default false fail-closed.
- Commits: 9c2cb7d (feat), 41def84 (docs). PR: https://github.com/ardelperal/APAP_WEB/pull/1052 — open, NOT merged, con deploy-order warning.
- Judge A (mukaurcs-7-7aur): REQUEST-CHANGES — 1 MAJOR (REQUIRED_ENV_VARS sin pin), 1 MINOR (login.html form incondicional), 2 SUGGESTION.
- Judge B (mukaurct-8-w5mx): 1 MAJOR (JD-B-001 CI e2e no ejercita flag; confirmado: PR CI 100% verde), 3 MINOR (local_backend latente, gate sin cobertura, pin yaml), 4 SUGGESTION.
- Fix round 1 DONE (worker mukbaxfd-9-p5l8): F1-F8 addressed; gates green; deletion cycle verified; 223 focused tests passed. Commits e574a3a/db66fa3/8ace4c6 pushed to PR #1052.
- size:exception applied: final diff ~888 lines (569+13 tracked + 306 test file) — the worker's "252" was a miscount. Body updated via REST (gh pr edit broken by Projects-classic GraphQL deprecation); label via issues API.
- #941 behavior reproduced live: push evaluated pr-size(888) pre-label → fail; labeled event refreshed direct pr-size → pass; `gh run rerun 36351488068` launched to make `required` re-read live labels.
- Re-judgment scoped en background: judge A mukbtyll-a-gk8n, judge B mukbtylm-b-kybf — pending.

## Re-judgment round (post fix round 1)

- Judge A (mukbtyll-a-gk8n): APPROVE — 12/12 RESOLVED, no new defects (ran 34 focused tests).
- Judge B (mukbtylm-b-kybf): REQUEST-CHANGES — all 8 RESOLVED (independently reproduced JD-B-003/004) BUT 2 CI-blocking regressions introduced by the fix: JD-B-009 login.html UndefinedError in XSS audit (standalone render), JD-B-010 caplog _caller_fields AttributeError with httpx INFO records; +3 SUGGESTION (e2e claim inert, local_backend flag-off atom, absence assertion). GitHub CI test job = failure, confirming.
- Fix round 2 (FINAL): worker mukcegzq-c-6ml4 — F9-F13, bar = full unit scope green (pytest tests/ minus e2e/integration).
- Lesson: judge A ran focused scope, judge B ran CI-equivalent scope; only B caught the regressions. Focused green != CI green.

## Fix round 2 (final) — 2026-09-27

- Worker mukcegzq-c-6ml4: F9-F13 fixed. Repro commands green (xss audit 888 passed; lifespan+caplog 10 passed). FULL CI-equivalent scope: 4953 passed / 0 failures. Gates green. Honest pr-size: 732 (over budget, under size:exception).
- Commits: 4e0feab (fix template+tests), 2670153 (docs claim reword). Pushed; PR body updated via REST.
- Final re-judgment: BOTH APPROVE. Judge A (mukcsuc2-d-tm5n): 5/5 verified with behavioral evidence, merge bar 4953/0. Judge B (mukcsuc4-e-rrx0): APPROVE + WARNING JD-B-014 (file pointer: login-render atoms live in test_auth_flow.py, not test_magic_link_flag.py) — corrected in commit 34f2abb and pushed.
- STATUS: PR #1052 READY FOR USER REVIEW/MERGE. Protocol exhausted (2 fix rounds used). Operator pre-merge action: verify APAP_AUTH_ENABLE_MAGIC_LINK=true in live Coolify env before promoting any build with this gate.
