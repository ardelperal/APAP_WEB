# Audit checklist — 2026-07-25

> **Mirror of the tracking issue**: https://github.com/ardelperal/APAP_WEB/issues/294
>
> The canonical source of truth is the GitHub issue. This file is a docs-only
> in-repo mirror kept in sync with the issue body. When the issue changes,
> re-run the same flip + "Closed findings" append that produced this revision.

Tracking issue for the full-codebase audit run on 2026-07-25 against `main` at `abcaa89`.

## How to work this batch

Every issue in this audit carries the label **`audit-2026-07-25`**. To pick up the work:

```
gh issue list --label audit-2026-07-25 --state open
```

Each issue is self-contained: it names the exact file and line, states the failure scenario, lists acceptance criteria, names the AGENTS.md rules that apply, and gives the commands to validate. An agent should not need this epic to execute any single one of them.

Follow `docs/proceso.md` and AGENTS.md §15 (pre-MVP single-branch policy) for the branch/PR/merge flow. Several of these touch auth, secrets or CSRF, which makes `judgment-day` mandatory per §17.2 — each issue says so where it applies.

## Baseline measured at audit time

| Gate | Result |
|---|---|
| `ruff check .` | pass |
| `python -m mypy` | pass — 0 errors, 92 files |
| `python scripts/check_rules.py .` | pass — 12 detectors |
| `check_module_size.py` / `check_route_size.py` | pass |
| `pytest --cov=app` | 2516 passed, 3 failed, 2 skipped — **89.18%** coverage |
| `CRITICAL_HELPERS` gate | pass — 21 helpers at 100% |

The 3 local failures: 2 are the environment-dependent `test_coverage_gate.py` cases (#292), 1 is the by-design hard-fail of the TOCTOU concurrency test (#282).

## What the audit found healthy

Worth stating, because it is the reason the findings below are narrow rather than structural:

- Layer boundaries hold — zero `execute_sql` calls in routes.
- Zero SQL string interpolation anywhere in `app/`; everything is parameterised.
- Zero `| safe` in templates; Jinja autoescape intact.
- Authorisation is re-validated against the database on every request, not trusted from the cookie.
- Path traversal is closed on storage keys and bucket names before any HTTP call.
- 12 project-specific AST detectors plus two shrink-only size ratchets, all wired into CI.
- Multi-stage Dockerfile, non-root runtime, no build tooling in the final image.

## Closed findings

These audit findings have landed in `main` and are now closed. Their boxes are flipped to `[x]` in the checklist below; the underlying PRs are listed here for traceability.

- #275 — fail-fast on missing or placeholder secrets at startup — PR #307
- #276 — HTTP security headers middleware (CSP, X-Frame-Options, nosniff, Referrer-Policy, HSTS) — PR #311
- #286 — rate limiting on the OAuth flow and write routes — PR #306
- #277 — `POST /admin/users` returns 500 on duplicate email — PR #308
- #278 — email never normalised: ghost users and missed revocations — PR #308
- #279 — permanent lockout when the last active developer is deactivated — PR #309
- #280 — `invalidate_all()` reopens the write-after-invalidate race — PR #310
- #281 — the `deploy` job never runs (merge-commit guard vs. PR-only policy) — PR #302
- #283 — `log_safe` can raise `KeyError` on reserved `LogRecord` field names — PR #301 (merged together with #284)
- #284 — `JsonFormatter` emits ~15 internal fields per log line — PR #301
- #285 — `animal_foto` buffers whole photos, no cache headers, stale docstring — PR #304
- #287 — `RedisAuthCache` is dead code reachable by configuration — PR #298
- #289 — `domain.py` and `acogidas/service.py` are 1–2 lines from the size budget — PR #303
- #290 — rule 22 (query-builder seam) has zero adoption and no gate — PR #305
- #291 — AGENTS.md has two rules numbered 29 — PR #298
- #293 — encode the detected anti-patterns as an AGENTS.md rule — PR #295

## Findings

### Security and startup

- [x] #275 — fail-fast on missing or placeholder secrets at startup — **highest impact of the audit**
- [x] #276 — HTTP security headers middleware (CSP, X-Frame-Options, nosniff, Referrer-Policy, HSTS)
- [x] #286 — rate limiting on the OAuth flow and write routes

### Auth correctness

- [x] #277 — `POST /admin/users` returns 500 on duplicate email
- [x] #278 — email never normalised: ghost users and missed revocations
- [x] #279 — permanent lockout when the last active developer is deactivated
- [x] #280 — `invalidate_all()` reopens the write-after-invalidate race

### CI and test integrity

- [x] #281 — the `deploy` job never runs (merge-commit guard vs. PR-only policy)
- [ ] #282 — the TOCTOU concurrency test runs nowhere
- [ ] #292 — `test_coverage_gate.py` subprocess depends on ambient `sys.path`

### Robustness

- [x] #283 — `log_safe` can raise `KeyError` on reserved `LogRecord` field names
- [x] #284 — `JsonFormatter` emits ~15 internal fields per log line
- [x] #285 — `animal_foto` buffers whole photos, no cache headers, stale docstring

### Technical debt

- [x] #287 — `RedisAuthCache` is dead code reachable by configuration
- [ ] #288 — route-layer coverage gap hidden by the global average
- [x] #289 — `domain.py` and `acogidas/service.py` are 1–2 lines from the size budget
- [x] #290 — rule 22 (query-builder seam) has zero adoption and no gate
- [x] #291 — AGENTS.md has two rules numbered 29

### Prevention

- [x] #293 — encode the detected anti-patterns as an AGENTS.md rule

## Suggested order

1. **#275** first — it is the only finding that turns a config slip into full auth bypass.
2. **#277 + #278** together — same file, same flow, small combined diff.
3. **#279**, then **#276**.
4. **#281** and **#282** before anything else lands, so the CI gates that validate the rest are actually running.
5. **#293** early rather than late: it is the rule that stops the next batch of these from appearing.

## Pre-existing issues in the same territory

Not opened by this audit, but they belong to the same clusters and should be scheduled alongside:

- #205 — extract query builders (pairs with #290 and the `acogidas` half of #289)
- #206, #223 — E2E suite not running in CI (pairs with #288)
- #217, #218, #219 — open `type:bug` in `migration/`; **#218 (swallowed `conn.commit()` failure) is a silent durability gap and deserves priority**
- #198 — review-authority inventory corrupted
