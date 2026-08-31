# APAP_WEB Test Audit

> Generated 2026-08-31 by `gentle-ai-explore` subagent (read-only audit of `tests/`).
> ~265 test files classified by type, mocks used, determinism, speed, and recommendation.

## Summary

- **Total test files**: ~265 (`tests/test_*.py` ≈ 208 + `tests/integration/` 5 + `tests/migration/` 25 + `tests/e2e/` 27)
- **Classification breakdown**:
  - **Unit** (pure builders / domain / application-layer stubs): ~95 files — fast, deterministic, no transport.
  - **Service-layer unit w/ httpx.MockTransport** (real `InsForgeClient` over an in-process `httpx.MockTransport`): ~25 files — deterministic, fast, asserts SQL wire-shape, not real DB behaviour.
  - **Route integration (in-process ASGI)** (httpx ASGITransport + a `_NoSqlRouteClient` / `_AnimalsRouteSpy`): ~25 files — gates "no SQL in routes" + auth/CSRF contract; mocked SQL.
  - **Integration (real Postgres)**: 5 files under `tests/integration/`, excluded by default — exercised in a dedicated CI job via `APAP_TEST_POSTGRES_DSN`.
  - **Migration ETL (FakeInsForge + Dysflow executor seam)**: ~25 files under `tests/migration/` — run in default suite, hermetic.
  - **E2E (Playwright)**: ~27 files under `tests/e2e/` — excluded by default, exercised in dedicated CI job.
  - **Meta / process / rule tests** (~70 files): test the linter, the layer-checker, coverage gate, the docstring gate, ruff ratchet, branch-name policy, etc.
- **Determinism**: ~99 % deterministic. No real-time-of-day, no `time.sleep`, no shared global state.
- **Speed (default `pytest` run)**: dominated by ~250+ unit files; order of magnitude: full default suite ~ tens of seconds; integration suite ~ tens of seconds per file; E2E ~ minutes.
- **Critical gaps** (areas with no integration / E2E coverage):
  1. **Auth revalidation round-trip against a real DB** — `test_auth.py` uses `httpx.MockTransport`; no integration atom for "INSERT user, mark inactive, hit protected route, observe 302 → /unauthorized."
  2. **Cascade / FK delete paths** — chip cascade, animal soft-delete cascade are unit-tested (no SQL on the cascade path).
  3. **CSRF middleware + live Postgres session lifecycle** — no end-to-end test that the CSRF token round-trips through a real session against a real DB.
  4. **Rate-limit middleware with concurrent requests** — unit-level only.
  5. **Migration ETL against a real `.accdb`** — by design, never tested here.
  6. **Public read-only API** — rate-limit / abuse paths not exercised.
  7. **`Coolify` webhook** — validation covered; not exercised E2E.

## Per-file classification

| File | Type | Mocks | Deterministic | Speed | Recommendation |
|---|---|---|---|---|---|
| `tests/__init__.py` | n/a | – | – | – | keep |
| `tests/conftest.py` | fixture | default spy + auth-reval seam | yes | fast | keep — already a multi-purpose seam; doc the `auth_reval_rows` contract more visibly |
| `tests/integration/__init__.py`, `tests/migration/__init__.py` | n/a | – | – | – | keep |
| `tests/integration/conftest.py` | fixture | real Postgres ephemeral schema | yes (modulo CI) | medium | keep — **only** place that exercises real SQL semantics |
| `tests/migration/conftest.py` | fixture + `FakeInsForge` | fake InsForge + Dysflow executor | yes | fast | keep |
| `tests/e2e/conftest.py` | fixture | Playwright browser; live server | yes (modulo network) | slow | keep |
| `tests/test_acogidas.py` | service unit | `httpx.MockTransport` | yes | fast | keep |
| `tests/test_acogidas_detail.py` | service unit | `httpx.MockTransport` | yes | fast | keep |
| `tests/test_acogidas_lifecycle_events.py` | service unit w/ `FakeSqlExecutor` | fake `SqlExecutor` | yes | fast | keep |
| `tests/test_acogidas_queries.py` | builder unit | none (pure functions) | yes | fast | keep |
| `tests/test_acogidas_routes.py` | route integration | `_NoSqlRouteClient` spy + `_DefaultInsForgeSpy` from conftest | yes | fast | keep |
| `tests/test_admin.py` | route integration | reval-only spy | yes | fast | keep |
| `tests/test_admin_handler_sync.py` | route unit | n/a | yes | fast | keep |
| `tests/test_admin_slice.py` | route unit | n/a | yes | fast | keep |
| `tests/test_adopciones.py` | service unit | `httpx.MockTransport` | yes | fast | keep |
| `tests/test_adopciones_lifecycle_events.py` | service unit | `FakeSqlExecutor` | yes | fast | keep |
| `tests/test_adopciones_queries.py` | builder unit | none | yes | fast | keep |
| `tests/test_adopciones_routes.py` | route integration | `_NoSqlRouteClient` spy | yes | fast | keep |
| `tests/test_adoption_state_machine.py` | domain unit | `FakeSqlExecutor` | yes | fast | keep |
| `tests/test_agents_md_section_23.py` | meta | none | yes | fast | keep |
| `tests/test_all_post_forms_have_csrf_input.py` | meta (Jinja scan) | none | yes | fast | keep — strong gate |
| `tests/test_animal_search.py` | application | stub port | yes | fast | keep |
| `tests/test_animals_application_change_animal_chip.py` | application | `_StubPort` | yes | fast | keep |
| `tests/test_animals_application_create_animal.py` | application | `_StubPort` | yes | fast | keep |
| `tests/test_animals_application_delete_animal.py` | application | `_StubPort` | yes | fast | keep |
| `tests/test_animals_application_get_animal_by_id.py` | application | `_StubPort` | yes | fast | keep |
| `tests/test_animals_application_get_animal_by_nchip.py` | application | `_StubPort` | yes | fast | keep |
| `tests/test_animals_application_list_animals.py` | application | `_StubPort` | yes | fast | keep |
| `tests/test_animals_application_list_lifecycle_events.py` | application | `_StubPort` | yes | fast | keep |
| `tests/test_animals_application_record_lifecycle_event.py` | application | `_StubPort` | yes | fast | keep |
| `tests/test_animals_application_resolve_animal_photo.py` | application | `_StubPort` + fake photo stream | yes | fast | keep |
| `tests/test_animals_application_search_animals.py` | application | `_StubPort` | yes | fast | keep |
| `tests/test_animals_application_update_animal.py` | application | `_StubPort` | yes | fast | keep |
| `tests/test_animals_domain.py` | domain unit | none | yes | fast | keep |
| `tests/test_animals_foto_route.py` | route integration | spy | yes | fast | keep |
| `tests/test_animals_insforge_adapter.py` | adapter unit | `_FakeClient` / `_SequencedFakeClient` / `_FakePhotoClient` | yes | fast | keep |
| `tests/test_animals_port.py` | port unit | stub | yes | fast | keep |
| `tests/test_animals_public_api.py` | route integration | spy | yes | fast | keep — extend with rate-limit assertion |
| `tests/test_animals_routes.py` | route integration | `_AnimalsRouteSpy` | yes | fast | keep |
| `tests/test_animals_routes_redirects.py` | route integration | spy | yes | fast | keep |
| `tests/test_apap003.py`, `tests/test_apap004_user_any.py` | meta | n/a | yes | fast | keep — pin the plugin rules |
| `tests/test_app.py` | app boot unit | depends on default spy | yes | fast | keep |
| `tests/test_auth.py` | service unit | `httpx.MockTransport` | yes | fast | keep — **extend** with integration atom |
| `tests/test_auth_cache.py` | unit | none | yes | fast | keep |
| `tests/test_auth_cache_backend.py` | unit | none | yes | fast | keep |
| `tests/test_auth_dependencies.py` | dependency unit | none | yes | fast | keep |
| `tests/test_auth_dependencies_slice.py` | meta | none | yes | fast | keep |
| `tests/test_auth_flow.py` | route integration | `_FakeInsForge` (in-process) | yes | fast | keep — OAuth endpoint faked, real `accounts.google.com` not exercised |
| `tests/test_auth_helpers.py` | unit | none | yes | fast | keep |
| `tests/test_auth_session_is_authorized.py` | unit | none | yes | fast | keep |
| `tests/test_catalogos_slice.py` | meta | none | yes | fast | keep |
| `tests/test_catalogs.py` | unit | `httpx.MockTransport` | yes | fast | keep |
| `tests/test_cesiones.py` | service unit | `httpx.MockTransport` | yes | fast | keep |
| `tests/test_cesiones_adapter.py` | adapter unit | fake client | yes | fast | keep |
| `tests/test_cesiones_routes.py` | route integration | `_NoSqlRouteClient`-style spy | yes | fast | keep |
| `tests/test_check_alantyle.py` | meta | n/a | yes | fast | keep |
| `tests/test_check_branch_name.py` | meta | n/a | yes | fast | keep |
| `tests/test_check_complexity.py` | meta | n/a | yes | fast | keep |
| `tests/test_check_crap.py` | meta | n/a | yes | fast | keep |
| `tests/test_check_jscpd.py` | meta | n/a | yes | fast | keep |
| `tests/test_check_mutation.py` | meta | n/a | yes | fast | keep |
| `tests/test_check_mutation_sites.py` | meta | n/a | yes | fast | keep |
| `tests/test_check_rules.py` | meta | n/a | yes | fast | keep |
| `tests/test_check_rules_exclusion.py` | meta | n/a | yes | fast | keep |
| `tests/test_check_spec_drift.py` | meta | n/a | yes | fast | keep |
| `tests/test_check_vulture_guard.py` | meta | n/a | yes | fast | keep |
| `tests/test_check_workflows.py` | meta | n/a | yes | fast | keep |
| `tests/test_chip_cascade.py` | adapter unit | fake client | yes | fast | keep — **extend** with integration atom (FK cascade) |
| `tests/test_ci_workflow.py` | meta | workflow YAML scan | yes | fast | keep |
| `tests/test_config.py` | config unit | env monkeypatch | yes | fast | keep |
| `tests/test_coolify_webhook.py` | route unit | spy | yes | fast | keep — **extend** with signed-payload happy path |
| `tests/test_cosmic_ray_run_config.py` | meta | n/a | yes | fast | keep |
| `tests/test_coverage_gate.py` | meta (pytest plugin) | `pytester` subprocess | yes (modulo subprocess) | medium | keep |
| `tests/test_crap_refactor_helpers.py` | meta | n/a | yes | fast | keep |
| `tests/test_critical_helpers_have_full_coverage.py` | meta | coverage JSON | yes | fast | keep |
| `tests/test_csrf_form_enumeration.py` | meta (Jinja scan) | none | yes | fast | keep |
| `tests/test_csrf_middleware.py` | middleware integration | `_AnonymousSpy` | yes | fast | keep — **add** E2E with real session |
| `tests/test_csrf_rejected_log_event.py` | middleware integration | spy | yes | fast | keep |
| `tests/test_derivation.py`, `tests/test_derivation_11cases.py` | domain unit | builder only | yes | fast | keep |
| `tests/test_dev_dependencies.py` | meta | n/a | yes | fast | keep |
| `tests/test_dockerfile.py` | meta | n/a | yes | fast | keep |
| `tests/test_docstring_coverage.py` | meta | n/a | yes | fast | keep |
| `tests/test_domain.py`, `tests/test_domain_*.py` | domain unit | none / pure functions | yes | fast | keep |
| `tests/test_e2e_auth.py` | route integration (in-process) | `_FakeInsForge` | yes | fast | keep |
| `tests/test_entradas.py` | service unit | `httpx.MockTransport` | yes | fast | keep |
| `tests/test_entradas_batch.py` | service unit | `httpx.MockTransport` w/ staged handler | yes | fast | keep |
| `tests/test_entradas_batch_routes.py` | route integration | spy | yes | fast | keep |
| `tests/test_entradas_routes.py` | route integration | spy | yes | fast | keep |
| `tests/test_entradas_shared_helpers.py` | unit | none | yes | fast | keep |
| `tests/test_estado_actual_animal_schema.py` | schema unit | `httpx.MockTransport` | yes | fast | keep — **add** integration atom |
| `tests/test_execute_sql_shape.py` | unit | none | yes | fast | keep |
| `tests/test_form_helpers.py` | unit | none | yes | fast | keep |
| `tests/test_foster.py` | service unit | `httpx.MockTransport` | yes | fast | keep |
| `tests/test_foster_assignment.py` | service unit | `httpx.MockTransport` | yes | fast | keep |
| `tests/test_foster_assignment_routes.py` | route integration | spy | yes | fast | keep |
| `tests/test_foster_routes.py` | route integration | spy | yes | fast | keep |
| `tests/test_gate_output_encoding.py` | meta | n/a | yes | fast | keep |
| `tests/test_git_hooks.py` | meta | subprocess | yes | medium | keep |
| `tests/test_health_catalog.py` | meta | n/a | yes | fast | keep |
| `tests/test_import_cycles.py` | meta | n/a | yes | fast | keep |
| `tests/test_insforge.py` | client unit | `httpx.MockTransport` | yes | fast | keep |
| `tests/test_insforge_error_handler.py` | unit | none | yes | fast | keep |
| `tests/test_layers.py` | meta | filesystem scan | yes | fast | keep |
| `tests/test_lifecycle_*.py` (8 files) | service unit | `FakeSqlExecutor` | yes | fast | keep — **add** integration atom for the append-only trigger |
| `tests/test_lifespan.py` | boot unit | spy | yes | fast | keep |
| `tests/test_log_*.py` (4 files) | unit | none / fake logger | yes | fast | keep |
| `tests/test_logout_contract.py` | contract unit | n/a | yes | fast | keep |
| `tests/test_make_csrf_request.py` | helper unit | n/a | yes | fast | keep |
| `tests/test_materiales.py` | service unit | `httpx.MockTransport` | yes | fast | keep |
| `tests/test_materiales_queries.py` | builder unit | none | yes | fast | keep |
| `tests/test_materiales_routes.py` | route integration | spy | yes | fast | keep |
| `tests/test_materiales_service_split.py` | meta | n/a | yes | fast | keep |
| `tests/test_measure_mutation_parallelism.py` | meta | n/a | yes | fast | keep |
| `tests/test_middleware.py`, `test_middleware_*.py`, `test_security_headers_middleware.py`, `test_rate_limit_middleware.py` | middleware unit / route integration | spy | yes | fast | keep |
| `tests/test_migration.py`, `test_migration_004.py`, `test_migration_boundaries.py`, `test_migration_cli.py` | migration unit | `FakeInsForge` / Dysflow seam | yes | fast | keep |
| `tests/test_module_size.py`, `test_route_size.py`, `test_route_layer_coverage.py`, `test_routes_registry.py` | meta (AST scan) | n/a | yes | fast | keep |
| `tests/test_oauth_slice.py` | route integration | fake | yes | fast | keep |
| `tests/test_packaging.py`, `test_pr_size.py`, `test_pr4b_artifact_atom_counts.py` | meta | n/a | yes | fast | keep |
| `tests/test_pages.py` | route integration | `_RevalOnlySpy` | yes | fast | keep |
| `tests/test_perf.py` | meta | n/a | yes | fast | keep |
| `tests/test_pii_audit_doc.py` | meta (doc scan) | n/a | yes | fast | keep |
| `tests/test_public_paths.py` | route integration | reval spy | yes | fast | keep |
| `tests/test_rbac.py`, `test_roles_enum.py` | unit | none | yes | fast | keep |
| `tests/test_reconcile.py`, `test_reconcile_pr5_followups.py` | migration unit | `FakeInsForge` | yes | fast | keep |
| `tests/test_repository_secrets_ignore.py` | meta | n/a | yes | fast | keep |
| `tests/test_roundtrip.py` | migration unit | `FakeInsForge` + injected executor | yes | fast | keep |
| `tests/test_ruff_apap001.py`, `test_ruff_ratchet.py` | meta | n/a | yes | fast | keep |
| `tests/test_rule_7_compliance.py` | meta | n/a | yes | fast | keep |
| `tests/test_runbook_links.py` | meta (doc scan) | n/a | yes | fast | keep |
| `tests/test_salud.py`, `test_salud_queries.py`, `test_salud_routes.py` | service + builder + route | `httpx.MockTransport` / spy | yes | fast | keep |
| `tests/test_sanidad.py`, `test_sanidad_batch.py`, `test_sanidad_periodicity.py`, `tests/test_sanidad_queries.py`, `tests/test_sanidad_routes.py` | service + builder + route | `httpx.MockTransport` / spy | yes | fast | keep |
| `tests/test_schema_bootstrap.py` | schema unit | `httpx.MockTransport` | yes | fast | keep |
| `tests/test_security_scanning.py` | meta (workflow scan) | n/a | yes | fast | keep |
| `tests/test_semantic_events.py` | service unit | `FakeSqlExecutor` | yes | fast | keep |
| `tests/test_session.py`, `test_session_rotation.py` | unit | none | yes | fast | keep |
| `tests/test_shadow_state.py` | migration unit | `FakeInsForge` | yes | fast | keep |
| `tests/test_slice_completeness.py`, `test_slice_insforge_error_handler.py`, `tests/test_catalogos_slice.py`, `tests/test_admin_slice.py`, `tests/test_layers.py` | meta | n/a | yes | fast | keep |
| `tests/test_smoke.py` | unit | none | yes | fast | keep (deprecation-warning guard) |
| `tests/test_sql_executor_protocol.py`, `test_sql_runner.py` | unit | none | yes | fast | keep |
| `tests/test_startup_config_validation.py` | config unit | env | yes | fast | keep |
| `tests/test_tasks.py` | unit | none | yes | fast | keep |
| `tests/test_template_migration.py`, `tests/test_template_selection.py` | meta (template scan) | n/a | yes | fast | keep |
| `tests/test_ua.py` | route integration | reval spy | yes | fast | keep |
| `tests/test_voluntarios_*.py` (~12 files) | service + application + routes | `httpx.MockTransport` / stub port / spy | yes | fast | keep |
| `tests/test_volunteer_fk_migration.py` | migration unit | `FakeInsForge` | yes | fast | keep |
| `tests/test_xss_audit.py`, `tests/test_xss_audit_greps.py`, `tests/test_xss_audit_handlers.py` | meta (handler / pattern scan) | n/a / handler-level | yes | fast | keep |
| `tests/integration/test_acogidas_queries_integration.py` | integration (real Postgres) | none | yes (modulo CI) | medium | keep — **extend** to FK-error and unique-constraint paths |
| `tests/integration/test_adopciones_queries_integration.py` | integration | none | yes | medium | keep |
| `tests/integration/test_materiales_queries_integration.py` | integration | none | yes | medium | keep |
| `tests/integration/test_salud_queries_integration.py` | integration | none | yes | medium | keep |
| `tests/integration/test_sanidad_queries_integration.py` | integration | none | yes | medium | keep |
| `tests/migration/test_apply.py` | migration unit | `FakeInsForge` | yes | fast | keep |
| `tests/migration/test_apply_safety.py` | migration unit | `FakeInsForge` + psutil seam | yes | fast | keep |
| `tests/migration/test_apply_voluntarios_fk.py` | migration unit | `FakeInsForge` | yes | fast | keep |
| `tests/migration/test_bootstrap.py` | migration unit | `FakeInsForge` | yes | fast | keep |
| `tests/migration/test_bucket_invariant.py` | migration unit | `FakeInsForge` | yes | fast | keep |
| `tests/migration/test_cli.py` | CLI unit | `FakeInsForge` + Dysflow seam | yes | fast | keep |
| `tests/migration/test_cli_apply_safety.py` | CLI unit | `FakeInsForge` | yes | fast | keep |
| `tests/migration/test_cli_volunteer_dedup.py` | CLI unit | `FakeInsForge` | yes | fast | keep |
| `tests/migration/test_dni_collision.py` | migration unit | `FakeInsForge` | yes | fast | keep |
| `tests/migration/test_dni_collision_counting.py` | migration unit | `FakeInsForge` | yes | fast | keep |
| `tests/migration/test_insforge_storage_methods.py` | migration unit | `FakeInsForge` | yes | fast | keep |
| `tests/migration/test_legacy_write_commit.py` | migration unit | `FakeInsForge` + executor seam | yes | fast | keep |
| `tests/migration/test_lock_snapshot.py` | migration unit | `FakeInsForge` + lock seam | yes | fast | keep |
| `tests/migration/test_module_rename_smoke.py` | migration unit | `FakeInsForge` | yes | fast | keep |
| `tests/migration/test_photo_storage.py` | migration unit | `FakeInsForge` | yes | fast | keep |
| `tests/migration/test_pii_redaction.py` | migration unit | `FakeInsForge` | yes | fast | keep |
| `tests/migration/test_pii_value_patterns.py` | migration unit | `FakeInsForge` | yes | fast | keep |
| `tests/migration/test_reporting.py` | migration unit | `FakeInsForge` | yes | fast | keep |
| `tests/migration/test_reverse_apply.py` | migration unit | `FakeInsForge` | yes | fast | keep |
| `tests/migration/test_round_trip.py` | migration unit | `FakeInsForge` + read+write executor | yes | fast | keep |
| `tests/migration/test_runtime_boundary.py` | migration unit | `FakeInsForge` | yes | fast | keep |
| `tests/migration/test_s608_identifier_guards.py` | migration unit | `FakeInsForge` | yes | fast | keep |
| `tests/migration/test_shadow_state.py` | migration unit | `FakeInsForge` | yes | fast | keep |
| `tests/migration/test_storage_contract_evidence.py` | migration unit | `FakeInsForge` | yes | fast | keep |
| `tests/migration/test_volunteer_dedup.py` | migration unit | `FakeInsForge` | yes | fast | keep |
| `tests/e2e/test_acogidas_crud.py` | e2e | live server + InsForge | yes | slow | keep |
| `tests/e2e/test_admin_authenticated.py` | e2e | live + OAuth mock | yes | slow | keep |
| `tests/e2e/test_adopciones_crud.py`, `test_adopciones_seguimiento.py` | e2e | live | yes | slow | keep |
| `tests/e2e/test_animales_crud.py` | e2e | live | yes | slow | keep |
| `tests/e2e/test_casas_acogida_asignar.py`, `test_casas_acogida_crud.py` | e2e | live | yes | slow | keep |
| `tests/e2e/test_cesiones_auth.py`, `test_cesiones_conflicts.py`, `test_cesiones_crud.py` | e2e | live | yes | slow | keep |
| `tests/e2e/test_entradas_batch.py`, `test_entradas_crud.py` | e2e | live | yes | slow | keep |
| `tests/e2e/test_landing.py` | e2e | live (skips when OAuth 503) | yes | slow | keep |
| `tests/e2e/test_layout_responsive_extended.py`, `test_nav_layout.py` | e2e | live | yes | slow | keep |
| `tests/e2e/test_login_form.py` | e2e | live | yes | slow | keep |
| `tests/e2e/test_logout.py` | e2e | live | yes | slow | keep |
| `tests/e2e/test_materiales_crud.py` | e2e | live | yes | slow | keep |
| `tests/e2e/test_public_redirects.py` | e2e | live | yes | slow | keep |
| `tests/e2e/test_salud_terapias.py` | e2e | live | yes | slow | keep |
| `tests/e2e/test_sanidad_5tipos.py`, `test_sanidad_auth.py`, `test_sanidad_crud.py`, `test_sanidad_date_validation.py`, `test_sanidad_no_duplicates.py` | e2e | live | yes | slow | keep |
| `tests/e2e/test_security_headers.py` | e2e | live | yes | slow | keep |
| `tests/e2e/test_voluntarios_crud.py`, `test_voluntarios_roles.py` | e2e | live | yes | slow | keep |

## Per-module coverage map

### `sanidad` (`app/modules/sanidad/`)
- **Covered by**: `test_sanidad.py` (service unit w/ MockTransport), `test_sanidad_batch.py` (atomic commit), `test_sanidad_periodicity.py`, `test_sanidad_queries.py` (builder), `test_sanidad_routes.py` (route integration), `test_salud.py` + `test_salud_routes.py` + `test_salud_queries.py`, `tests/integration/test_sanidad_queries_integration.py`, `tests/integration/test_salud_queries_integration.py`, 5 E2E files.
- **What is mocked**: SQL is mocked at every layer below the route. The atomic commit guarantee is unit-tested with a custom `_handler_cascading` that returns error responses mid-batch; **integration does not assert that the CTE truly rolls back the partial state on a real Postgres failure**.
- **Gaps**:
  - **Real CTE rollback path**: when one of the per-record validations fails at the DB layer (unique `(animal_id, fecha, tipo_actuacion)`), no integration atom asserts rollback.
  - **D-24 date validation**: tested at the builder level, but not at the route level with a foreign-session attack.

### `animals` (`app/modules/animals/`)
- **Covered by**: 11 `test_animals_application_*.py` (port-stub layer), `test_animals_insforge_adapter.py`, `test_animals_domain.py`, `test_animals_port.py`, `test_animals_routes.py` / `_redirects` / `_foto_route`, `test_animals_public_api.py`, `test_chip_cascade.py`, `test_animal_search.py`, `tests/e2e/test_animales_crud.py`.
- **Gaps**:
  - **Public search rate-limit**: no 429 path tested against `/animales/search`.
  - **Photo bucket private-vs-public invariant** not asserted at the animales slice boundary (only at migration slice).

### `entradas` (`app/modules/entradas/`)
- **Covered by**: `test_entradas.py`, `test_entradas_batch.py`, `test_entradas_routes.py`, `test_entradas_batch_routes.py`, `test_entradas_shared_helpers.py`, E2E `test_entradas_batch.py` + `test_entradas_crud.py`.
- **Gaps**:
  - **No `tests/integration/test_entradas_queries_integration.py`**. The entradas batch CTE is one of the most transactionally complex flows; only ever exercised against MockTransport + staged E2E.

### `adopciones` (`app/modules/adopciones/`)
- **Covered by**: `test_adopciones.py`, `test_adopciones_lifecycle_events.py`, `test_adopciones_queries.py`, `test_adoption_state_machine.py`, `test_adopciones_routes.py`, `tests/integration/test_adopciones_queries_integration.py`, E2E `test_adopciones_crud.py` + `test_adopciones_seguimiento.py`.
- **Gaps**:
  - **State-machine failure paths** (decline-after-approval cascade) tested only with `FakeSqlExecutor`.

### `acogidas` / `foster`
- **Covered by**: `test_acogidas.py`, `test_acogidas_detail.py`, `test_acogidas_lifecycle_events.py`, `test_acogidas_queries.py`, `test_acogidas_routes.py`, `test_foster.py`, `test_foster_assignment.py`, `test_foster_routes.py`, `test_foster_assignment_routes.py`, `tests/integration/test_acogidas_queries_integration.py`, E2E `test_acogidas_crud.py`, `test_casas_acogida_asignar.py`, `test_casas_acogida_crud.py`.
- **Gaps**:
  - **Foster capacity override + estancia FK chain** not asserted against real DB.
  - **Stay-close cascade**: no integration atom against real Postgres trigger for `animal_lifecycle_events` append-only.

### `materiales` (`app/modules/materiales/`)
- **Covered by**: `test_materiales.py`, `test_materiales_queries.py`, `test_materiales_routes.py`, `test_materiales_service_split.py`, `tests/integration/test_materiales_queries_integration.py`, E2E `test_materiales_crud.py`.
- **Relatively healthy**. Integration atom covers the unique-active-index.

### `cesiones` (`app/modules/cesiones/`)
- **Covered by**: `test_cesiones.py`, `test_cesiones_adapter.py`, `test_cesiones_routes.py`, E2E `test_cesiones_crud.py` + `test_cesiones_conflicts.py` + `test_cesiones_auth.py`.
- **Gaps**:
  - **No `tests/integration/test_cesiones_queries_integration.py`**. Conflict resolution tested only at the route layer with a spy. ✅ Closed 2026-08-31 via PR closing #633. Three atoms landed against real Postgres: UNIQUE rollback on duplicate entrada, FK rollback on ghost entrada, happy-path control.

### `voluntarios` (`app/modules/voluntarios/`)
- **Covered by**: ~12 `test_voluntarios_*.py` files (service, application, routes, roles, RBAC).
- **Gap**: no integration test of "insert user → mark inactive → hit protected route → expect 302".

### `tasks` (worker / async)
- **Covered by**: `test_tasks.py` only.
- **Gap**: thin coverage; may not exercise retry or idempotency.

### `core` (`app/core/`)
- **Auth**: most heavily tested area in the project, but **all in-process with mocks**. No end-to-end "real Postgres + real session cookie + real CSRF" path tested together.
- **InsForge client**: `test_insforge.py` covers wire-level happy path + error envelope translation. Good.
- **Config / settings**: `test_config.py`, `test_startup_config_validation.py`. Good.
- **Logging**: `test_logging*.py`, `test_log_safe_*.py`. Good.

## Critical gaps

1. **No real-DB integration test for entradas batch rollback.** Most transactional flow; only MockTransport verification. Add `tests/integration/test_entradas_queries_integration.py`.
2. **No real-DB integration test for the append-only trigger** on `animal_lifecycle_events`. Ships in production; never asserted to fire.
3. **No real-DB integration test for `require_authorized_user` revalidation** (issue #143 path).
4. **No integration test for the unique-natural-key collision in cesiones / adopciones.** Conflict resolution is E2E-only.
5. **No E2E test of the rate-limit middleware under concurrent load.**
6. **No E2E test of the public search abuse path.**
7. **No unit/integration test of the InsForge storage bucket private-public invariant at the animales slice boundary.**
8. **No tests of `app/core/tasks.py` retry semantics against a flaky executor.**

## Flaky tests

After reading ~25 representative files, **no obvious source of non-determinism** in the default suite:

- No `time.sleep`, no `datetime.now()`-dependent assertions.
- `pytest-randomly` installed but `--randomly-dont-reorganize` keeps order stable.
- Each test installs its own dependency override and tears it down.

**Potential latent flakes** (none observed; flagging for hardening):

- `tests/test_coverage_gate.py` uses `pytester` subprocess — coverage.json depends on worker pool.
- `tests/migration/test_*` autouse `_default_msaccess_preflight` sets `_PSUTIL_AVAILABLE = True`.
- `tests/e2e/test_*` all skip gracefully when `/login` returns 503.
- The `_DefaultInsForgeSpy` pattern-matches SQL by string-prefix — brittle if calls reorder.

## Recommendations

### 1. Convert to integration (high value)

| Source (mocked) | New integration atom | Why |
|---|---|---|
| `tests/test_entradas_batch.py` | `tests/integration/test_entradas_queries_integration.py::test_batch_rollback_on_midway_unique_violation` | CTE rollback unverifiable against fake |
| `tests/test_acogidas_lifecycle_events.py`, `test_adopciones_lifecycle_events.py` | `tests/integration/test_lifecycle_append_only_trigger.py` | Append-only trigger never asserted |
| `tests/test_chip_cascade.py` | `tests/integration/test_chip_cascade_integration.py` | FK cascade across multiple tables |
| `tests/test_auth.py` deactivate path | `tests/integration/test_auth_revalidation_integration.py` | Real cookie + DB revalidation |
| `tests/test_animales_insforge_adapter.py` chip cascade + photo | `tests/integration/test_animals_photo_bucket_invariant.py` | Bucket invariant at slice boundary |
| `tests/test_cesiones.py` conflict path | `tests/integration/test_cesiones_queries_integration.py` (closed #633) | Real unique constraints |

### 2. Extend existing tests

| File | Add |
|---|---|
| `tests/test_auth.py` | Assert per-request revalidation hits DB **exactly once** (mocked transport with call counter). |
| `tests/test_csrf_middleware.py` | Cross-session adversarial case (cookie A, token B) using real `_install_default_insforge_client`. |
| `tests/test_rate_limit_middleware.py` | Concurrency case (`asyncio.gather` 20 simultaneous requests, expect ≤ 5 OKs). |
| `tests/test_animals_public_api.py` | 429-after-threshold case via rate-limit middleware. |
| `tests/integration/test_sanidad_queries_integration.py` | CTE-rollback case for unique `(animal_id, fecha, tipo)` index. |
| `tests/integration/test_adopciones_queries_integration.py` | FK-reject case (inserting adopción with missing `voluntario_id`). |
| `tests/e2e/test_landing.py` | Confirm marketing modules list is **not** present in `/login` HTML. |
| `tests/test_csrf_form_enumeration.py` | Cases for new JSON API endpoints (PATCH `/animales/{id}/chip`). |
| `tests/test_vulture_guard.py` | Ensure guard's `BASELINE` doesn't accumulate dead entries. |

### 3. Eliminate or fix

- **`tests/test_smoke.py`** is essentially `assert 1 + 1 == 2`. Either delete it or convert into a sanity test that imports `app.main` and asserts `app.title` is set.
- **Ratchet tests** (`test_ruff_ratchet.py`, `test_module_size.py`, `test_route_size.py`, `test_route_layer_coverage.py`, `test_coverage_gate.py`, `test_docstring_coverage.py`, `test_critical_helpers_have_full_coverage.py`, `test_layers.py`, `test_check_*.py` ~12 files) form a **ratchet surface** that is large but each file is small. None should be deleted, but **the total surface is worth a sanity-check review**: each ratchet has its own BASELINE file; if any BASELINE goes stale the gate goes red for unrelated reasons. Pin a single owner.
- **`tests/_rule_helpers/fixtures/detector*_violates*`** and **`tests/fixtures/query_seam/*`** are fixture trees (not tests) — flagged here because they account for **a large fraction of the 660 files indexed by CodeGraph** (`tests/` ≈ 350k LOC total). They are deliberately malformed AST to exercise detectors; they are not test files in the sense the audit cares about, but they pollute the index. **Recommendation**: move them under `tests/_fixtures/` with a `__init__.py` that marks them skipped at collection time.

### 4. Add new tests (prioritized by criticality)

**P0** (security / data integrity):
1. `tests/integration/test_auth_revalidation_integration.py` — real DB + real session cookie + real CSRF token; assert deactivate path 302s.
2. `tests/integration/test_lifecycle_append_only_trigger.py` — assert UPDATE on `animal_lifecycle_events` rejected.
3. ✅ `tests/integration/test_entradas_queries_integration.py` — landed 2026-08-31 via PR closing #632. Three atoms: UNIQUE rollback (entrada pre-existing collides with staged row), FK rollback (ghost animal_id), happy-path control.
4. `tests/integration/test_chip_cascade_integration.py` — assert chip-cascade UPDATE fires against real rows.

**P1** (operational risk):
5. `tests/e2e/test_rate_limit_concurrent.py` — concurrent burst against `/animales/search`.
6. `tests/e2e/test_cesiones_conflict_integration.py` — concurrent double-grant; expect one OK + one 409.
7. `tests/test_coolify_webhook.py` — add signed-payload happy path.
8. `tests/test_tasks.py` — extend to flaky-executor retry path.

**P2** (architectural safety):
9. `tests/test_xss_audit_handlers.py` — add regression for each new route handler template.
10. `tests/test_make_csrf_request.py` — add a "form-field path" test.

## Concrete observations on what each layer actually tests

**Service-layer unit tests** (`test_acogidas.py`, `test_entradas.py`, `test_foster.py`, `test_sanidad.py`, `test_salud.py`, `test_materiales.py`, `test_cesiones.py`, `test_voluntarios_*.py`, `test_animals_insforge_adapter.py`):
- Pattern: real `InsForgeClient` wired to `httpx.MockTransport`. Handler returns canned rows / errors keyed on captured SQL.
- Asserts: SQL string shape, param ordering, exact call count.
- **What is hidden**: trigger execution, FK enforcement, ON CONFLICT semantics, `RETURNING` shape under empty rowsets.

**Route-layer integration tests** (`test_acogidas_routes.py`, `test_animals_routes.py`):
- Pattern: full FastAPI app + `httpx.ASGITransport`. `_NoSqlRouteClient` spy fails test if a route calls `client.execute_sql` directly.
- Asserts: HTTP status, redirect target, response body fragment, CSRF token present, role-gated 403.

**Application-layer unit tests** (`test_animals_application_*.py`, `test_acogidas_lifecycle_events.py`, `test_adopciones_lifecycle_events.py`):
- Pattern: `_StubPort` (animals) or `FakeSqlExecutor` (lifecycle).
- Asserts: input validation, error mapping, port delegation.

**Builder / queries tests** (`test_acogidas_queries.py`, `test_adopciones_queries.py`, `test_materiales_queries.py`, `test_salud_queries.py`, `test_sanidad_queries.py`):
- Pure functions; no transport.
- Asserts: `assert sql == expected_sql` (full equality or substring).
- **The strongest unit tests in the suite** — they pin SQL byte-for-byte.

**Integration tests** (`tests/integration/`): 5 files, only queries — not routes, not services. Single most under-invested layer given how much production complexity lives in SQL (CTEs, triggers, FK chains).

**Migration tests** (`tests/migration/`): best-in-class. The `FakeInsForge` understands `INSERT/UPDATE/SELECT/COUNT/CREATE TABLE`, parses `ON CONFLICT`, routes shadow-state UPDATEs. **Template every other slice should aspire to.**

**E2E tests** (`tests/e2e/`): well-gated (skips on `/login == 503`); use real InsForge; UUID-suffixed NCHIPs to avoid collisions. **Focused on happy CRUD**; negative paths mostly absent at E2E.

**Audit / meta tests**: ~70 files testing rules, gates, coverage. Intentional (AGENTS.md §23, §24). Risk: **baseline drift** — each guard has its own BASELINE; a stale entry means a forbidden pattern can come back without the gate noticing. Recommend a periodic BASELINE-audit PR.