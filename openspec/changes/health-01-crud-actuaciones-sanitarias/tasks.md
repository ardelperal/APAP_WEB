# Tasks: HEALTH-01 — Actuaciones Sanitarias (CRUD)

skill_resolution: paths-injected

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 2200-2800 total (service ~500 + routes ~400 + templates ~250 + tests ~1100 + SDD ~400 + domain.py ~40 + main.py ~3 + base.html ~2 + decisiones-proyecto ~30 + roadmap ~3) |
| 400-line budget risk | High (over 400 with tests) |
| Chained PRs recommended | No (pre-MVP single-branch per AGENTS.md §15.2; the project routinely accepts single feature commits in this range — see #47 ADOPT-01 with 3801 lines merged as a single PR) |
| Delivery strategy | force-chained (pre-MVP single branch toward `main`) |
| Chain strategy | stacked-to-main toward `main` (pre-MVP) |
| Decision needed before apply | No |

## Phase 1: Schema + Service (RED → GREEN → REFACTOR)

- [x] 1.1 RED: add tests in `tests/test_sanidad.py` covering create/list/get/update/soft-delete, required-field validation (animal_id, fecha), FK checks (animal activo, voluntario activo per VOL-05), D-24 validation (5 atoms: futura, malformada, anterior al alta, exención legacy, igual al alta), `search_actuaciones_by_animal`, `list_actuaciones_sanitarias` with optional `animal_id` filter, CTE TOCTOU.
- [x] 1.2 GREEN: add `ACTUACION_SANITARIA_CREATE_TABLE_SQL` constant to `app/core/domain.py` (10 columns + 3 audit) and wire `client.execute_sql(ACTUACION_SANITARIA_CREATE_TABLE_SQL)` at the end of `ensure_domain_schema`. Idempotent via `CREATE TABLE IF NOT EXISTS`.
- [x] 1.3 GREEN: add `app/modules/sanidad/__init__.py` (module marker) and `app/modules/sanidad/service.py` with `ActuacionSanitaria` dataclass (frozen/slots, 11 fields), `ActuacionSanitariaConflictError(ValueError)` (reserved), `_validate_fecha_d24(fecha)` helper (pure validation: format + future-date per D-24 reglas 1+2), SQL constants for INSERT/UPDATE/LIST/GET/DELETE + search, CTE for atomic FK + fecha_alta check (D-24 regla 3), `create_actuacion_sanitaria` / `list_actuaciones_sanitarias` / `get_actuacion_sanitaria_by_id` / `update_actuacion_sanitaria` / `delete_actuacion_sanitaria` (atomic soft-delete) / `search_actuaciones_by_animal`.
- [x] 1.4 RED-GREEN: extend `tests/test_domain.py` with `test_actuacion_sanitaria_create_table_sql_uses_if_not_exists`, `test_actuacion_sanitaria_create_table_sql_columns`, `test_actuacion_sanitaria_create_table_sql_fk_animal_id_to_animales`, `test_actuacion_sanitaria_create_table_sql_fk_tipo_actuacion_id_to_catalogos_pruebas`, `test_actuacion_sanitaria_create_table_sql_fk_voluntario_id_to_voluntarios`, `test_ensure_domain_schema_emits_actuacion_sanitaria_after_contratos`.
- [x] 1.5 REFACTOR: extract shared helpers if any duplication; verify `_validate_fecha_d24` raises with Spanish-friendly messages.
- [x] 1.6 Verify: `pytest tests/test_sanidad.py tests/test_domain.py -v`, `ruff check .`, `python -m build`, `python scripts/check_rules.py app`.

## Phase 2: Routes + Templates (RED → GREEN)

- [x] 2.1 RED: create `tests/test_sanidad_routes.py` for auth guards (7 endpoints), `require_writer_user` for 3 writes, service delegation, 404/422 handling, redirects, no `client.execute_sql(...)` in routes, CSRF token in forms, `?animal_id=` filter passthrough, D-24 sad path (form with invalid fecha → 422 with Spanish message).
- [x] 2.2 GREEN: add `app/modules/sanidad/routes.py` with 7 protected routes (list, new, create, detail, edit, update, delete) using `require_authorized_user` for reads and `require_writer_user` for writes (POST create / POST update / POST delete).
- [x] 2.3 GREEN: add templates `app/templates/sanidad/list.html` (with `?animal_id=` filter), `form.html` (shared create/edit with `tipo_actuacion` dropdown populated from `list_catalogos_pruebas`), `detail.html` with Spanish copy. Use `{% extends base_template %}` (no `"base.html"` literal — UA-based slices A/B/C merged).
- [x] 2.4 GREEN: wire router in `app/main.py` (`include_router(sanidad_router)`) and add "Actuaciones" nav link in `app/templates/base.html` (mobile + desktop).
- [x] 2.5 Verify: `pytest tests/test_sanidad_routes.py -v`, `ruff check .`, `python -m build`, `python scripts/check_rules.py app`.

## Phase 3: Docs + Closeout

- [ ] 3.1 Add D-24 to `docs/architecture/decisiones-proyecto.md` as a new section (formalizing the rule that was only referenced in `docs/roadmap.md`). Include: full text of the rule (3 sub-rules + legacy exemption), reference to `app/modules/sanidad/service.py::_validate_fecha_d24` and the CTE in `_INSERT_ACTUACION_SANITARIA_SQL`.
- [ ] 3.2 Update `docs/roadmap.md`: move #50 row from §4 (pending) to §5-bis (closed) with SHA + commit subject; update `Última actualización`.
- [ ] 3.3 Close #50 with traceability comment per `github-issue-closure-traceability` (commit SHA + test path + P1 fidelity note).
- [ ] 3.4 Save Engram observation with SDD key `health-01-crud-actuaciones-sanitarias`, commit SHAs, target branch, and verification evidence (per `sdd-commit-traceability`).

## Implementation commits

| Commit | Work unit | SDD tasks | Verification | Access sync |
|---|---|---|---|---|
| _TBD_ | HEALTH-01 (schema + service + routes + templates + tests + SDD + domain + main + base + decisiones + roadmap) | 1.1-3.4 | _TBD_ | N/A (LocalBackend is target; legacy `TbActuacionSanitaria` is read-only reference) |