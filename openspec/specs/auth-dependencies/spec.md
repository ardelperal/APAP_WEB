# Spec: `auth-dependencies` slice

**Change**: `auth-dependencies` · **Project**: `apap_web` · **Phase**: spec · **Date**: 2026-08-05  
**Source**: `proposal.md` + `explore.md` + locked decisions (`sdd/auth-dependencies/decisions`, engram `24064`).

## 1. Requirements

### R01 — Shim re-exports all 9 public symbols
`app/core/auth_dependencies.py` must re-export (via `from app.core.di.auth_dependencies_di import *`) exactly: `AuthenticatedUser`, `is_authenticated_user`, `get_local_backend_client_dep`, `get_current_user_optional`, `return_early_if_response`, `require_authorized_user`, `require_writer_user`, `require_developer_user`, `require_developer_user_redirect`. no re-export from `app.core.di.__init__`.
**Scenario** — *every consumer resolves* — given 21 import sites import ≥1 of the 9 names when the slice lands then `from app.core.auth_dependencies import <name>` resolves and both existing test files pass unchanged.

### R02 — Implementation in `app/core/di/auth_dependencies_di.py`
New module must contain all 9 functions verbatim from current `auth_dependencies.py` plus the imports in proposal §4.
**Scenario** — *module exports the 9 names* — given the file exists when imported then `dir(...)` includes every name in the 9-symbol set.

### R03 — §32.P4 fix (Variant A)
`require_authorized_user` must wrap `get_user_by_email(client, email)` in `try/except BackendError`; on `BackendError` emit `log_safe("auth.denied", reason="db_unreachable", user_id=...)` and return `RedirectResponse("/unauthorized", 302)`.
**Scenario** — *BackendError → 302, no 500* — given a valid cookie + stale cache when `get_user_by_email` raises `BackendError` then dep returns `/unauthorized` 302 and emits `log_safe("auth.denied", reason="db_unreachable")` and no exception propagates.

### R04 — Pin test denies transport-shaped leaks
`tests/test_auth_dependencies_slice.py` must assert: no `execute_sql`/raw SQL; `LocalBackendClient` only as parameter type; auth-cache via `get_cached_auth`/`set_cached_auth` only.
**Scenario** — *pin test fails on leak* — given the pin test is wired in when `client.execute_sql(...)` or `LocalBackendClient(...)` is added inside `require_authorized_user` then the test fails naming the symbol.

### R05 — Audit doc refreshed
`docs/audits/auth-dependencies-audit-2026-Q2.md` must gain an addendum covering the migration, shim contract, 9-symbol list, and §32.P4 fix; Verdict updated.
**Scenario** — *doc covers slice + §32.P4* — given the doc structure when the slice lands then a dated addendum is present and Verdict reflects the §32.P4 fix.

### R06 — CI green (six jobs) + rule compliance
PR merge requires `ruff check .`, `scripts/check_rules.py`, `python -m mypy`, `pytest -W error::DeprecationWarning`, `python -m build` all green in `ci.yml` jobs lint/typecheck/test/security/integration/build. Detectors 5 (`raw_logger_in_app`, §9), 6 (`print_in_app`, §9), 11 (`unjustified_lazy_import`, §26), 12 (cross-module imports, §27) must stay green.
**Scenario** — *CI run is green* — given the slice on a branch when `ci.yml` runs on head then the six required jobs are green and merge body cites the run URL.

### R07 — Module size budget (§21)
`auth_dependencies_di.py` ≤ 700 lines; shim ≤ 50 lines. `scripts/check_module_size.py` must not receive a new BASELINE entry.
**Scenario** — *ratchet stays green* — given the slice lands when the ratchet runs then no new BASELINE entry and both modules are under budget.

### R08 — Default-deny + log_safe contract (§6 + §9)
`require_authorized_user` reads `Settings.auth_cache_ttl_seconds` — a missing/zero value must mean "revalidate every request" (cache miss → DB query), never "skip → allow". Every event must go through `log_safe`; no `logger.*`, no `print`. Denial `reason` enum is closed: `no_session | cookie_no_flag | no_email | db_reval_miss | writer_required | developer_required | db_unreachable`. No PII in log fields.
**Scenario** — *missing TTL → revalidate; log_safe only* — given `auth_cache_ttl_seconds` is zero or missing when the dep runs then it revalidates via DB (cache miss path) and on any denial emits `log_safe("auth.denied", reason=<enum>, user_id=<id>)` and no PII appears in fields.

### R09 — Signature stability
The 9 public symbols must keep byte-identical signatures (parameters, defaults, return annotation).
**Scenario** — *existing tests pass without edits* — given both test files import from `app.core.auth_dependencies` when `pytest -W error::DeprecationWarning` runs then both pass and no source line changes.

### R10 — `main.py` / `routes_registry.py` untouched
The slice must not modify `app/main.py` or `app/routes_registry.py` unless forced; if so, PR description must flag the reason.
**Scenario** — *diff bounded to four paths* — given `git diff main...HEAD` when reviewed then only the four paths in proposal §8 appear.

## 2. Non-functional requirements
Performance ≤ 5 ms added per request (re-export + one `try/except`). Python 3.11+; FastAPI pinned; no new runtime dep. Coverage: global floor §19 (80%); §11 unchanged; per-layer report for `app/core/di/` per §32.P8. Type safety: mypy §24 zero errors; `# type: ignore` requires a specific code.

## 3. Out of scope
The 11 module slices · changes to `app/main.py` or `app/routes_registry.py` (flag only if forced) · resolving #226 cycle (document with `lazy-import:` per §26) · `app/core/auth_cache.py` (touch only if needed) · ratchet files · `app/core/ports/auth_session_port.py` Protocol (rejected in explore.md §4).

## 4. Trace
| Req | Proposal § | AGENTS.md |
|---|---|---|
| R01, R02 | §3, §4, §7 DoD | §1, §33 |
| R03 | §4, §6 | §32.P4 |
| R04 | §6 §32.P3 | §33.4 |
| R05 | §3, §8 | §12 |
| R06 | §7, §15.1 | §15.1, §19, §20, §24, §9, §26, §27 |
| R07 | §7 DoD | §21 |
| R08 | §6 | §6, §9 |
| R09 | §5 R3 | §31, §32.P4 |
| R10 | §3, §7 | §15, §17 |

## 5. Acceptance criteria
- All 9 re-exports verified present in the shim (assertable).
- Pin test denies transport-shaped leaks; runs in CI; fails on regression.
- `tests/test_auth_dependencies.py` + `tests/test_auth_session_is_authorized.py` pass sin modification.
- CI green: lint, typecheck, test, security, integration, build (per §15.1); module size `auth_dependencies_di.py` ≤ 700, shim ≤ 50, no new BASELINE.
- Audit doc covers scope/methodology/findings/verdict per §12.
- §32.P4 fix demonstrable: unit test forces `BackendError` and asserts 302 + `log_safe("auth.denied", reason="db_unreachable")`.