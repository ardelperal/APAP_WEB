# #1019 — Enforce role guards on `require_authorized_user`-only routes

## Goal

JD-B-002 (pre-existing WARNING, judgment-day #923 → epic #911). The `require_authorized_user` dep (`app/core/di/auth_dependencies_session_di.py`) re-reads `rol` from the DB on every request, but never rejects unknown role strings or the legacy `reader` role. Routes that depend on this dep alone are therefore reachable by readers and unknown-role users. Issue #1019 promotes this from an acknowledged gap to a required fix; the matrix-doc already declares those routes as outside the fail-closed guarantee and the issue closes that hole.

Scope: 200-350 lines per the issue body. WRITE path is the priority — `PATCH /adopciones/{id}/seguimiento` (`app/modules/adopciones/routes.py`) was reachable by reader/unknown; one test in the issue reproduces it. The remaining READ routes get a decision recorded per route, plus a guard test that fails if any future user-facing route lands without one.

## Acceptance criteria (from issue #1019)

- [ ] Every WRITE route passes through `require_permission` with the matrix-assigned permission.
- [ ] Every READ-only route has a recorded decision: `require_permission(<matrix read>` or an allowlist entry with rationale.
- [ ] A guard test fails if a user-facing route uses `require_authorized_user` without a recorded decision.

Refs #911, #923, #679.

## Per-route decision table

| # | Route | Method | Current guard | Decision | Rationale |
|---|-------|--------|---------------|----------|-----------|
| 1 | `/adopciones/{id}/seguimiento` | PATCH | `require_authorized_user` | **`require_permission(WRITE_ADOPCIONES)`** (code change in `app/modules/adopciones/routes.py`) | The issue priority: a state-transition WRITE that today any authorized user can hit. The matrix assigns `WRITE_ADOPCIONES` to admin/staff + the legacy writer roles (`DEVELOPER`/`KEY_USER`); reader, unknown, and `VOLUNTARIO` (no `WRITE_ADOPCIONES`) are denied. No new permission needed — `WRITE_ADOPCIONES` covers every adoption mutation including the seguimiento state machine. |
| 2 | `/animales/search` | GET | `require_authorized_user` | **`require_permission(READ_ANIMALES)`** (code change in `app/modules/animals/routes.py`) | Search returns the animales list; other animales reads already use `READ_ANIMALES`. Same scope, same permission — closure of the matrix gap. |
| 3 | `/animales/{id}/salud/resumen` | GET | `require_authorized_user` | **`require_permission(READ_SALUD)`** (code change in `app/modules/animals/routes.py`) | The resumen data is `actuacion_sanitaria`, which lives under the salud domain. Other sanidad reads already use `READ_SALUD`; the route file lives in `animals/` but the payload is salud. |
| 4 | `/acogidas/{id}/materiales` | GET | `require_authorized_user` | **`require_permission(READ_ACOGIDAS)`** (code change in `app/modules/materiales/acogida_routes.py`) | The parent resource is the `estancia` (acogida); the materials catalog lookup is a secondary view of the same estancia. The matrix assigns `READ_ACOGIDAS` to admin/staff + the legacy read roles, matching the writer/reader split used by the POST counterpart. |
| 5 | `/entradas/batch/new` | GET | `require_authorized_user` | **`require_permission(READ_ENTRADAS)`** (code change in `app/modules/entradas/batch_routes.py`) | The batch form is the entrada workflow; the POST counterpart uses `require_writer_user`. `READ_ENTRADAS` matches the matrix and closes the read-side gap for the same workflow. |
| 6 | `/tareas` and the rest of `/tareas/*` | GET / POST | `require_authorized_user` | **allowlist entry** (no code change — file `app/modules/tasks/routes.py` is outside the edit surfaces for this slice) | The tareas module has no entry in the `Permission` enum; today any authorized user (including `reader`) can use it. Adding a `READ_TAREAS` permission would be out of scope (#1019 does not list tareas as affected). The allowlist records the existing intentional posture: tareas is an internal workflow tracker accessible to every authorized operator; the unit-of-work sits with whoever opens the issue that introduces tareas permissions. Until then the audit test treats `/tareas/*` as a known exception with this rationale. |
| 7 | `/casas-acogida/{id}/asignar` (GET) | GET | `require_authorized_user` | **allowlist entry** (no code change) | This is the form-render pre-POST; the POST counterpart uses `require_writer_user`. The render form is read access to the casa + the underlying animal record; the matrix `READ_CASAS_ACOGIDA` is the natural permission but the form previews the gate's evaluations and lives outside the affected-list of #1019. Recorded here so the audit test does not regress on this route. |
| 8 | `/casas-acogida/{id}/overrides` | GET | `require_developer_user` | **no change** | Already gated by `require_developer_user` (FOSTER-03 #45 P1 risk-review fix). Out of scope for #1019. |

### Routes in the affected list that the matrix already covers

The other sanidad routes (`/sanidad`, `/sanidad/{id}`, `/sanidad/new`, `/sanidad/{id}/edit`, `/sanidad/batch/new`, `/sanidad/actuaciones/batch`) use `require_permission(READ_SALUD|WRITE_SALUD)` already and are out of scope for this audit. Their `Auth model` docstrings in `app/modules/sanidad/routes.py` and `app/modules/sanidad/batch_routes.py` still mention `require_authorized_user`; a separate slice can refresh those notes.

## Audit test design

`tests/test_rbac.py::test_require_authorized_user_only_routes_have_decision` iterates `app.routes` (the FastAPI route table), pulls the per-handler dependency tree, and asserts every user-facing route either:

- Uses `require_permission(<something>)` directly, OR
- Uses `require_writer_user` (which itself composes on `require_authorized_user` plus role gate), OR
- Is present in an explicit `_AUTHORIZED_USER_ONLY_ALLOWLIST` tuple with a rationale field.

The allowlist is module-level in `tests/test_rbac.py` (the audit file). Routes outside this set fail with a message naming the missing pair. The test runs with the standard `app` module-level instance and depends on the `_install_default_local_backend_client` autouse fixture so the `app.state.sql_executor` is wired.

## Verification contract

- `pytest tests/test_rbac.py tests/test_voluntarios_role_routes.py tests/test_auth.py -q` → green except the 2 documented pre-existing failures in `tests/test_voluntarios_role_routes.py` (investigate separately, do not mask).
- Fast suite scope (`pyproject addopts`) → no NEW failures vs base `093bb57`.
- `ruff check` on touched files; `scripts/check_route_size.py` OK; `scripts/check_ruff_ratchet.py` OK.
- `git diff --shortstat origin/main...HEAD` BEFORE push (target ≤ 400).

## Work-unit commits

- `fix(auth): enforce WRITE_ADOPCIONES on PATCH /adopciones/{id}/seguimiento` + tests RED→GREEN.
- `fix(auth): close read-side require_authorized_user gaps in animales/salud/materiales/entradas` + per-route tests.
- `test(rbac): add guard-matrix audit test for require_authorized_user-only routes` + allowlist entries.
- `docs(security): record #1019 closure and per-route decisions in rbac-matrix.md` (matrix update only when a row is missing).

## Status

- [ ] RED tests captured
- [ ] GREEN — code changes committed
- [ ] Audit test in place
- [ ] Docs updated
- [ ] Verification commands clean

## Fence decision (PR #1033 unblock)

The PR-diff `test` job still fails on pre-existing repo-wide reader-403 test rot that this PR does NOT cover. The PR scope fence is set on commit `4a9401b`:

- IN scope: `tests/test_voluntarios_routes.py::test_create_voluntario_rejects_reader_with_403` and `::test_deactivate_voluntario_rejects_reader_with_403` (and the sibling pattern in `tests/test_voluntarios_role_routes.py`). Fixed in `4a9401b`.
- OUT of scope: `tests/test_salud_routes.py::test_salud_write_routes_reject_reader_with_403` (6 parametrized cases) and any other reader-403 test in modules this PR does not touch. Same family (conftest default spy hardcodes `rol=key_user` for the auth reval), same shape, but lives in `tests/test_salud_routes.py` which is not in the #1019 PR's edit surfaces.

Family tracked in #1041. PR #1033 lands without waiting for the family-level fix.

<!-- odd:1019-role-guards-initial -->