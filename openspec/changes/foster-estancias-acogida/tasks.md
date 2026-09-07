# Tasks: FOSTER-02 — Estancias de Acogida

skill_resolution: paths-injected

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 1100-1500 total (with tests + SDD) |
| 400-line budget risk | High (over 400 — single PR per pre-MVP single-branch policy) |
| Chained PRs recommended | No (pre-MVP single-branch per AGENTS.md §15.2; precedent of #41 INTAKE-03 and #43 FOSTER-01 accepting single large commits) |
| Delivery strategy | force-chained (single PR) |
| Chain strategy | stacked-to-main toward `main` (pre-MVP) |
| Decision needed before apply | No |

## Phase 1: Schema + Service

- [ ] 1.1 RED: add tests in `tests/test_acogidas.py` covering create/list/get/update/close/delete, FK validation (animal, casa activa, voluntario activo), `compute_duracion`, `is_active`, sad validation per field, soft-delete, close semantics.
- [ ] 1.2 GREEN: add `ACOGIDAS_ADD_CASA_FK_SQL` constant to `app/core/domain.py` and call it from `ensure_domain_schema` AFTER `ACOGIDAS_CREATE_TABLE_SQL`. The `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` is idempotent.
- [ ] 1.3 GREEN: add `app/modules/acogidas/service.py` with `Acogida` dataclass (16 fields), `AcogidaConflictError`, SQL constants, validation (animal + fecha_inicio required; casa activa if present; voluntarios activos if present), CRUD API (`create_acogida`, `list_acogidas`, `get_acogida_by_id`, `update_acogida`, `close_acogida`, `delete_acogida`), and helpers (`compute_duracion`, `is_active`).
- [ ] 1.4 GREEN: add `app/modules/acogidas/__init__.py` re-exporting the public surface.
- [ ] 1.5 REFACTOR: extract shared helpers; ensure service is framework-agnostic.
- [ ] 1.6 Verify: `pytest tests/test_acogidas.py tests/test_domain.py`, `ruff check .`, `python -m build`.

## Phase 2: Routes + Templates

- [ ] 2.1 RED: create `tests/test_acogidas_routes.py` for auth guards (parametrized over 7 endpoints), service delegation, 404/422 handling, redirects, no `client.execute_sql(...)` in routes, CSRF token in forms.
- [ ] 2.2 GREEN: add `app/modules/acogidas/routes.py` with protected list/new/create/detail/edit/update/close/delete routes.
- [ ] 2.3 GREEN: add templates `app/templates/acogidas/list.html` (with `?activas_solo=1` filter), `form.html` (shared create/edit), `detail.html` (with `duracion` calculated) with Spanish copy.
- [ ] 2.4 GREEN: wire router in `app/main.py` (after `foster_router`) and `app/templates/base.html` ("Estancias de acogida" nav link between "Casas de acogida" and "Voluntarios").
- [ ] 2.5 Verify: `pytest tests/test_acogidas_routes.py`, `ruff check .`, `python -m build`.

## Phase 3: XSS audit + Closeout

- [ ] 3.1 Update `tests/test_xss_audit.py`: add `acogidas/list.html`, `acogidas/form.html`, `acogidas/detail.html` entries to `TEMPLATE_SPECS`; extend `handler_controlled` allowlist with `("acogidas/form.html", "form_action")` (mirror of the casas_acogida pattern).
- [ ] 3.2 Update `docs/roadmap.md`: remove #44 row from §4 (or move to ✅ with SHA), add to §5-bis closed list with SHA + commit, update `Última actualización` to 2026-07-04.
- [ ] 3.3 Close #44 with traceability comment per `github-issue-closure-traceability` (commit SHA + test path + P1 fidelity note + P1 fidelity: FK estructurada a casas_acogida y voluntarios activos en lugar de free-text legacy).
- [ ] 3.4 Final validation: full `pytest -W error::DeprecationWarning --ignore=tests/e2e --deselect tests/test_voluntarios_concurrent.py`, `ruff check .`, `python -m build`. Target 1207+ tests passed (1182 + 25 service + 15 routes = 1222 ideal; minimum 1207 if some tests merge).

## Implementation commits

| Commit | Work unit | SDD tasks | Verification | Access sync |
|---|---|---|---|---|
| _TBD_ | FOSTER-02 (schema + service + routes + templates + XSS) | 1.1-2.5 | _TBD_ | N/A (LocalBackend is target; legacy `TbAcogidaAnimal` is read-only reference) |
| _TBD_ | docs(roadmap) closeout | 3.2 | _TBD_ | N/A |
