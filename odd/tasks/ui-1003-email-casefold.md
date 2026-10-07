# Feature: UI-1003 — case-insensitive email lookup + normalized admin seed

Issue: ardelperal/APAP_WEB#1003 · Branch: `fix/1003-email-lookup-casefold`
Worktree: `/home/ubuntu/repos/apap-app-worktrees/1003-email-casefold` (from origin/main c5fbb89)

## Contracts (binding)

- Bug body: `GET_USER_BY_EMAIL_SQL` (`app/core/adapters/local_backend/auth_local_backend_queries.py:57` pre-fix, also duplicated in `app/core/local_backend/auth_queries.py:57`) was case-sensitive; seed (`app/core/application/auth/ensure_schema_and_seed.py:35` pre-fix) stored `settings.initial_admin_email` as-is. A mixed-case `APAP_INITIAL_ADMIN_EMAIL` (e.g. `Admin@Apap.Local`) saved the row in mixed case and the verify for `admin@apap.local` 302'd to `/unauthorized` — admin lockout by env typo.
- Convention: `auth_cache.py` already normalizes cache keys with `.lower()` (issue #278). The fix mirrors that convention on the DB lookup path AND at the seed boundary.
- Magic-link bypass: `app/core/local_backend/magic_link.py::_lookup_authorized_user` calls `port.get_user_by_email(email)` directly, NOT through the application-layer use case. The SQL must therefore be case-insensitive even though the use case normalizes — defense-in-depth (single-sided normalization would leave the magic-link bypass still broken).
- No schema/index change: rows are single-digit; `lower()` per row is acceptable. No citext migration, no functional index.
- No form / session / login-flow changes. The fix is bounded to email identity normalization at two boundaries.

## Tasks

- [x] T1 RED: add 3 tests to `tests/test_auth.py` (`test_get_user_by_email_uses_case_insensitive_where`, `test_ensure_schema_normalizes_initial_admin_email_to_lowercase`, `test_ensure_schema_seed_is_idempotent_under_mixed_case`); observe all 3 fail with the right reason (SQL shape substring absent / params not normalized).
- [x] T2 GREEN: change `GET_USER_BY_EMAIL_SQL` in BOTH `app/core/adapters/local_backend/auth_local_backend_queries.py` AND `app/core/local_backend/auth_queries.py` to `WHERE lower(email) = lower($1) AND activo = true`. Update the 2 adapter docstrings (`app/core/local_backend/auth_adapter.py`, `app/core/adapters/local_backend/auth_local_backend_adapter.py`) so they describe the case-insensitive WHERE truthfully. Normalize the seed via an inlined `_canonical_admin_email` helper in `app/core/application/auth/ensure_schema_and_seed.py` (single-line strip + lower) — inline avoids expanding the existing `application → auth_helpers` layer-purity baseline.
- [x] T3 Update `tests/conftest.py::auth_reval_rows` spy pattern: now matches BOTH `lower(email) = lower($1)` (new SQL) AND `email = $1` (legacy SQL for `_CHECK_DUPLICATE_EMAIL_SQL` exclusion). The 'rol' SELECT-column regex still gates the duplicate-check exclusion.
- [x] T4 Update existing test `test_get_user_by_email_returns_row_when_active` to assert the new SQL shape substring.
- [x] T5 Verification: `pytest tests/test_auth.py` 31 → 31 passed (3 new tests + 28 existing); `pytest tests/test_layers.py::test_current_tree_passes_with_baseline` green (no new layer violations); `ruff check` clean on all 7 touched files; `pytest tests/` fast scope (excluding integration/e2e/migration) green for the touched modules (2 pre-existing reader-403 failures in `test_voluntarios_role_routes.py` are not caused by this fix — same 2 fail on the base c5fbb89 with the changes stashed).
- [x] T6 Work-unit commit (no push): `fix(auth): case-insensitive email lookup and normalized admin seed` + body (admin lockout by case typo, both SQL copies fixed, inlined seed normalization respects layer-purity, Closes #1003).

## Evidence

| File:line | Status |
|---|---|
| `app/core/adapters/local_backend/auth_local_backend_queries.py:55-66` | fixed: `WHERE lower(email) = lower($1) AND activo = true` (case-insensitive WHERE) |
| `app/core/local_backend/auth_queries.py:55-66` | fixed: same case-insensitive WHERE (duplicate SQL consumed by the old `LocalBackendAuthUsersAdapter` that `magic_link._lookup_authorized_user` wires) |
| `app/core/application/auth/ensure_schema_and_seed.py:6-13, 38` | fixed: inlined `_canonical_admin_email` (strip + lower) applied to `settings.initial_admin_email` before passing to port; layer-purity preserved (no infra import added) |
| `app/core/local_backend/auth_adapter.py:87-104` | fixed: docstring corrected to describe the new case-insensitive WHERE truthfully |
| `app/core/adapters/local_backend/auth_local_backend_adapter.py:87-104` | fixed: same docstring correction in the newer adapter |
| `tests/conftest.py:81-98` | fixed: spy pattern now matches `lower(email) = lower($1)` OR `email = $1` (legacy), still gated by the 'rol' regex so `_CHECK_DUPLICATE_EMAIL_SQL` is excluded |
| `tests/test_auth.py:656-748` | 3 new tests + updated existing assertion at line 151 (`test_get_user_by_email_returns_row_when_active` now asserts the case-insensitive SQL substring) |
| `app/core/auth_cache.py:173/197/231` | unchanged — already normalizes cache keys via `.lower()` (precedent for the convention) |
| `app/core/auth_helpers.py:14` | unchanged — `normalize_email` exists; the ensure_schema use case inlines the same one-liner to avoid the cross-layer import |
| `app/core/local_backend/magic_link.py:222` | unchanged — `start_magic_link` already normalizes the input with `.strip().lower()`; the verify path's bypass of the application-layer use case is what the case-insensitive SQL guards against |
| `app/core/adapters/local_backend/auth_local_backend_queries.py:71-75` | unchanged — `_CHECK_DUPLICATE_EMAIL_SQL` keeps case-sensitive WHERE; out of scope (separate concern; admin add-user flow, not login) |
| `app/core/application/auth/get_user_by_email.py` | unchanged — already normalizes the input via `normalize_email`; the SQL case-insensitivity is the defense-in-depth for callers that bypass this use case |

## Out of scope (explicit non-changes)

- `_CHECK_DUPLICATE_EMAIL_SQL` — admin add-user duplicate check; out of scope for the login bug.
- `app/core/adapters/auth_local/classic_password_auth_port.py:35/41` — classic password (non-magic-link) path; out of scope.
- No new functional index. Rows are single-digit.
- No citext migration. Postgres default `TEXT` collation is fine; `lower()` per-row is cheap at this scale.
- No new BASELINE entry to `scripts/check_layers.py`. The seed normalization is inlined; the cross-layer `auth_helpers` import that the parent originally requested would have expanded the baselined debt (the existing `get_user_by_email → auth_helpers` entry is already baselined — adding a parallel one would be noise).
- No changes to `magic_link.py`, `auth_cache.py`, `auth_helpers.py`, `config.py`, `main.py`.

## Verification (measured)

- `pytest tests/test_auth.py -q` → 31 passed, 0 failed (3 new tests + 28 existing)
- `pytest tests/test_layers.py::test_current_tree_passes_with_baseline` → passed (layer-purity preserved)
- `pytest tests/test_voluntarios_role_routes.py` with my changes → 2 failed (pre-existing), 3 passed — same as base c5fbb89
- `pytest tests/ -q --ignore=tests/integration --ignore=tests/e2e --ignore=tests/e2e_ci --ignore=tests/migration` → 4461 passed, 16 skipped (no new failures)
- `ruff check` on the 7 touched files → All checks passed
- `git diff --stat` vs branch base c5fbb89 → 7 files, 160 insertions + 13 deletions = 173 net lines (well under 400)
- `git diff --shortstat origin/main..HEAD` → 777 lines of drift (origin/main is 30 commits ahead of c5fbb89; this is branch divergence, not my work)

## Risks

- Branch divergence: this branch is at c5fbb89; origin/main has moved 30 commits forward. The 173-line work-unit diff is correct against the branch base. Rebase onto origin/main before merge is a parent-side decision (not done here — no destructive git).
- The case-insensitive SQL adds one `lower()` evaluation per row. With single-digit user rows, this is negligible. If the table ever grows, a functional index `CREATE INDEX ... ON usuarios_autorizados (lower(email))` should be added.
- The conftest spy pattern now matches BOTH the new and legacy SQL shapes. If a future query also has `email = $1` AND a `rol` column, the spy will intercept it as a revalidation. The current SQL inventory has no such query — re-validate after any future SQL change in `auth_local_backend_queries.py` or `auth_queries.py`.

## Work-unit commit

- Commit: `fix(auth): case-insensitive email lookup and normalized admin seed`
- Body: admin lockout by `APAP_INITIAL_ADMIN_EMAIL` case typo; both SQL copies (`auth_local_backend_queries.py` + `local_backend/auth_queries.py`) now `WHERE lower(email) = lower($1)`; seed normalization inlined at the use case to preserve layer-purity (avoids expanding the baselined `application → auth_helpers` cross-layer debt); two adapter docstrings corrected to describe the new case-insensitive WHERE truthfully; conftest spy pattern updated to match the new SQL shape while preserving the `_CHECK_DUPLICATE_EMAIL_SQL` exclusion. Closes #1003.
