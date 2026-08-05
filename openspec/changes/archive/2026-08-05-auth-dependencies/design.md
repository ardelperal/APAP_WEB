# Design: `auth-dependencies` slice — shim + di + §32.P4 Variant A + pin test

**Change**: `auth-dependencies` · **Project**: `apap_web` · **Phase**: design · **Date**: 2026-08-05  
**Source**: spec.md (R01–R10) + proposal.md + locked decisions (`sdd/auth-dependencies/decisions`, engram `24064`).  
**Repo root**: `C:\00repos\codigo\APAP_WEB\00_main` (worktree `00_main`).  
**Pre-MVP gate**: §15.1, §15.6 standing merge authorization active; diff ≤ 400 lines.

---

## 1. Architecture overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│ CONSUMERS (19 files; imports unchanged via shim)                        │
│  app/main.py · app/core/{admin_handlers,auth_flow,rbac}.py              │
│  app/modules/*/routes.py ×13 · tests/test_auth_*.py ×2                   │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │ from app.core.auth_dependencies import <X>
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ app/core/auth_dependencies.py  ← SHIM (~20 lines, ≤50)                  │
│   from app.core.di.auth_dependencies_di import *                        │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │ import *
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ app/core/di/auth_dependencies_di.py  ← IMPLEMENTATION (~430 lines, ≤700)│
│  AuthenticatedUser · is_authenticated_user · get_insforge_client_dep ·  │
│  get_current_user_optional · return_early_if_response ·                  │
│  require_authorized_user  ← §32.P4 Variant A fix lives here             │
│  require_writer_user · require_developer_user ·                         │
│  require_developer_user_redirect · _resolve_developer_user              │
└──────────┬───────────────────────────┬──────────────────────────────────┘
           │                           │
           ▼                           ▼
┌──────────────────────┐  ┌──────────────────────────────────────────────┐
│ app/core/auth.py     │  │ app/core/insforge.py  (InsForgeClient type)   │
│ get_user_by_email    │  │ app/core/data_access.py (InsForgeError)       │
│ (raises InsForgeError│  │ app/core/auth_cache.py (get_cached_auth,      │
│  on transport fail)  │  │   set_cached_auth)                            │
└──────────────────────┘  │ app/core/config.py (Settings)                 │
                          │ app/core/logging.py (log_safe)                │
                          │ app/core/roles.py (Rol)                       │
                          │ app/core/session.py (read_session_payload)    │
                          └──────────────────────────────────────────────┘
           ▲
           │
┌──────────┴───────────────────────────────────────────────────────────────┐
│ TESTS / DOCS                                                            │
│  tests/test_auth_dependencies.py  (existing — untouched)                │
│  tests/test_auth_session_is_authorized.py  (existing — untouched)        │
│  tests/test_auth_dependencies_slice.py  ← NEW pin test (§33.4 / §32.P3) │
│  docs/audits/auth-dependencies-audit-2026-Q2.md  ← addendum refresh     │
└─────────────────────────────────────────────────────────────────────────┘
```

## 2. Module layout

| Path | Action | Content (exact) |
|---|---|---|
| `app/core/di/auth_dependencies_di.py` | **Create** | 9 public symbols + 1 private helper, lifted verbatim from current `auth_dependencies.py` lines 50–419; new `try/except InsForgeError` block added inside `require_authorized_user` (R02, R03). |
| `app/core/auth_dependencies.py` | **Modify → shim** | Replace lines 1–419 with: module docstring + `from app.core.di.auth_dependencies_di import *` (≈ 12–20 lines, ≤ 50; R01, R07). |
| `tests/test_auth_dependencies_slice.py` | **Create** | Architectural pin test (R04). |
| `docs/audits/auth-dependencies-audit-2026-Q2.md` | **Modify** | Addendum appended after `#229 Addendum` (R05). |

**Shim body (canonical, target form):**

```python
"""Backward-compatibility shim — re-exports from app.core.di.auth_dependencies_di.

The 9 public symbols (`AuthenticatedUser`, `is_authenticated_user`,
`get_insforge_client_dep`, `get_current_user_optional`,
`return_early_if_response`, `require_authorized_user`, `require_writer_user`,
`require_developer_user`, `require_developer_user_redirect`) are defined in
``app/core/di/auth_dependencies_di.py`` per §33.3 (slice composition root).
This module preserves the historical import path for 19 consumer files
(see ``openspec/changes/auth-dependencies/proposal.md`` §3).
"""
from app.core.di.auth_dependencies_di import *  # noqa: F401,F403
```

`app/core/di/__init__.py` is **NOT** modified (locked decision 3): no new re-export there. The 9 names reach consumers only via the legacy shim path.

## 3. Interface contracts (the 9 public symbols)

| Symbol | Signature (byte-identical to current) | Imports / callers | Failure mode |
|---|---|---|---|
| `AuthenticatedUser` | `TypedDict` (`user_id: str`, `email: str`, `rol: str`, `is_authorized: bool`) | imported by `app/core/rbac.py`, 13 route modules, tests | type-only, no runtime fail |
| `is_authenticated_user(obj: object) -> TypeGuard[AuthenticatedUser]` | structural check | used in route handlers post `return_early_if_response` | narrow not narrow — never raises |
| `get_insforge_client_dep(request: Request) -> Iterator[InsForgeClient]` | yields pooled client from `app.state.insforge_client`; lazy-fallback to `InsForgeClient(settings.insforge_url, settings.insforge_service_key)` | `app/main.py`, `app/core/auth_flow.py`, 13 routes, `tests/test_auth_dependencies.py` | `AttributeError → fallback`; never raises; `yield` + `finally: pass` (rule §2) |
| `get_current_user_optional(request: Request) -> dict \| None` | delegates to `read_session_payload(request, secret=get_settings().session_secret)` | routes that render conditional UI | `None` on missing/invalid cookie, never raises |
| `return_early_if_response(value: Response \| AuthenticatedUser \| dict) -> Response \| None` | rule §7 helper; propagates redirects | 13 route modules | type discrimination only |
| `require_authorized_user(request, payload=Depends(get_current_user_optional), client=Depends(get_insforge_client_dep)) -> Response \| dict` | core guard; **NEW**: wraps `get_user_by_email(client, email)` in `try/except InsForgeError` (R03) | all guarded routes; `app/main.py` | `no_session → 302 /login`; `cookie_no_flag → 302 /unauthorized`; `no_email → 302 /unauthorized`; `db_reval_miss → 302 /unauthorized`; **`db_unreachable → 302 /unauthorized` (NEW, §32.P4 fix)** |
| `require_writer_user(user=Depends(require_authorized_user)) -> Response \| dict` | composes above; `user["rol"] not in Settings.writer_rols → HTTPException(403)` | 13 write routes | 403 + `log_safe("auth.denied", reason="writer_required", ...)` |
| `_resolve_developer_user(payload: Response \| dict) -> Response \| dict \| None` | private helper; `user["rol"] != Rol.DEVELOPER.value → None` | internal only | returns `None` on denial |
| `require_developer_user(payload=Depends(require_authorized_user)) -> Response \| dict` | composes above + `_resolve_developer_user`; `None → HTTPException(403)` | developer-only routes (audit log list, etc.) | 403 + `log_safe("auth.denied", reason="developer_required", ...)` |
| `require_developer_user_redirect(payload=Depends(require_authorized_user)) -> Response \| dict` | same as above but `None → RedirectResponse("/unauthorized", 302)` | `app/main.py` (admin panel pre-#146) | 302 + same audit event |

**Example call site** (existing, preserved verbatim):
```python
# app/modules/voluntarios/routes.py (line ~1)
from app.core.auth_dependencies import require_writer_user, return_early_if_response
```

## 4. Data flow — `require_authorized_user` with §32.P4 fix

```
HTTP request
    │
    ▼
┌── FastAPI resolves Depends() chain ────────────────────────────┐
│  payload     = Depends(get_current_user_optional)              │
│  client      = Depends(get_insforge_client_dep)                │
└────────────────────────────────┬────────────────────────────────┘
                                 ▼
Step 1: not payload? → log_safe("auth.denied", reason="no_session")
                       return RedirectResponse("/login", 302)
                                 ▼
Step 2: not payload.get("is_authorized", False)? (default-deny §6)
                       log_safe("auth.denied", reason="cookie_no_flag")
                       return RedirectResponse("/unauthorized", 302)
                                 ▼
Step 3: email = payload.get("email"); not isinstance/empty?
                       log_safe("auth.denied", reason="no_email")
                       return RedirectResponse("/unauthorized", 302)
                                 ▼
Step 4 (NEW):  ttl = Settings.auth_cache_ttl_seconds
                cached = get_cached_auth(email, ttl)
                if cached is None:
                    try:
                        fresh = get_user_by_email(client, email)   ← app.core.auth
                    except InsForgeError as exc:                  ← §32.P4 Variant A
                        log_safe("auth.denied",
                                 reason="db_unreachable",
                                 user_id=payload.get("user_id"))
                        return RedirectResponse("/unauthorized", 302)
                    if fresh is None: → db_reval_miss → 302 /unauthorized
                    set_cached_auth(email, is_authorized=True, rol=fresh["rol"])
                    payload["rol"] = fresh["rol"]; return payload
                if not cached.is_authorized: → db_reval_miss → 302 /unauthorized
                payload["rol"] = cached.rol; return payload
```

**Why `try/except` is the right shape** — matches rule §32.P4 criterion verbatim:

- **Names the error** (not bare `except Exception`): `except InsForgeError as exc`.
- **Logs structured** (rule §9): `log_safe("auth.denied", reason="db_unreachable", user_id=…)` — no PII, `reason` is closed-enum.
- **Returns HTTP, doesn't raise** (rule §7): `RedirectResponse("/unauthorized", 302)` — same shape as the four existing denial paths in this function.
- **Mirrors `oauth_di` narrow-catch precedent**: `test_oauth_slice.py::test_callback_propagates_insforge_error_from_exchange_real` shows the same error class is handled explicitly elsewhere in the codebase.

**Closure preservation** (`__cause__`): the exception is rebound to a return, so FastAPI's exception handler middleware never sees `InsForgeError` and cannot double-log it. `__cause__` of the redirect is implicit (the `RedirectResponse` does not chain `from exc`); if the operator needs the original traceback, the `log_safe` event carries `reason="db_unreachable"` and Sentry indexes on that.

## 5. §32.P4 fix — code shape (illustrative, not committed)

```python
# inside require_authorized_user, after step 3 (email validation), R03 verbatim
if cached is None:
    try:
        fresh = get_user_by_email(client, email)
    except InsForgeError:
        log_safe(
            "auth.denied",
            reason="db_unreachable",
            user_id=payload.get("user_id") if isinstance(payload, dict) else None,
        )
        return RedirectResponse(url="/unauthorized", status_code=302)
    if fresh is None:
        set_cached_auth(email, is_authorized=False, rol=None)
        log_safe(
            "auth.denied",
            reason="db_reval_miss",
            user_id=payload.get("user_id") if isinstance(payload, dict) else None,
        )
        return RedirectResponse(url="/unauthorized", status_code=302)
    set_cached_auth(email, is_authorized=True, rol=fresh["rol"])
    payload["rol"] = fresh["rol"]
    return payload
```

The `try/except` wraps the **single `client`-bound call** (`get_user_by_email`). It does NOT wrap the cache reads (`get_cached_auth`) — those are in-process and cannot raise `InsForgeError`. It does NOT wrap the `payload["rol"] = …` mutation — that is dict-internal.

## 6. Migration path

| Step | Action | Why |
|---|---|---|
| 1 | Create `app/core/di/auth_dependencies_di.py` containing the 9 symbols + private helper lifted verbatim from current `auth_dependencies.py` lines 50–419; add §32.P4 fix. | New home (locked decision 1). |
| 2 | Add `try/except InsForgeError` block around `get_user_by_email(client, email)` inside `require_authorized_user`. | R03, fix §32.P4 in the same PR. |
| 3 | Replace `app/core/auth_dependencies.py` body with the shim (docstring + `import *`). | R01, R07; preserves all 19 import sites transparently. |
| 4 | Add `from app.core.auth import get_user_by_email` (module level, unchanged) plus the other 7 module-level imports from the current file. Do NOT add a `lazy-import:` marker (issue #226 note: module-level import is the current convention; cycle doc lives in `decisiones-proyecto.md`). | Module-level import is unchanged; cycle is out of scope (spec §3). |
| 5 | Verify `python -c "import app.core.auth_dependencies"` succeeds and `dir(app.core.auth_dependencies)` contains all 9 names. | R01 mechanical check. |
| 6 | Run `python -m pytest -W error::DeprecationWarning tests/test_auth_dependencies.py tests/test_auth_session_is_authorized.py` — must pass without edits. | R09. |
| 7 | Run `ruff check .`, `python scripts/check_rules.py .`, `python -m mypy`, `python -m build`, `python scripts/check_module_size.py` — all green. | R06, R07. |
| 8 | Refresh `docs/audits/auth-dependencies-audit-2026-Q2.md` addendum. | R05. |

**No consumer needs editing.** All 19 files (`app/main.py`, 3 `core/`, 13 `modules/*/routes.py`, 2 `tests/`) import via `from app.core.auth_dependencies import <name>`, which the shim satisfies.

## 7. Pin test design (`tests/test_auth_dependencies_slice.py`)

The test follows the **catalogos_slice architectural-pin** precedent (`tests/test_catalogos_slice.py:547` `test_domain_layer_does_not_import_insforge`, :561 `test_application_layer_does_not_import_insforge`, :583 `test_di_layer_does_not_export_domain_or_port`).

### Test cases (≥ 5 atoms)

| # | Test | Asserts |
|---|---|---|
| 1 | `test_di_module_exports_all_nine_symbols` | `dir(app.core.di.auth_dependencies_di)` contains exactly the 9 public names; nothing else public. |
| 2 | `test_shim_reexports_all_nine_symbols` | `dir(app.core.auth_dependencies)` contains the 9 names; `app.core.auth_dependencies.<name> is app.core.di.auth_dependencies_di.<name>` (identity, not just equality). |
| 3 | `test_di_module_has_no_raw_sql_or_execute_sql` | AST walk of `app/core/di/auth_dependencies_di.py`: zero occurrences of `execute_sql(` (any module-level or function-level call). Failure message: `"raw execute_sql call found at line {N} inside {symbol}"`. |
| 4 | `test_require_authorized_user_catches_insforge_error_and_redirects` | Force `get_user_by_email` to raise `InsForgeError(503, ...)`. Call `require_authorized_user(request, payload={...}, client=stub)`. Assert: returns `RedirectResponse("/unauthorized", 302)`; **no exception propagates**; `log_safe` was called with `event="auth.denied"`, `reason="db_unreachable"`, `user_id=…`. |
| 5 | `test_di_module_nine_signatures_match_shim_byte_for_byte` | For each of the 9 names, `inspect.signature(app.core.auth_dependencies.<name>) == inspect.signature(app.core.di.auth_dependencies_di.<name>)`. Failure message: `"signature drift on {name}: shim={...} di={...}"`. |
| 6 | `test_di_module_under_module_size_budget` | `wc -l app/core/di/auth_dependencies_di.py` ≤ 700. (Already enforced by `scripts/check_module_size.py`; this test pins the same number for symmetry.) |
| 7 | `test_shim_under_fifty_lines` | `wc -l app/core/auth_dependencies.py` ≤ 50. |

### Why these atoms

- (1)–(2) pin **R01** (no missing re-export).
- (3) pins **R04** (no transport-shaped leaks: the dep module MUST NOT run SQL — the implementation calls `get_user_by_email`, which is the abstraction seam).
- (4) pins **R03** (the §32.P4 fix demonstrably works).
- (5) pins **R09** (byte-identical signatures). This is the canary that prevents `app.dependency_overrides` drift.
- (6)–(7) pin **R07** (the 700/50 budget; mirror of the existing ratchet with a one-test local equivalent).

The pin test does NOT replace `scripts/check_module_size.py` — both run; the test gives a faster, focused signal on regression.

## 8. Failure modes

| Requirement | Failure shape | Detection |
|---|---|---|
| R01 (shim) | Missing name → `ImportError: cannot import name 'X' from 'app.core.auth_dependencies'` at consumer module load | `tests/test_auth_dependencies_slice.py::test_di_module_exports_all_nine_symbols` + `test_shim_reexports_all_nine_symbols` |
| R02 (DI module exists) | `ModuleNotFoundError: app.core.di.auth_dependencies_di` | import smoke + test 1 |
| R03 (§32.P4 fix) | `InsForgeError` propagates → 500 (regression) | `test_require_authorized_user_catches_insforge_error_and_redirects` |
| R04 (no transport leak) | `client.execute_sql(` or new `InsForgeClient(...)` call added inside the di module | AST test 3 |
| R05 (audit doc) | Doc stale or verdict missing | `tests/test_audit_doc.py` (existing pattern) + reviewer checklist |
| R06 (CI green) | lint / typecheck / test / build red | `ci.yml` (lint, typecheck, test, security, integration, build); Detectors 5 (`raw_logger_in_app` §9), 6 (`print_in_app` §9), 11 (`unjustified_lazy_import` §26), 12 (cross-module imports §27) |
| R07 (module size) | `auth_dependencies_di.py` > 700 OR shim > 50 OR new `BASELINE` entry | `scripts/check_module_size.py` (CI lint job) + test 6/7 |
| R08 (default-deny + log_safe) | `Settings.auth_cache_ttl_seconds = 0` interpreted as "skip" instead of "revalidate" → review-test fails; `logger.*` or `print(` in the di module → Detector 5/6 fires | existing `tests/test_auth_dependencies.py::test_require_authorized_user_*` + Detector 5/6 |
| R09 (signature stability) | consumer test signature drift → `app.dependency_overrides` resolution fails at runtime | test 5 (pin) + existing `tests/test_auth_dependencies.py` running untouched |
| R10 (no `main.py` / `routes_registry.py` change) | diff includes those paths → review blocker | reviewer + `git diff main...HEAD --stat` |

## 9. Test plan (for `sdd-tasks` → `sdd-apply`)

| Layer | What | How |
|---|---|---|
| Architectural pin | 7 atoms in `tests/test_auth_dependencies_slice.py` (see §7) | `pytest tests/test_auth_dependencies_slice.py -v` |
| Signature smoke | Re-run `tests/test_auth_dependencies.py` (≈ 40 cases) WITHOUT edits | `pytest tests/test_auth_dependencies.py -v` |
| Auth contract smoke | Re-run `tests/test_auth_session_is_authorized.py` (≈ 10 cases) WITHOUT edits | `pytest tests/test_auth_session_is_authorized.py -v` |
| §32.P4 fix scenario | Force `get_user_by_email` → `InsForgeError(503, …)`; assert 302 + `log_safe("auth.denied", reason="db_unreachable")`; assert `pytest.raises(InsForgeError)` does NOT trigger | new atom in `test_auth_dependencies_slice.py` |
| Module size ratchet | di ≤ 700, shim ≤ 50, no new `BASELINE` | `python scripts/check_module_size.py` |
| Rule linters | Detectors 5, 6, 11, 12 stay green | `python scripts/check_rules.py .` |
| mypy | zero errors on `app/`, `migration/` | `python -m mypy` |
| ruff | clean | `ruff check .` |
| build | wheel + sdist succeed | `python -m build` |
| Coverage | global floor ≥ 80 % (§19); `app/core/di/` reported per-layer (§32.P8) | `pytest --cov=app --cov-fail-under=80` |

**Existing tests must pass unchanged.** Per R09 — they pin the byte-identical signature contract.

## 10. Audit doc outline (addendum appended to existing doc)

```
## Slice #420-7 Addendum — 2026-08-05  (auth-dependencies)

### Scope
- Files moved: app/core/auth_dependencies.py → app/core/di/auth_dependencies_di.py
- Files shrunk: app/core/auth_dependencies.py → ~20-line re-export shim
- New file: tests/test_auth_dependencies_slice.py
- This doc: refreshed addendum

### Methodology
1. CodeGraph caller map of the 9 symbols: 19 consumer files enumerated.
2. AST diff: shim body is `import *` plus a module docstring; no logic.
3. Signature comparison: `inspect.signature()` for each of the 9 names matches between
   shim and di module byte-for-byte.
4. §32.P4 review: identified the unhandled `InsForgeError` path in
   `require_authorized_user` → revalidation step; designed Variant A.

### Findings
| Severity | Finding | Resolution |
|---|---|---|
| CRITICAL | §32.P4: InsForgeError from get_user_by_email escaped as 500 | Variant A in same PR (try/except → log_safe + 302) |
| INFO | Module-level import from app.core.auth (cycle #226) | Documented in decisiones-proyecto.md; unchanged |
| INFO | Shim is 12–20 lines, well below the 50-line cap | No new BASELINE entry required |
| INFO | AuthCacheBackend Protocol exists but is bypassed by module-level facade | Pre-existing debt; out of scope |

### Verdict
PASS — slice migrated to app/core/di/, signatures byte-identical, §32.P4 fix in place,
no consumer import path broken, audit doc and pin test ship together.
```

## 11. Risks and mitigations

| # | Risk | Sev | Mitigation |
|---|------|-----|------------|
| 1 | §32.P4 `InsForgeError` not actually caught (test passes, prod breaks) | critical | Atom (4) forces `get_user_by_email` to raise; `pytest.raises(InsForgeError)` MUST NOT trigger — assertion on no-exception + on `log_safe` call args |
| 2 | Module-level import from `app.core.auth` reintroduces #226 cycle | warning | Cycle pre-existing; module-level import unchanged from current file (line 60) — same load order, same observed behavior. Documented in addendum. |
| 3 | Shim silently drops a name (typo) → 13 modules break at import | critical | Pin test atom (1)+(2) identity-checks the 9 names; `wc -l` regression test on the shim flags any drift |
| 4 | Auth cache call still bypasses `AuthCacheBackend` Protocol | suggestion | Pre-existing; addendum records as INFO; no change this PR |
| 5 | `app.dependency_overrides[get_insforge_client_dep]` breaks on signature drift | warning | Atom (5) pins signatures; existing `tests/test_auth_dependencies.py` uses `app.dependency_overrides[get_insforge_client]` (the `app.main` alias, not the di module's name) — verify this still resolves via re-export |
| 6 | `app/core/di/__init__.py` accidental re-export (locked decision 3 forbids it) | warning | Pin test atom (1) explicitly asserts that the 9 names are NOT in `dir(app.core.di)` — the di `__init__.py` only re-exports the slice's `get_*_port` provider, not the 9 dep names |
| 7 | `mypy` complains about `import *` in shim | suggestion | `noqa: F401,F403` on the import line; `from __future__ import annotations` keeps re-export types resolvable |
| 8 | `pyproject.toml` `fail_under = 80` (§19) drops because `app/core/di/` is now a fresh tree with no coverage | warning | Pin test atoms drive the coverage of the di module; per-layer report per §32.P8 |

## 12. Acceptance criteria (mirror spec §5)

1. All 9 re-exports verified present in the shim (`test_di_module_exports_all_nine_symbols`, `test_shim_reexports_all_nine_symbols`).
2. Pin test denies transport-shaped leaks; runs in CI; fails on regression (atoms 3, 6, 7).
3. `tests/test_auth_dependencies.py` + `tests/test_auth_session_is_authorized.py` pass WITHOUT modification.
4. CI green: lint (`ruff check .`), rule linter (`scripts/check_rules.py .`), typecheck (`python -m mypy`), test (`pytest -W error::DeprecationWarning`), build (`python -m build`) — per §15.1.
5. Module size: `auth_dependencies_di.py` ≤ 700, shim ≤ 50, no new `BASELINE` entry in `scripts/check_module_size.py`.
6. Audit doc addendum covers scope/methodology/findings/verdict per §12; refresh dated 2026-08-05.
7. §32.P4 fix demonstrable: `test_require_authorized_user_catches_insforge_error_and_redirects` forces `InsForgeError`, asserts 302 + `log_safe("auth.denied", reason="db_unreachable")` + `pytest.raises(InsForgeError)` does NOT trigger.
8. `app/main.py` and `app/routes_registry.py` diff is empty (R10).
9. `app/core/di/__init__.py` diff is empty (locked decision 3).

---

**Next**: ready for `sdd-tasks`. The 7 pin-test atoms plus the migration steps (1)–(8) decompose cleanly into deliverable sub-tasks under the 400-line review budget.
