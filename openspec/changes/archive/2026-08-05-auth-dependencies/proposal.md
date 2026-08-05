# Proposal: `auth-dependencies` Slice

## 1. Summary

Move `app/core/auth_dependencies.py` (9 FastAPI deps, ~419 lines) into
`app/core/di/auth_dependencies_di.py`; reduce the original to a re-export
shim. Same PR applies the §32.P4 `InsForgeError` fix and refreshes the
audit doc.

Last `core/` seam of epic #420. 11 module slices import ≥1 of the 9
symbols and are blocked. Handoff priority 1.a.

## 2. Context

Epic #420. Six slices merged: #414, #415, #416, #417, #418, #419. §33.3
names `app/core/di/<slice>_di.py` as the composition root. §31 binds
domain services to Protocols, but auth deps are `Depends()` factories
(not CRUD) — Option A, orchestrator-locked. 19 consumers: `main.py`, 3
`core/`, 13 module `routes.py`, 2 tests.

## 3. Scope

**In scope** — new `app/core/di/auth_dependencies_di.py` (9 deps + §32.P4
fix); shrink `app/core/auth_dependencies.py` to a ~20-line shim; new
`tests/test_auth_dependencies_slice.py`; update
`docs/audits/auth-dependencies-audit-2026-Q2.md`.

**Out of scope** — 11 module slices (separate PRs); `app/main.py` +
`app/routes_registry.py` (flag if forced); #226 cycle (document, don't
resolve); `app/core/auth_cache.py`; ratchet files (flag if needed).

## 4. Approach (Option A — locked)

Move the 9 functions verbatim to
`app/core/di/auth_dependencies_di.py` with unchanged imports
(`app.core.auth.get_user_by_email`, `app.core.auth_cache`,
`app.core.config`, `app.core.insforge`, `app.core.logging.log_safe`,
`app.core.roles`, `app.core.session`). §32.P4 fix: wrap
`get_user_by_email(client, email)` in `try/except InsForgeError` →
catch `log_safe("auth.denied", reason="db_unreachable")` →
`RedirectResponse("/unauthorized", 302)`. Mirrors denied-flow 302 and
`oauth_di` narrow-catch. Shrink `app/core/auth_dependencies.py` to
`from app.core.di.auth_dependencies_di import *` + back-compat
docstring. Pin test: no raw SQL; 9 names re-exported; `InsForgeError`
redirects, doesn't raise.

## 5. Risks

| # | Risk | Sev | Mitigation |
|---|------|-----|------------|
| 1 | §32.P4 unhandled `InsForgeError` → 500 | critical | try/except fix in same PR |
| 2 | Missing 9 re-exports breaks 13 modules + main + 3 core | critical | `import *` shim + pin test |
| 3 | `app.dependency_overrides` overrides break on signature drift | warning | Signatures byte-identical |
| 4 | Lazy-import cycle #226 carries over | warning | Module-level import unchanged |
| 5 | Auth-cache call bypasses port Protocol | suggestion | Pre-existing debt, out of scope |

## 6. §32 Anti-Pattern Check

§32.P1 mitigated (slice IS the HTTP edge). **§32.P4 FIXED in this
slice.** §32.P3 mitigated (pin test). §32.P5 mitigated (new docstring
describes current flow). §32.P2/P6/P7 N/A. §32.P8 watch — report
per-layer coverage for `app/core/di/`.

## 7. Definition of Done

9 symbols re-exported. `InsForgeError` → 302 `/unauthorized` with
`log_safe("auth.denied", reason="db_unreachable")`. Pin test green. The
2 existing test files green, signatures unchanged. Audit doc updated.
CI green: lint, typecheck, test (`-W error::DeprecationWarning`), build.
Module size: new ≤700 (§21), shim ≤50. `main.py` and
`routes_registry.py` untouched.

## 8. Deliverables

| Action | Path |
|--------|------|
| Create | `app/core/di/auth_dependencies_di.py` (~430 lines) |
| Modify | `app/core/auth_dependencies.py` → shim (~20 lines) |
| Create | `tests/test_auth_dependencies_slice.py` |
| Modify | `docs/audits/auth-dependencies-audit-2026-Q2.md` |

No deletions, deps, `main.py`/`routes_registry.py` changes, or ratchet
edits.