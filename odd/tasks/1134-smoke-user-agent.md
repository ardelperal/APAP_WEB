# 1134 — production smoke: User-Agent (Cloudflare 403), redirect host, retries, runbook SHA

Branch: `fix/1134-smoke-user-agent` (worktree `apap-app-worktrees/1134-smoke-user-agent`), off origin/main 4ceb750.
Issue: #1134 (defect of #1131/PR #1133; refs #935, #1119). Single PR, `Closes #1134`.

## Objective
Make scripts/production_smoke.py work against the real production host and harden the checks the native review flagged.

## Evidence
Real run 2026-09-29: HTTP 403 on all three checks because Cloudflare rejects the default `Python-urllib/3.x` User-Agent; `curl/8.5.0` and `apap-production-smoke/1 (+https://github.com/ardelperal/APAP_WEB)` get 200.

## Tasks
- [x] T1 RED/GREEN: explicit User-Agent on every request; test captures request headers on the stub server and fails on the urllib default.
- [x] T2 RED/GREEN: redirect to /login must be relative or same host as the base URL.
- [x] T3 RED/GREEN: bounded retries for the public and protected checks (same policy as the revision check).
- [x] T4 runbook: read the deployed revision from /healthz, not origin/main.
- [x] T5 checks: REAL run against production (must exit 0), full suite, ruff, check_workflows, every lint step of ci.yml locally (incl. check_alantyle and jscpd).
- [ ] T6 one work-unit commit; native review, push and PR by the parent.

## Route
Delegated writer. Engram mirror: pending.

## Evidence of completion
- Work-unit commit 5cf0566 (fix(ci)); numstat 75/37 script, 107/8 tests, 5/1 runbook.
- RED: 8 new tests failed before the change; GREEN: 42 passed in tests/test_production_smoke.py.
- Real run vs https://apap.romancaba.com/healthz revision 2d5024a1dd87b33c5b7f33016d66fd3c1abdf4e6: 3 checks ok, exit=0.
- Full suite: 5149 passed, 19 skipped; ruff check/format clean; all ci.yml lint scripts exit 0 (check_required_jobs needs CI_NEEDS_JSON, CI-only).
- T6: commit done; review, push and PR pending with the parent.
