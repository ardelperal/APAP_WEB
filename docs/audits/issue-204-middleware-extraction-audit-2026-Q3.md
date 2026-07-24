# Auth-Middleware Extraction Audit — 2026 Q3

**Audit slice**: Issue `#204` (refactor — no behaviour change)
**Branch**: `refactor/issue-204-auth-extraction`
**PR**: pending (`ardelperal/APAP_WEB`)
**Date**: 2026-07-22
**Auditor**: AI-assisted audit driven by `code-review-expert` lens + full
local validation (`pytest`, `ruff`, `mypy`, `scripts/check_rules.py`,
`scripts/check_module_size.py`) + coverage gate.
**Motivation**: the 2026-07-18 audit recommended extracting the auth-chain
setup out of `app/main.py` to shrink a 689-line factory into a thin
shell and centralise the registration alongside the existing
middleware definitions (`CsrfMiddleware`, `UADetectionMiddleware`). The
extraction is a **refactor**: no behaviour change. This audit certifies
that the contracts the auth chain enforces remain identical after the
move and that no new attack surface was introduced.

---

## Scope

| In-scope | Out-of-scope |
|---|---|
| FastAPI middleware chain order (`CsrfMiddleware` → `protect_user_facing_routes` → `UADetectionMiddleware`) | Handler-level `Depends(require_authorized_user)` (unchanged, still imports from `app/core/auth_dependencies.py`) |
| Auth-redirect contracts (302 to `/login`, 302 to `/unauthorized`) for protected routes | OAuth flow (`/auth/google`, `/auth/callback`, `/logout`) handlers — these stay in `app/main.py` because they are application-level glue, not "domain module" routes |
| Default-deny `payload.get("is_authorized", False)` invariant | Domain modules (`/animales`, `/voluntarios`, etc.) — unchanged, no SQL touched |
| `Settings.csrf_enabled` feature flag (Slice 5) | New dependencies (no `pyproject.toml` change in this PR) |
| `UADetectionMiddleware` still fires before the auth middleware (architectural contract, see `app/core/middleware.py:296-302` comment) | Templates / static assets |

## Methodology

1. **Diff pre-/post-refactor runtime stack**: introspected both the
   pre-refactor `app/main.py::create_app` (checked out at `origin/main`)
   and the post-refactor version of the same call. Compared the
   middleware descriptors in `app.user_middleware` and the
   `(method, path)` sets in `app.routes` — exact equality required.
2. **Full pytest run**: `python -m pytest -W error::DeprecationWarning
   --ignore=tests/e2e --deselect tests/test_voluntarios_concurrent.py
   --cov=app --cov-report=json --cov-fail-under=80 -q`. Coverage floor
   met (89.18%); CRITICAL_HELPERS gate PASS at 21/21 helpers @100%.
3. **Rule linter**: `python scripts/check_rules.py .` — Detector 7
   (`csrf_middleware_registered`) re-scoped to verify both
   `app/main.py` (calls `install_auth_middleware`) AND
   `app/core/middleware.py` (registers `CsrfMiddleware`). Detector 8
   (`csrf_samesite_strict`) and 6 (`print_in_app`) unchanged; both
   stay green.
4. **Type/static checks**: `ruff check .` clean; `python -m mypy`
   clean.
5. **New TDD surface**: `tests/test_middleware_install.py` and
   `tests/test_routes_registry.py` exercise the new structure with
   `app.user_middleware` and `app.routes` introspection (same
   introspection surface the existing
   `tests/test_middleware.py::test_ua_detection_middleware_is_registered_in_app`
   uses).
6. **End-to-end auth contract**: `tests/test_public_paths.py` (4
   atoms) and `tests/test_middleware_is_authorized.py` (functional
   atoms) continue to pass without rewriting their behaviour
   assertions. Only source-location pins were updated to track the
   `app/main.py` → `app/core/middleware.py` move (see §Source-pin
   tracking below).

---

## Findings

| Severity | Count | Status |
|---|---|---|
| **P0** Critical | 0 | none |
| **P1** High | 0 | none |
| **P2** Medium | 0 | none |
| **P3** Low | 1 | informational — detector scope update (§Detector 7 scope) |

### P3 — Detector 7 scope (informational)

`scripts/check_rules.py::_check_csrf_middleware_registered` previously
walked `app/main.py` for the literal `CsrfMiddleware` string. After
`#204`, the class reference lives in `app/core/middleware.py::install_auth_middleware`.
The detector was updated to walk BOTH files: `app/main.py` must call
`install_auth_middleware` (the bootstrapping surface), `app/core/middleware.py`
must reference `CsrfMiddleware` (the actual registration). Dropping
either half is a regression. The two-file check is structurally
equivalent to the old single-file check (same regression window
covered); no operator-facing change.

### Source-pin tracking (informational)

Two pre-existing meta-tests pinned the source location of the
default-deny substring and the `read_session_payload` call:

- `tests/test_middleware_is_authorized.py::test_middleware_default_false_en_fuente`
  — reads `app/main.py`, asserts the `payload.get("is_authorized", False)`
  literal is present. **Updated** to read `app/core/middleware.py`.
- `tests/test_middleware_is_authorized.py::test_solo_dos_call_sites_en_app`
  — counts `if not payload.get("is_authorized"` lines in `app/`,
  asserts the file set is `{app/main.py, app/core/auth_dependencies.py}`.
  **Updated** to assert `{app/core/middleware.py, app/core/auth_dependencies.py}`.
  The call-count invariant (2) is preserved.
- `tests/test_auth_dependencies.py::test_middleware_uses_read_session_payload`
  — reads `app/main.py`, asserts `read_session_payload(` literal.
  **Updated** to read `app/core/middleware.py`.

The **behaviour** pinned by each test (default-deny; no inline
snippet; call exists at all) is unchanged; only the FILE the test
reads was updated to track the refactor's code move. This is the
correct outcome: source-pinning tests are anti-patterns for refactors,
and updating them to follow the moved code is required when the move
is the explicit goal of the issue. Each updated test carries a
migration comment in the diff explaining the change.

No other test or template was modified.

---

## Verdict

**PASS.** Issue `#204` is a behaviour-preserving extraction. The
auth-chain order on a request (`UADetection → protect → Csrf → routes`)
is unchanged. The default-deny `is_authorized` contract is preserved.
The `CsrfMiddleware` feature-flag guard is preserved. The auth-flow
redirect contract (302 to `/login`, 302 to `/unauthorized`) is
unchanged. Every public-path and PII-path test continues to pass
without rewriting the assertions. The two source-pinning tests track
the moved location with the count invariant intact.

No new attack surface introduced. No new dependencies. No new env vars.

## Correction (2026-07-22): routes-registry prefix test failure on FastAPI >=0.137

CI run `29953269866` (job `test`) failed the 8 parametrized atoms of
`tests/test_routes_registry.py::test_register_routers_includes_each_module_router`
(`/animales`, `/entradas`, `/voluntarios`, `/sanidad`, `/adopciones`,
`/acogidas`, `/cesiones`, `/materiales`) on a fresh FastAPI app. The
local pre-push run passed only because the dev venv pinned
`fastapi==0.133.1`; CI resolves `fastapi>=0.115` and pip pulls
`fastapi 0.137.2`, which changed `app.include_router(...)` (PR
[fastapi/fastapi#15745](https://github.com/fastapi/fastapi/pull/15745))
to store a `_IncludedRouter` wrapper in `app.routes` that does not
expose `.path` or `.methods`. The set comprehension
`{r.path for r in app.routes if hasattr(r, 'path')}` therefore
dropped every registry route, leaving only FastAPI defaults
(`/openapi.json`, `/docs`, `/redoc`) — none match the asserted
prefixes.

Fix in `tests/test_routes_registry.py:58-87, 229-271`: the helper
`_extract_method_path_pairs` and the inline path-set walker in
`test_register_routers_includes_each_module_router` now recurse
into `_IncludedRouter.original_router.routes` (the wrapped
`APIRouter`'s child routes, whose `.path` is already composed).
`app/routes_registry.py` is unchanged — the registry is correct; the
test was relying on a flat `app.routes` shape that FastAPI 0.137
deliberately stopped returning (per upstream discussion
[fastapi/fastapi#15791](https://github.com/fastapi/fastapi/discussions/15791)).
Verified locally against clean venvs on `fastapi 0.133.1` (2505
passed, 0 failed) and `fastapi 0.137.2` (2503 passed, 0 failed),
plus `ruff`, `mypy`, `scripts/check_rules.py`,
`scripts/check_module_size.py` clean. CRITICAL_HELPERS gate
21/21 @100% on both. New CI run URL in the commit body.

## Test Plan re-run evidence

- `pytest … --cov-fail-under=80`: **2517 passed, 2 skipped, 2 deselected**,
  coverage **89.18%** (above 80% floor). `CRITICAL_HELPERS` gate
  21/21 @100% PASS.
- `ruff check .`: clean.
- `python -m mypy`: clean (92 files).
- `python scripts/check_rules.py .`: clean (Detector 7 new two-file
  check + Detectors 6/8 unchanged).
- `python scripts/check_module_size.py`: clean. `app/main.py`
  shrunk from 689 → 544 lines (~21% reduction). New
  `app/core/middleware.py` 197 lines (under 700-line budget);
  `app/routes_registry.py` 62 lines.

## Rollback plan

The refactor is structurally additive (new modules + import-time
preserved behaviour). Rollback is `git revert <merge-sha>` — no
database migration, no env-var change, no operator action required.
The pre-refactor `app/main.py` is fully self-contained (no new
modules depended on its inline definition), so rollback cannot break
any module that did not opt-in to the new imports during the brief
window the PR was open.
