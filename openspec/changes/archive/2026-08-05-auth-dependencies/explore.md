# Exploration: `auth-dependencies` Slice

**SDD change**: `auth-dependencies`
**Project**: `apap_web`
**Phase**: explore
**Date**: 2026-08-05

---

## 1. Current State of `app/core/auth_dependencies.py`

### What it exposes (7 public symbols, ~419 lines)

| Symbol | Type | Role |
|--------|------|------|
| `AuthenticatedUser` | `TypedDict` | Shape of the authenticated-user dict returned by auth deps |
| `is_authenticated_user` | `TypeGuard` function | Narrows `object` → `AuthenticatedUser` |
| `get_insforge_client_dep` | FastAPI `yield` dep | Yields the pooled `InsForgeClient` from `app.state` |
| `get_current_user_optional` | FastAPI dep | Returns session payload or `None` (no auth required) |
| `return_early_if_response` | Helper | Propagates `RedirectResponse`; rule §7 guard for handlers |
| `require_authorized_user` | FastAPI dep | Primary guard: demands valid session + `is_authorized=True`, revalidates via DB per request (issue #143) |
| `require_writer_user` | FastAPI dep | Composes `require_authorized_user`; adds role-check against `Settings.writer_rols`; raises HTTP 403 |
| `require_developer_user` | FastAPI dep | Composes `require_authorized_user`; demands `rol == "developer"`; raises HTTP 403 |
| `require_developer_user_redirect` | FastAPI dep | Same as `require_developer_user` but redirects to `/unauthorized` (302) instead of 403 |

### Structure

```
auth_dependencies.py (~419 lines)
├── TypedDict + TypeGuard (lines 69–102)
├── get_insforge_client_dep (lines 105–125)  — FastAPI dep, yields pooled client
├── get_current_user_optional (lines 128–136) — FastAPI dep, reads signed cookie
├── return_early_if_response (lines 139–162)  — rule §7 redirect guard
├── require_authorized_user (lines 165–256)    — core guard, ~92 lines, calls auth cache + DB
├── require_writer_user (lines 259–312)        — role guard, composes above
├── _resolve_developer_user (lines 315–327)   — private helper
├── require_developer_user (lines 330–377)     — role guard
└── require_developer_user_redirect (lines 380–419) — role guard, redirect variant
```

### Key implementation detail: the lazy-import cycle

```python
# auth_dependencies.py line 235 — inside require_authorized_user:
fresh = get_user_by_email(client, email)   # ← get_user_by_email imported from app.core.auth
```

`get_user_by_email` is imported at **module level** from `app.core.auth` (line 60). The `lazy-import:` marker convention (rule §26) applies to *local* imports inside function bodies; the module-level import from `app.core.auth` does NOT carry the marker but is also part of the known cycle tracked in issue #226. The cycle: `app.core.auth` imports from `app.core.config` (for `Settings`), and vice-versa.

### FastAPI DI patterns used

- `Depends(get_current_user_optional)` — layered dep: session → auth check
- `Depends(get_insforge_client_dep)` — request-scoped pooled client
- `yield` on `get_insforge_client_dep` — rule §2 compliance (client owned by lifespan, not this dep)
- Return types are `Response | dict` — redirects ARE the control flow, not exceptions (rule §7)

---

## 2. Established Sibling Pattern (`app/core/di/`)

### Canonical layout (per §33.3)

```
app/core/
├── domain/auth/
│   ├── rol.py            — Rol StrEnum
│   └── user.py           — AuthorizedUser entity
├── ports/
│   └── auth_port.py      — AuthUsersPort Protocol (CRUD for usuarios_autorizados)
├── adapters/insforge/
│   └── auth_insforge_adapter.py — InsForgeAuthUsersAdapter
├── application/auth/
│   ├── add_authorized_user.py
│   ├── deactivate_authorized_user.py
│   └── _domain_errors.py
├── di/
│   ├── __init__.py       — re-exports all get_<slice>_port providers
│   ├── auth_di.py        — get_auth_users_port (46 lines)
│   ├── catalogos_di.py   — get_catalogos_port (90 lines)
│   └── oauth_di.py       — get_oauth_port (100 lines)
```

### DI provider shape (template: `catalogos_di.py` / `oauth_di.py`)

```python
def get_<slice>_port(request: Request) -> Iterator[<PortProtocol>]:
    try:
        client = request.app.state.insforge_client
    except AttributeError:
        settings = get_settings()
        client = InsForgeClient(settings.insforge_url, settings.insforge_service_key)
        request.app.state.insforge_client = client
    try:
        adapter = <ConcreteAdapter>(client)
        yield adapter
    finally:
        pass  # blank finally: seam for future per-worker cleanup
```

### `di/__init__.py` re-exports

```python
from app.core.di.auth_di import get_auth_users_port
from app.core.di.catalogos_di import get_catalogos_port
from app.core.di.oauth_di import get_oauth_port
# ... etc
__all__ = ["get_auth_users_port", "get_catalogos_port", "get_oauth_port", ...]
```

---

## 3. Consumer Map of `app/core/auth_dependencies`

**Total: 19 files** importing from `auth_dependencies`.

### By layer

| Layer | Files | Symbols imported |
|-------|-------|-----------------|
| `app/main.py` | 1 | `get_insforge_client_dep`, `require_authorized_user`, `require_developer_user_redirect` |
| `app/core/` (infra) | 3 | `get_insforge_client_dep`, `require_authorized_user`, `require_developer_user_redirect`, `AuthenticatedUser` |
| `app/modules/*/routes.py` (13 modules) | 13 | `require_authorized_user`, `require_writer_user`, `require_developer_user`, `require_developer_user_redirect`, `AuthenticatedUser`, `is_authenticated_user`, `return_early_if_response` |
| `tests/` | 2 | (test auth session + test auth dependencies) |

### Full consumer list

```
app/main.py
app/core/admin_handlers.py
app/core/auth_flow.py         ← get_insforge_client_dep
app/core/rbac.py              ← AuthenticatedUser
app/modules/acogidas/routes.py
app/modules/adopciones/routes.py
app/modules/animals/routes.py
app/modules/cesiones/routes.py
app/modules/entradas/batch_routes.py
app/modules/entradas/routes.py
app/modules/foster/assignment_routes.py
app/modules/foster/routes.py
app/modules/materiales/acogida_routes.py
app/modules/materiales/routes.py
app/modules/salud/routes.py
app/modules/sanidad/batch_routes.py
app/modules/sanidad/routes.py
app/modules/tasks/routes.py
app/modules/voluntarios/routes.py
tests/test_auth_dependencies.py
tests/test_auth_session_is_authorized.py
```

### Re-export chain risk

No consumer re-exports from `auth_dependencies` — all import directly from the module path. This is good for backward-compat: a re-export shim in `auth_dependencies.py` that re-exports from a new location would be transparent to all consumers.

---

## 4. Mapping to §33.3 Contract

### What `auth_dependencies` actually manages (two separate concerns)

| Concern | Type | Hexagonal slot |
|---------|------|---------------|
| `usuarios_autorizados` CRUD (get_user_by_email, etc.) | Already refactored | `app/core/ports/auth_port.py` + `app/core/di/auth_di.py` |
| Session-payload reading (`get_current_user_optional`) | HTTP-level | Remains in route/dependency layer |
| Auth guards (`require_authorized_user`, etc.) | HTTP-level | Remains in route/dependency layer |
| Auth cache (`get_cached_auth`, `set_cached_auth`) | In-process cache | `app/core/auth_cache.py` (already separate) |

### The refactoring challenge

`auth_dependencies` is **not** a CRUD slice. It is a **session/authorization middleware** that:
1. Reads the signed session cookie
2. Optionally re-validates against `usuarios_autorizados` (with in-process cache)
3. Returns either a `RedirectResponse` or an `AuthenticatedUser` dict

The `AuthUsersPort` already handles the "get user by email" piece. The remaining piece is the **HTTP-level guard composition** — `require_authorized_user`, `require_writer_user`, `require_developer_user`, `require_developer_user_redirect`.

### Proposed directory layout

```
app/core/
├── auth_dependencies.py           ← THIN RE-EXPORT SHIM (backward compat)
│                                  ← all 9 public symbols re-exported from new home
├── ports/
│   └── auth_session_port.py       ← NEW: Protocol for require_*_user functions
├── di/
│   └── auth_dependencies_di.py   ← NEW: get_require_authorized_user etc.
```

### What a `ports/auth_session_port.py` would declare

The `require_authorized_user` family does NOT fit the "port as a CRUD interface" pattern cleanly — it is a FastAPI `Depends()` callable that composes multiple concerns. However, the Protocol approach (§31) can still apply to the **result type**:

```python
class AuthSessionPort(Protocol):
    """Protocol for session validation and authorization guards.

    The concrete implementation lives in app/core/di/auth_dependencies_di.py.
    Route handlers depend on this Protocol, never on the concrete dependency.
    """

    def require_authorized_user(
        self,
        request: Request,
        payload: dict | None,
        client: InsForgeClient,
    ) -> Response | dict: ...

    def require_writer_user(
        self,
        user: Response | dict,
    ) -> Response | dict: ...
```

**Alternative**: Keep these as plain functions in `di/auth_dependencies_di.py` without a Protocol. The `catalogos_di.py` pattern is "a provider that yields a port instance"; the `auth_dependencies` pattern is "a module with multiple standalone FastAPI deps". The Protocol is less natural here. **Recommendation: plain module with provider functions, no Protocol**, mirroring the current structure but moved to `di/`.

---

## 5. Risks and Blockers

### Risk 1: §32.P4 — Partial exception handling in `require_authorized_user`
- **Severity**: critical
- **Description**: `require_authorized_user` calls `get_user_by_email(client, email)` (from `app.core.auth`) which can raise `InsForgeError`. The function has no `try/except` around this call. A network failure → unhandled `InsForgeError` → 500.
- **Current state**: Same issue existed before; the refactor should NOT make it worse. Adding `try/except InsForgeError` is a one-line fix within the same function.
- **Blocker?**: No — fixable in the same PR.

### Risk 2: Backward-compat re-export must preserve all 9 public symbols
- **Severity**: critical
- **Description**: 19 consumers import specific symbols. The shim must re-export ALL of them from the new location. Missing any breaks 13 route modules + `main.py`.
- **Diff shape**:
  ```python
  # NEW: app/core/di/auth_dependencies_di.py
  from app.core.auth_dependencies_impl import (
      AuthenticatedUser, is_authenticated_user,
      get_insforge_client_dep, get_current_user_optional,
      return_early_if_response, require_authorized_user,
      require_writer_user, require_developer_user,
      require_developer_user_redirect,
  )
  
  # app/core/auth_dependencies.py (becomes shim)
  from app.core.di.auth_dependencies_di import *
  ```
- **Blocker?**: No — mechanically solvable.

### Risk 3: `require_authorized_user` embeds auth cache (`get_cached_auth`/`set_cached_auth`)
- **Severity**: warning
- **Description**: The guard function calls `auth_cache` module-level facades (`get_cached_auth`, `set_cached_auth`) directly. These are NOT on a port. The `AuthCacheBackend` Protocol already exists (`app/core/auth_cache.py:84`). This is a pre-existing architecture debt, not introduced by this refactor.
- **Blocker?**: No — existing pattern, no worse than before.

### Risk 4: Lazy-import cycle `app.core.auth ↔ app.core.auth_dependencies`
- **Severity**: warning
- **Description**: `auth_dependencies` imports `get_user_by_email` from `app.core.auth` at module level. Issue #226 tracks this. The refactor moves the dep *call* into `di/` but the import stays in `app.core.auth` (the service, already separate).
- **Blocker?**: No — already documented with `lazy-import:` convention (rule §26).

### Risk 5: Tests that pin `auth_dependencies` import path
- **Severity**: warning
- **Description**: `tests/test_auth_dependencies.py` and `tests/test_auth_session_is_authorized.py` import from `app.core.auth_dependencies` directly. The re-export shim preserves the path, so tests should not break. However, test overrides (`app.dependency_overrides`) may need adjusting if the DI wiring changes.
- **Blocker?**: No — re-export shim preserves the path.

### Risk 6: Module size — new `di/auth_dependencies_di.py`
- **Severity**: suggestion
- **Description**: `auth_dependencies.py` is 419 lines. Moving its implementation to `di/auth_dependencies_di.py` keeps it well under the 700-line cap (rule §21). The shim in `auth_dependencies.py` will be ~20 lines.
- **Blocker?**: No.

### Risk 7: §32.P4 InsForgeError not caught — 500 on network failure
- **Severity**: critical
- **Description**: Same as Risk 1 but in context of the guard's call to `get_user_by_email`. This is an existing bug that predates this refactor. The fix should be included in this PR (catch `InsForgeError`, log, redirect to `/unauthorized` or return 503).
- **Blocker?**: No, but must be addressed in the same PR.

---

## 6. Backward Compatibility Strategy

**Handoff says**: *"Compatibilidad hacia atrás por re-exports desde la ruta antigua."*

### Phase 1: Create new implementation in `di/`

```python
# app/core/di/auth_dependencies_di.py
"""FastAPI dependency wiring for session/authorization guards.

Moved from app/core/auth_dependencies.py (issue #226 follow-up).
All 9 public symbols are re-exported from here.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import TypeGuard

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from starlette.responses import Response
from typing_extensions import TypedDict

# lazy-import: avoids circular import with app.core.auth (auth.py
# imports Settings at module load time).
from app.core.auth import get_user_by_email
from app.core.auth_cache import get_cached_auth, set_cached_auth
from app.core.config import get_settings
from app.core.insforge import InsForgeClient
from app.core.logging import log_safe
from app.core.roles import Rol
from app.core.session import read_session_payload

# (all 9 symbols implemented here, identical to current auth_dependencies.py)
# + InsForgeError handling fix (§32.P4)
```

### Phase 2: Make `auth_dependencies.py` a thin shim

```python
# app/core/auth_dependencies.py
"""Backward-compatibility shim — re-exports from new DI location.

All symbols are now provided by app.core.di.auth_dependencies_di.
This file exists solely to preserve the import path for existing callers.
"""
from app.core.di.auth_dependencies_di import *
```

### Semantics preserved

- All 9 public symbols have identical signatures
- `require_authorized_user` behavior is unchanged (same cache-hit/miss flow)
- `require_writer_user` and `require_developer_user` compose the same way
- Default-deny (`is_authorized` defaults to `False`) is preserved (§6)
- Redirect-not-exception pattern is preserved (§7)
- `log_safe` events with reason enums are preserved (§9)

### Default-allow vs default-deny: no semantic change

The v1 path had the same semantics as the v2 path. No gap here.

---

## 7. Architectural Pin Test

### Precedent from sibling slices

Each of the 5 existing slices ships a pin test that fails if a transport import sneaks into domain/ports/application. For `auth_dependencies`, the analogous test would verify:

1. **No InsForge transport in session guard logic**: `app/core/di/auth_dependencies_di.py` may import `InsForgeClient` (for the dep), but the **implementation** of `require_authorized_user` must NOT contain raw SQL or `execute_sql` calls.
2. **Auth cache is accessed via the module facade only**: `get_cached_auth`/`set_cached_auth` from `auth_cache.py` are acceptable; direct `InProcessAuthCache` instantiation is not.
3. **No circular import at module load time**: importing `auth_dependencies` must not trigger `app.core.auth` import cycle at module level (enforced by lazy-import marker on the one internal call).

### Suggested test name and location

`tests/test_auth_dependencies_slice.py` — following `tests/test_catalogos_slice.py`, `tests/test_oauth_slice.py` pattern.

---

## 8. CodeGraph Status

**`codegraph status .`**: `[!] The last index run never finished (killed mid-index?) — the index is truncated.`

- After `codegraph sync .`: `Already up to date`
- Staleness banner present for: `00_main/app/core/ports/auth_port.py`, `00_main/app/core/ports/oauth_port.py`, `00_main/app/core/domain/auth/user.py`, `00_main/app/core/insforge.py`, `00_main/app/core/adapters/insforge/catalogos_insforge_adapter.py`
- `codegraph_status`: **synced** (sync completed successfully; banner files are pending but not blocking)

---

## 9. Questions / Unknowns

### Q1: Protocol or plain module for the session guard DI?

The sibling slices (`auth_di`, `catalogos_di`, `oauth_di`) all yield a **port Protocol instance**. `auth_dependencies` is different: its 9 public symbols are standalone FastAPI `Depends()` factories, not methods on an object. 

**Two options**:
- **Option A (plain module)**: `di/auth_dependencies_di.py` is a plain module with the 9 dep functions. No Protocol. No `__init__.py` change needed (consumers keep importing from `app.core.auth_dependencies`). Clean, minimal.
- **Option B (Protocol + provider)**: Define `AuthSessionPort` Protocol with the 9 callables as methods, then have `get_auth_dependencies_port()` yield an instance. More consistent with sibling slices but adds indirection with no clear benefit since these are not CRUD operations.

**Recommendation**: Option A — plain module in `di/`, thin re-export shim in `auth_dependencies.py`. This matches the actual nature of the code (FastAPI dependency factories, not a backend interface).

### Q2: Should `AuthenticatedUser` TypedDict move to `domain/auth/`?

`AuthenticatedUser` (session-layer shape) and `AuthorizedUser` (database-layer entity in `domain/auth/user.py`) are different types. Moving `AuthenticatedUser` to `domain/auth/` would be clean but requires updating 13 route files that import it. The re-export shim handles this transparently either way.

**Recommendation**: Keep `AuthenticatedUser` in the re-export shim for now; it is a session-payload shape, not a domain entity.

### Q3: §32.P4 fix — should it be in the same PR or a separate one?

`require_authorized_user` does not catch `InsForgeError` from `get_user_by_email`. This is a pre-existing bug (§32.P4 partial exception handling). The fix is a `try/except InsForgeError` around the DB call.

**Recommendation**: Fix in the same PR. It's a one-line catch, it directly relates to the refactor's goal (clean exception handling), and leaving it for a follow-up means the new code ships with the same bug.

---

## 10. Top 3 Risks Summary

| # | Risk | Severity | Mitigation |
|---|------|----------|------------|
| 1 | §32.P4: `InsForgeError` not caught in `require_authorized_user` → 500 on network failure | critical | Add `try/except InsForgeError` in same PR |
| 2 | Missing any of 9 re-exported symbols in shim → 13 route modules break | critical | Re-export all 9 symbols; automated test verifying all 9 names exist |
| 3 | Tests that override `app.dependency_overrides` may break if DI wiring changes signature | warning | Verify `tests/test_auth_dependencies.py` and `tests/test_auth_session_is_authorized.py` pass after refactor |
