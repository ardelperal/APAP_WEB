# Tasks: web-only-feature-preservation

## Resumen

| Campo | Valor |
|-------|-------|
| SDD | `web-only-feature-preservation` |
| PRs | 6 |
| Tasks totales | 31 |
| Líneas estimadas (total) | ~1 970 |
| Rama objetivo | `staging` |
| Estrategia de delivery | `auto-chain` (fuerza-chained) |
| Dependencia MIGRATION-01 | PR 4 requiere MIGRATION-01 PR 4/6 y 6/6 mergeados |

## Review Workload Forecast

| Campo | Valor |
|-------|-------|
| Líneas estimadas (cambio) | ~1 970 (6 PRs) |
| Riesgo presupuesto 400 líneas | **Alto** — 4 de 6 PRs superan el presupuesto |
| PRs encadenadas recomendadas | **Sí** — 6 PRs en cadena |
| Estrategia de cadena | `stacked-to-main` (cada PR mergea a `staging`, la cadena completa Promotion a `main`) |
| Decisión necesaria antes de apply | **No** — `auto-chain` con `force-chained` (decisión del usuario 2026-06-21) |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Schema + shadow_state CRUD + P0 blocker tables | PR 1 (`feat(web-only-preservation): schema + shadow-state`) | ~370 líneas; no dep MIGRATION-01 |
| 2 | Derivation engine + semantic events | PR 2 (`feat(web-only-preservation): derivation + semantic-events`) | ~400 líneas; requiere tablas lifecycle de PR 1 |
| 3 | YAML mappings update + loader validation | PR 3 (`feat(web-only-preservation): yaml-extensions`) | ~150 líneas; independiente |
| 4 | Hook integration con MIGRATION-01 applier | PR 4 (`feat(web-only-preservation): applier-hook`) | ~400 líneas; **requiere MIGRATION-01 PR 4/6 y 6/6 mergeados** |
| 5 | CLI `apap-migrate reconcile` | PR 5 (`feat(web-only-preservation): reconcile-cli`) | ~350 líneas; requiere PR 4 |
| 6 | Round-trip tests + perf | PR 6 (`test(web-only-preservation): round-trip + perf`) | ~300 líneas; requiere todo |

---

## PR 1: Schema + shadow_state CRUD + P0 blocker tables

**Rama**: `staging` → `feat/web-only-p1-schema`
**Est. líneas**: ~370 | **Dep. MIGRATION-01**: Ninguna

- [x] 1.1 Añadir `ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL` y `ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL` a `app/core/domain.py` (schemas de `lifecycle-event-log-design.md §3.1-3.2`) — **P0 BLOCKER**
- [x] 1.2 Integrar ambas tablas en `ensure_domain_schema()` de `app/core/domain.py`
- [x] 1.3 Crear `app/core/migration/shadow_state.py` con clase `ShadowStateRepository` y métodos `upsert`, `lookup`, `list_needs_review`, `update_reconciliation_status`
- [x] 1.4 Crear tabla `web_only_feature_shadow` con índice único `(table_name, legacy_pk, web_column)` — SQL en `shadow_state.py`
- [x] 1.5 Extender `ColumnMapping` en `app/core/migration/mappings/__init__.py` con campo `web_only_strategy: Literal["preserve","fixed","derived"] | None` y validador
- [x] 1.6 Crear módulo `app/core/migration/reconcile.py` con tipos `ReconciliationResult`, `ReconciliationOutcome`, `ReconciliationStatus`
- [x] 1.7 Añadir subcomando `reconcile` skeleton en `app/core/migration/cli.py` (flag `--check-only`, `--interactive`, `--table`, `--since`)
- [x] 1.8 Escribir 5 tests unitarios para `shadow_state.py` (upsert, lookup O(1), list_needs_review, update_status, delete)
- [x] 1.9 Escribir 2 tests de integración para el CLI skeleton (`--help` → exit 0; `--check-only` sin escribir)
- [x] 1.10 Verificar con `pytest tests/test_migration.py -W error::DeprecationWarning` — coverage ≥80%

---

## PR 2: Derivation engine + semantic events

**Rama**: `feat/web-only-p1-schema` → `feat/web-only-p2-derivation`
**Est. líneas**: ~400 | **Dep. MIGRATION-01**: Ninguna (usa tablas de PR 1)

- [ ] 2.1 Implementar `derive_estado_actual_animal(tb_ficha, tb_entradas, tb_acogidas, tb_adopciones) -> DerivationResult` en `app/core/migration/derivation.py` — priority cascade de `DameSituacion()` (`lifecycle-state-resolver-extraction.md §3`)
- [ ] 2.2 Implementar comparador post-aplicación: `matched` / `divergent` / `needs_review` según regla Q2
- [ ] 2.3 Escribir 11 tests parametrizados para `derive_estado_actual_animal` (casos de `lifecycle-state-resolver-extraction.md §4`)
- [ ] 2.4 Crear `app/core/migration/semantic_events.py` con función pura `translate_diff(diff: Diff, table_mapping: TableMapping) -> list[LifecycleEvent]`
- [ ] 2.5 Mapear 8 combinaciones diff→evento (INSERT/UPDATE en TbEntradas/TbAcogidaAnimal/TbAdopcion/TbFichaAnimal → eventos de `lifecycle-event-log-design.md §4`)
- [ ] 2.6 Escribir 8 tests unitarios para `semantic_events.py` (uno por combinación diff→evento)
- [ ] 2.7 Escribir 4 tests unitarios para paths de reconcile (preserve / fixed / derived / needs_review)
- [ ] 2.8 Integrar `derive_estado_actual_animal` en `reconcile_after_legacy_write()` de `reconcile.py`
- [ ] 2.9 Verificar con `pytest tests/test_migration.py -W error::DeprecationWarning` — coverage ≥80%

---

## PR 3: YAML mappings update + loader validation

**Rama**: `feat/web-only-p2-derivation` → `feat/web-only-p3-yaml`
**Est. líneas**: ~150 | **Dep. MIGRATION-01**: Ninguna

- [ ] 3.1 Añadir `web_only_strategy: preserve` a columna `DNI` en `app/core/migration/mappings/voluntario.yaml`
- [ ] 3.2 Validar que YAML sin `web_only_strategy` con `legacy_column: null` aborta con código de salida 4 (test)
- [ ] 3.3 Validar que YAML con `web_only_strategy` inválido aborta con `ValidationError` (test)
- [ ] 3.4 Documentar en comentario YAML la estrategia de cada columna web-only de las 5 tablas

---

## PR 4: Hook integration con MIGRATION-01 applier

**Rama**: `feat/web-only-p3-yaml` → `feat/web-only-p4-hook`
**Est. líneas**: ~400 | **Dep. MIGRATION-01**: **PR 4/6 y PR 6/6 mergeados primero**

- [ ] 4.1 Implementar `post_apply_diff(*, direction, applied_diffs, table_mappings, web_client, shadow_state, sync_state) -> ReconciliationResult` en `app/core/migration/reconcile.py`
- [ ] 4.2 Invocar `reconcile_after_legacy_write()` por cada fila afectada en dirección `legacy-to-web`
- [ ] 4.3 Invocar `semantic_events.translate_diff()` por cada diff y persistir eventos en `animal_lifecycle_events`
- [ ] 4.4 Actualizar `last_legacy_snapshot_at` en `web_only_feature_shadow` para columnas `preserve` afectadas
- [ ] 4.5 En dirección `web-to-legacy`: no-op (preservar shadow state sin re-derivación)
- [ ] 4.6 Extender `MigrationReport` con campo `reconciliation_summary: ReconciliationSummary`
- [ ] 4.7 Escribir 3 tests de integración: (a) apply legacy→web re-deriva y marca `matched`; (b) divergencia sin override manual → `divergent`; (c) divergencia con override manual → `needs_review`
- [ ] 4.8 Escribir 1 test de integración de atomicidad mixta (fallo simulado en sync_state post-COMMIT)
- [ ] 4.9 Coordinar con autor de MIGRATION-01 PR 4/6 la firma exacta de `post_apply_diff` antes de merge
- [ ] 4.10 Verificar con `pytest tests/test_migration.py -W error::DeprecationWarning` — coverage ≥80%

---

## PR 5: CLI `apap-migrate reconcile`

**Rama**: `feat/web-only-p4-hook` → `feat/web-only-p5-reconcile-cli`
**Est. líneas**: ~350 | **Dep. MIGRATION-01**: PR 4 (requiere `post_apply_diff`)

- [ ] 5.1 Implementar `apap-migrate reconcile --check-only`: lista casos `needs_review` sin escribir — exit 0 si hay pendientes
- [ ] 5.2 Implementar `apap-migrate reconcile --interactive`: presentar cada caso con metadatos y prompt (a) keep web / (b) accept derived / (c) defer / (q) quit
- [ ] 5.3 Implementar opción (a) keep web: escribe `reconciled_at`, `reconciliation_status = matched`, no modifica valor web
- [ ] 5.4 Implementar opción (b) accept derived: ejecuta UPDATE con valor derivado, `reconciliation_status = matched`
- [ ] 5.5 Implementar `--table <name>` y `--since <ISO8601>` como filtros
- [ ] 5.6 Escribir 1 test CLI `--check-only` sin escribir
- [ ] 5.7 Escribir 3 tests CLI `--interactive` con mocks (keep/accept/defer)
- [ ] 5.8 Escribir 1 test CLI `--table --since` filtros
- [ ] 5.9 Verificar con `pytest tests/test_migration_cli.py -W error::DeprecationWarning` — coverage ≥80%

---

## PR 6: Round-trip tests + perf

**Rama**: `feat/web-only-p5-reconcile-cli` → `feat/web-only-p6-tests`
**Est. líneas**: ~300 | **Dep. MIGRATION-01**: Todas las anteriores

- [ ] 6.1 Escribir test de round-trip `web→legacy→web` que preserva `DNI` (estrategia `preserve`) — valor idéntico al inicial
- [ ] 6.2 Escribir test de round-trip `legacy→web` que re-deriva `estado_actual_animal` tras cambio legacy — verifica `matched`
- [ ] 6.3 Escribir test de override manual en web + cambio legacy → `needs_review` (Q2 path)
- [ ] 6.4 Escribir test de perf: 10 000 animales × 5 columnas `preserve/derived/fixed` en <10s (`test_reconcile_perf.py`)
- [ ] 6.5 Verificar que derivation engine cubre los 11 casos de `lifecycle-state-resolver-extraction.md §4`
- [ ] 6.6 Ejecutar suite completa: `pytest tests/test_migration.py tests/test_migration_cli.py -W error::DeprecationWarning --cov=app --cov-report=term-missing` — coverage ≥80%

---

## Cross-PR Dependencies

```
PR 1 ──→ PR 2 ──→ PR 3 ──→ PR 4 ──→ PR 5 ──→ PR 6
                 └───────────────────────────────────── PR 4 también requiere
                     MIGRATION-01 PR 4/6 + PR 6/6 mergeados
```

| De | A | Tipo |
|----|---|-------|
| PR 1 | PR 2 | Tablas `animal_current_state` y `animal_lifecycle_events` necesarias para derivation engine |
| PR 2 | PR 4 | `derive_estado_actual_animal` y `translate_diff` necesarios para el hook |
| PR 3 | PR 4 | YAML actualizado con `web_only_strategy` necesario para el hook |
| PR 4 | PR 5 | `post_apply_diff` necesario para el CLI `reconcile` |
| MIGRATION-01 PR 4/6, 6/6 | PR 4 | Firma `post_apply_diff` definida en MIGRATION-01 PR 4/6; CLI `reconcile` integrado en MIGRATION-01 PR 6/6 |

---

## Implementation Commits (template)

| Commit | Work unit | SDD tasks | Verification |
|---|---|---|---|
| `<sha>` | `feat(domain): add animal_current_state + animal_lifecycle_events tables` | 1.1–1.2 | `pytest tests/test_domain.py` |
| `<sha>` | `feat(migration): shadow_state CRUD + ColumnMapping extension` | 1.3–1.6 | `pytest tests/test_migration.py -k shadow` |
| `<sha>` | `feat(migration): derive_estado_actual_animal + semantic_events` | 2.1–2.9 | `pytest tests/test_migration.py -k "derive or semantic"` |
| `<sha>` | `feat(migration): YAML web_only_strategy + voluntario.yaml update` | 3.1–3.4 | `pytest tests/test_migration.py -k yaml` |
| `<sha>` | `feat(migration): post_apply_diff hook + reconcile_after_legacy_write` | 4.1–4.10 | `pytest tests/test_migration.py -k reconcile` |
| `<sha>` | `feat(cli): apap-migrate reconcile --interactive + --check-only` | 5.1–5.9 | `pytest tests/test_migration_cli.py -k reconcile` |
| `<sha>` | `test(migration): round-trip + perf tests` | 6.1–6.6 | `pytest --cov=app --cov-report=term-missing` |

---

## Notas

- **TDD estricto**: cada tarea escribirse primero el test rojo, luego producción verde, luego refactor. Pytest con `--strict-markers --strict-config -W error::DeprecationWarning`.
- **Conventional commits**: `feat(...)`, `test(...)`, `fix(...)`, `docs(...)` en inglés con scope `web-only-preservation`.
- **P0 blocker**: las tablas `animal_current_state` y `animal_lifecycle_events` **NO existen** en `app/core/domain.py`. Añadirlas en PR 1 es obligatorio antes de PR 2. Schemas en `docs/discovery/lifecycle-event-log-design.md §3.1-3.2`.
- **E2E con MIGRATION-01**: los tests de PR 6 asumen MIGRATION-01 PR 4/6 y 6/6 mergeados. Sin ellos, los tests de integración del hook saltan con `pytest.skip`.
- **Idioma de artefactos SDD**: español profesional (España) conforme a `openspec/config.yaml:21`.
- **Presupuesto de revisión**: 400 líneas por PR. Los PRs 1, 2, 4 y 5 superan ~350–400 líneas — revisar con `chained-pr` skill antes de abrir cada PR.
- **Atomicidad mixta**: si `sync_state.save()` falla tras el COMMIT web, el derivation engine es idempotente — el siguiente `apply` corrige en ≤2 rondas (design §8).