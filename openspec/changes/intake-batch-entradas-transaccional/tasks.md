# Tasks: INTAKE-02 — Entradas Batch Transaccional

skill_resolution: paths-injected

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 350-500 total |
| 400-line budget risk | Medium (borderline) |
| Chained PRs recommended | No (single PR feasible si se mantiene lean) |
| Suggested split | Si pasa de 400: PR A schema+service+tests, PR B routes+templates |
| Delivery strategy | force-chained |
| Chain strategy | stacked-to-main toward `main` (pre-MVP) |
| Decision needed before apply | No |

## Phase 1: Schema + Service (#40 part A)

- [ ] 1.1 RED: add tests in `tests/test_entradas_batch.py` covering per-record validation, cross-batch uniqueness, atomic commit happy path, atomic rollback on mid-batch failure, and cleanup of staging.
- [ ] 1.2 GREEN: add `ENTRADAS_BATCH_STAGING_CREATE_TABLE_SQL` constant to `app/core/domain.py` and ensure `ensure_domain_schema` includes it; wire `entradas_batch_staging` into the `for sql in [...]: client.execute_sql(...)` loop in `ensure_domain_schema`.
- [ ] 1.3 GREEN: add `app/modules/entradas/batch_service.py` with public functions: `stage_batch(client, records) -> BatchStaging`, `commit_batch(client, batch_id) -> list[Entrada]`, `cancel_batch(client, batch_id) -> None`, `get_batch(client, batch_id) -> BatchStaging | None`. Implement cross-batch uniqueness check before any DB write.
- [ ] 1.4 REFACTOR: extract shared helpers; ensure service is framework-agnostic (no FastAPI imports); duplicate-error translation mirrors the INTAKE-01 `EntradaConflictError` pattern.
- [ ] 1.5 Verify: `pytest tests/test_entradas_batch.py`, `ruff check .`, `python -m build`.

## Phase 2: Routes + Templates (#40 part B)

- [ ] 2.1 RED: extend `tests/test_entradas_routes.py` (or create `tests/test_entradas_batch_routes.py`) for: auth guard, form rendering of batch/new, stage POST redirects to preview, commit POST redirects to /entradas, cancel DELETE redirects to batch/new, CSRF token present, no `client.execute_sql(...)` in routes.
- [ ] 2.2 GREEN: add batch routes to `app/modules/entradas/routes.py` (or a new `app/modules/entradas/batch_routes.py` mounted under the same router prefix `/entradas/batch`): `GET /entradas/batch/new`, `POST /entradas/batch`, `GET /entradas/batch/{batch_id}`, `POST /entradas/batch/{batch_id}/commit`, `DELETE /entradas/batch/{batch_id}`.
- [ ] 2.3 GREEN: add templates `app/templates/entradas/batch_new.html` (form with ≥5 rows + HTMX "Añadir fila"), `app/templates/entradas/batch_preview.html` (table with status per record + Confirmar/Cancelar).
- [ ] 2.4 GREEN: wire nav link in `app/templates/base.html` ("Entradas en lote") and ensure router is registered in `app/main.py`.
- [ ] 2.5 Verify: `pytest tests/test_entradas_routes.py tests/test_entradas_batch_routes.py`, `ruff check .`, `python -m build`, fresh-context review lens (R1 risk + R3 reliability).

## Phase 3: Docs + Closeout

- [ ] 3.1 Update `docs/roadmap.md`: remove #40 row from §4, add to §5-bis closed list with SHA + commit, update `Última actualización`.
- [ ] 3.2 Close #40 with traceability comment per `github-issue-closure-traceability` (commit SHA + test path + P1 fidelity note).

## Implementation commits

| Commit | Work unit | SDD tasks | Verification | Access sync |
|---|---|---|---|---|
| _TBD_ | INTAKE-02 batch slice (single chained PR, pre-MVP single-branch) | 1.1-2.5 | `pytest` 1041 passed, 1 skipped (psycopg module missing for migration_004 only), 2 deselected (`test_voluntarios_concurrent.py`); `ruff check .` clean; `python -m build` OK | N/A (InsForge is target; no Access binary write) |