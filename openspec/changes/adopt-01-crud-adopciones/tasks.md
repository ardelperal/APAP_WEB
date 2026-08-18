# Tasks: ADOPT-01 — Adopciones (CRUD)

skill_resolution: paths-injected

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 700-900 total (service ~250 + routes ~250 + templates ~300 + tests ~400 + SDD ~250 + migration ~5 + main.py ~3 + base.html ~2 + tests updates ~10) |
| 400-line budget risk | High (over 400 with tests) |
| Chained PRs recommended | No (pre-MVP single-branch per AGENTS.md §15.2; the project routinely accepts single feature commits in this range — see #41 INTAKE-03, #43 FOSTER-01, #65 CATALOG-01) |
| Delivery strategy | force-chained (pre-MVP single branch toward `main`) |
| Chain strategy | stacked-to-main toward `main` (pre-MVP) |
| Decision needed before apply | No |

## Phase 1: Migration + Service

- [x] 1.1 RED: add tests in `tests/test_adopciones.py` covering create/list/get/update/soft-delete, required-field validation (animal_id, fecha_adopcion, nombre_adoptante), FK checks (animal activo, voluntario activo per VOL-05), `search_adopciones_by_adoptante` (ILIKE case-insensitive), `is_active` derivado.
- [x] 1.2 GREEN: add migration `app/core/migration/sql/005_add_tipo_adopcion.sql` (idempotent ALTER TABLE adding `tipo_adopcion TEXT NOT NULL DEFAULT 'regular' CHECK (...)`). Wire `apply_sql_migrations` picks it up on next lifespan.
- [x] 1.3 GREEN: add `app/modules/adopciones/service.py` with `Adopcion` dataclass (frozen/slots, 14+ campos + `is_active` property), `AdopcionConflictError`, SQL constants, FK validation (animal_id activo, voluntario_seguimiento_id activo per VOL-05), `create_adopcion` / `list_adopciones` / `get_adopcion_by_id` / `update_adopcion` / `delete_adopcion` (atomic soft-delete) / `search_adopciones_by_adoptante`.
- [x] 1.4 REFACTOR: extract shared helpers; ensure service is framework-agnostic; verify `_validate_references` rejects inactive voluntario per VOL-05 (D-ADOPT-02).
- [x] 1.5 Verify: `pytest tests/test_adopciones.py`, `ruff check .`, `python -m build`, `python scripts/check_rules.py app`.

## Phase 2: Routes + Templates

- [x] 2.1 RED: create `tests/test_adopciones_routes.py` for auth guards (7 endpoints), service delegation, 404/422 handling, redirects, no `client.execute_sql(...)` in routes, CSRF token in forms, `?adoptante=` filter passthrough.
- [x] 2.2 GREEN: add `app/modules/adopciones/routes.py` with protected list/new/create/detail/edit/update/delete routes using `require_authorized_user` (NOT `require_writer_user` — key_user+ per #144).
- [x] 2.3 GREEN: add templates `app/templates/adopciones/list.html` (with `?adoptante=` filter), `form.html` (shared create/edit), `detail.html` with Spanish copy. Use `{% extends base_template %}` (no `"base.html"` literal — UA-based slices A/B/C merged).
- [x] 2.4 GREEN: wire router in `app/main.py` (`include_router(adopciones_router)`) and add "Adopciones" nav link in `app/templates/base.html` (mobile + desktop).
- [x] 2.5 Verify: `pytest tests/test_adopciones_routes.py`, `ruff check .`, `python -m build`, `python scripts/check_rules.py app`.

## Phase 3: Docs + Closeout

- [ ] 3.1 Update `docs/roadmap.md`: remove #47 row from §4, add to §5-bis closed list with SHA + commit, update `Última actualización`.
- [ ] 3.2 Close #47 with traceability comment per `github-issue-closure-traceability` (commit SHA + test path + P1 fidelity note).
- [ ] 3.3 Update `docs/architecture/decisiones-proyecto.md` if any decision in D-ADOPT-01..05 needs cross-project persistence.

## Implementation commits

| Commit | Work unit | SDD tasks | Verification | Access sync |
|---|---|---|---|---|
| _TBD_ | ADOPT-01 (migration + service + routes + templates + tests) | 1.1-3.2 | _TBD_ | N/A (InsForge is target; legacy `TbAdopcion` is read-only reference) |