# Tasks: `auth-dependencies` slice — shim + di + §32.P4 fix

**Change**: `auth-dependencies` · **Project**: `apap_web` · **Phase**: tasks
**Date**: 2026-08-05
**Source**: design.md + spec.md + proposal.md + locked decisions (engram #24057) + gate review (engram #24069)
**Execution order**: T01 → T02 → T03 → T04 → T05 → T06 → T07 → T08 → T09 → T10 → T11 → T12 → T13 → T14
**Delivery strategy**: single PR (exception-ok per preflight); diff ≤ 400 lines

---

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~380–420 (di module ~370 + shim ~20 + pin test ~80 + audit addendum ~30) |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR — all 4 deliverables in one commit |
| Delivery strategy | exception-ok (single PR, no re-prompt on size) |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

---

## Phase 1: Skeleton — new di module

### T01 — Create `app/core/di/auth_dependencies_di.py` skeleton (no §32.P4 fix yet)

**Spec**: R01, R02, R09; D§2 module layout.
**Files**: `app/core/di/auth_dependencies_di.py` (create).
**Steps**:
- Read `app/core/auth_dependencies.py` lines 1–419.
- Create `app/core/di/auth_dependencies_di.py` with the same module docstring (adapted), same imports, same 9 public symbols + private helper `_resolve_developer_user`, identical signatures.
- Do NOT add the §32.P4 fix yet — plain lift verbatim.
- Add `# noqa: F401,F403` on the `from app.core.di.auth_dependencies_di import *` line (will be added in T04).
- `from __future__ import annotations` at top.
**Verification**: `python -c "import app.core.di.auth_dependencies_di; print(dir(app.core.di.auth_dependencies_di))"` shows all 9 names; no ImportError.
**Done when**: `app/core/di/auth_dependencies_di.py` exists with all 9 symbols, same signatures as the source, and compiles without error.

---

## Phase 2: §32.P4 fix

### T02 — Apply §32.P4 Variant A fix inside `require_authorized_user`

**Spec**: R03, R08; D§4 data flow, D§5 code shape; gate correction 5 (bare `except InsForgeError:`).
**Files**: `app/core/di/auth_dependencies_di.py` (modify).
**Steps**:
- Locate the `if cached is None:` block inside `require_authorized_user` in the new di module.
- Wrap `get_user_by_email(client, email)` call in `try/except InsForgeError:` (bare except, no `as exc` — matches existing code style at line 237).
- On exception: `log_safe("auth.denied", reason="db_unreachable", user_id=payload.get("user_id") if isinstance(payload, dict) else None)` then `return RedirectResponse(url="/unauthorized", status_code=302)`.
- Do NOT bind `as exc` — variable is unused.
**Verification**: `grep -n "except InsForgeError" app/core/di/auth_dependencies_di.py` finds the block; `ruff check app/core/di/auth_dependencies_di.py` is clean.
**Done when**: The §32.P4 try/except block is present and uses bare `except InsForgeError:`.

---

## Phase 3: Shim creation

### T03 — Verify ImportError safety on the shim

**Spec**: R01; gate correction 5.
**Files**: `app/core/auth_dependencies.py` (modify — interim only; final form in T04).
**Steps**:
- Write the shim body (module docstring + `from app.core.di.auth_dependencies_di import *  # noqa: F401,F403`).
- Verify `python -c "from app.core.auth_dependencies import *; print('OK')"` runs without ImportError.
**Verification**: Import succeeds and all 9 names are in `dir(app.core.auth_dependencies)`.
**Done when**: Shim body compiles and re-exports all 9 names without ImportError.

### T04 — Shrink `app/core/auth_dependencies.py` to the final shim (≤50 lines)

**Spec**: R01, R07; D§2 module layout.
**Files**: `app/core/auth_dependencies.py` (modify → shim).
**Steps**:
- Replace lines 1–419 with: module docstring (back-compat note) + `from app.core.di.auth_dependencies_di import *  # noqa: F401,F403`.
- Target ≤50 lines total (docstring + import + blank lines).
**Verification**: `wc -l app/core/auth_dependencies.py` returns ≤50.
**Done when**: `app/core/auth_dependencies.py` is ≤50 lines and re-exports all 9 names.

---

## Phase 4: Verification of invariants

### T05 — Verify `app/core/di/__init__.py` is NOT modified

**Spec**: R01 (locked decision 3: no re-export from di `__init__.py`).
**Files**: `app/core/di/__init__.py` (no change).
**Steps**:
- Read `app/core/di/__init__.py` and confirm it does NOT contain any of the 9 auth-dependency names (`AuthenticatedUser`, `is_authenticated_user`, `get_insforge_client_dep`, `get_current_user_optional`, `return_early_if_response`, `require_authorized_user`, `require_writer_user`, `require_developer_user`, `require_developer_user_redirect`).
- Confirm the file still re-exports only `get_<slice>_port` providers from other slices (auth_di, catalogos_di, oauth_di).
**Verification**: `grep -E "AuthenticatedUser|is_authenticated_user|get_insforge_client_dep|get_current_user_optional|return_early_if_response|require_authorized_user|require_writer_user|require_developer_user|require_developer_user_redirect" app/core/di/__init__.py` returns zero matches.
**Done when**: `app/core/di/__init__.py` is untouched and does not re-export any auth-dependency symbol.

---

## Phase 5: Pin test

### T06 — Write `tests/test_auth_dependencies_slice.py` (7 atoms, gate corrections 1–3)

**Spec**: R04, R09; D§7 pin test design; gate corrections 1, 2, 3.
**Files**: `tests/test_auth_dependencies_slice.py` (create).
**Steps**:
- Create `tests/test_auth_dependencies_slice.py` with 7 test atoms:
  1. `test_di_module_exports_all_nine_symbols` — asserts the 9 names are in `dir(app.core.di.auth_dependencies_di)` and nothing else public.
  2. `test_shim_reexports_all_nine_symbols` — identity check: `app.core.auth_dependencies.<name> is app.core.di.auth_dependencies_di.<name>` for each of the 9; cites gate correction 1 (shim works for ~35 consumers transparently, not just 19).
  3. `test_di_module_has_no_raw_sql_or_execute_sql` — AST walk; asserts zero `execute_sql(` calls in the di module; cites `tests/test_catalogos_slice.py` and `tests/test_oauth_slice.py::test_di_layer_does_not_export_domain_or_port` as precedents.
  4. `test_require_authorized_user_catches_insforge_error_and_redirects` — monkeypatch `get_user_by_email` to raise `InsForgeError(503, "service unavailable")`; call `require_authorized_user`; assert returns `RedirectResponse` to `/unauthorized` 302; assert `log_safe` called with `event="auth.denied", reason="db_unreachable"`; assert `set_cached_auth.call_count == 0` (gate correction 2: cache must NOT be poisoned on InsForgeError).
  5. `test_di_module_nine_signatures_match_shim_byte_for_byte` — `inspect.signature` on each of the 9 names matches between shim and di module.
  6. `test_di_module_under_module_size_budget` — di module ≤700 lines (mirrors `check_module_size.py`).
  7. `test_shim_under_fifty_lines` — shim ≤50 lines.
- Precedents section at top of file: cites `tests/test_catalogos_slice.py` AND `tests/test_oauth_slice.py::test_di_layer_does_not_export_domain_or_port` (gate correction 3).
**Verification**: `python -m pytest tests/test_auth_dependencies_slice.py -v` passes all 7 atoms.
**Done when**: All 7 atoms green; atom 4 includes the negative `set_cached_auth` assertion and does NOT use `as exc` on the bare except.

---

## Phase 6: Regression checks

### T07 — Verify existing auth test files pass unchanged

**Spec**: R09; D§9 test plan.
**Files**: `tests/test_auth_dependencies.py`, `tests/test_auth_session_is_authorized.py` (no changes).
**Steps**:
- Run `python -m pytest tests/test_auth_dependencies.py tests/test_auth_session_is_authorized.py -v --tb=short` WITHOUT modifying either file.
- If any test fails, fix the shim or di module — NOT the test files.
**Verification**: Both test files pass completely.
**Done when**: Both test files pass without a single edit.

### T08 — Verify `app.dependency_overrides` keys still resolve via the shim

**Spec**: R09; gate correction 6.
**Files**: `tests/test_auth_dependencies.py`, `tests/test_auth_session_is_authorized.py` (read only).
**Steps**:
- Enumerate the exact override keys used in both files: `get_insforge_client` (imported from `app.main`), `get_insforge_client_dep` (from `app.core.auth_dependencies`), and `get_current_user_optional`.
- Verify each key resolves via the shim: `from app.core.auth_dependencies import get_insforge_client_dep, get_current_user_optional; print(get_insforge_client_dep is get_insforge_client_dep)` (identity).
- Confirm `get_insforge_client` (from `app.main`) is unchanged and still an override target.
**Verification**: `python -c "from app.core.auth_dependencies import get_insforge_client_dep, get_current_user_optional; print('OK')"` succeeds without error.
**Done when**: All three override keys (`get_insforge_client`, `get_insforge_client_dep`, `get_current_user_optional`) are importable from `app.core.auth_dependencies` and identity-check True.

---

## Phase 7: Documentation

### T09 — Refresh `docs/audits/auth-dependencies-audit-2026-Q2.md` addendum

**Spec**: R05; D§10 audit doc outline; gate correction 4.
**Files**: `docs/audits/auth-dependencies-audit-2026-Q2.md` (modify — append addendum).
**Steps**:
- Read the existing audit doc (237 lines).
- Append `## Slice #420-7 Addendum — 2026-08-05` section with: Scope, Methodology (including consumer count correction: ~35 total, gate correction 1), Findings severity table (CRITICAL §32.P4 + mitigation; INFO lazy-import cycle #226; INFO shim ≤50 lines; INFO AuthCacheBackend bypass), Verdict PASS.
- Gate correction 4: enumerate the 11 out-of-scope slices in the addendum's out-of-scope section: acogidas, adopciones, animals, cesiones, entradas, foster, materiales, salud, sanidad, tasks, voluntarios.
**Verification**: The appended addendum is present, dated 2026-08-05, and covers §32.P4 CRITICAL finding.
**Done when**: Audit doc has a dated addendum with scope, methodology, findings, verdict, and the 11 module slices explicitly listed.

---

## Phase 8: CI / quality gates

### T10 — Verify CI gates

**Spec**: R06; D§9 test plan.
**Steps**:
- Run in order: `ruff check .` → `python scripts/check_rules.py .` → `python -m mypy` → `python -m pytest -W error::DeprecationWarning tests/test_auth_dependencies_slice.py tests/test_auth_dependencies.py tests/test_auth_session_is_authorized.py` → `python -m build`.
- All must exit 0 (no failures).
**Verification**: All 5 commands pass.
**Done when**: All CI gates are green locally; diff is ≤400 lines.

### T11 — Verify module size budget

**Spec**: R07.
**Steps**:
- Run `python scripts/check_module_size.py` — di module must be ≤700 lines, shim ≤50 lines, no new BASELINE entry.
- Run `python scripts/check_route_size.py` — confirm no route handler regressed.
**Verification**: Both scripts exit 0.
**Done when**: `auth_dependencies_di.py` ≤700 lines; `auth_dependencies.py` ≤50 lines; no BASELINE entry added.

### T12 — Verify rule linter (Detectors 5/6/11/12)

**Spec**: R06, R08.
**Steps**:
- Run `python scripts/check_rules.py .` and inspect output.
- Detector 5 (`raw_logger_in_app`): verify the di module has zero `logger.*` calls (only `log_safe`).
- Detector 6 (`print_in_app`): verify the di module has zero `print()` calls.
- Detector 11 (`unjustified_lazy_import`): confirm the existing `# lazy-import:` markers in `app/core/config.py` and `app/core/auth_dependencies.py` (lazy-import of `get_user_by_email` inside the function) are preserved — do NOT remove them.
- Detector 12 (`cross_module_imports`): confirm no module under `app/modules/` imports directly from `app.core.di.auth_dependencies_di`; all consumers go through the shim at `app.core.auth_dependencies`.
**Verification**: `python scripts/check_rules.py .` exits 0 with no violations in the di module or shim.
**Done when**: All 4 detectors stay green; lazy-import markers are intact.

### T13 — Verify lazy-import cycle documentation

**Spec**: R08 (rule §26).
**Steps**:
- Confirm the lazy-import of `get_user_by_email` inside `require_authorized_user` in the di module carries the `# lazy-import: avoids circular import with app.core.auth` marker.
- Confirm `app/core/config.py`'s existing lazy-import marker is untouched.
**Verification**: `grep -n "lazy-import" app/core/di/auth_dependencies_di.py` finds the marker on the `from app.core.auth import get_user_by_email` line.
**Done when**: The `get_user_by_email` import in the di module carries the `lazy-import:` marker convention.

### T14 — Confirm 11 module slices are explicitly out of scope

**Spec**: R05 (gate correction 4); spec §3.
**Steps**:
- Verify the audit doc addendum (T09) lists the 11 slices: acogidas, adopciones, animals, cesiones, entradas, foster, materiales, salud, sanidad, tasks, voluntarios.
- Verify the design's out-of-scope section (§3 / §11 of design.md) similarly enumerates them.
**Verification**: `grep -E "acogidas|adopciones|animals|cesiones|entradas|foster|materiales|salud|sanidad|tasks|voluntarios" docs/audits/auth-dependencies-audit-2026-Q2.md` returns ≥11 matches.
**Done when**: The 11 module slices are explicitly enumerated in the audit doc addendum.
