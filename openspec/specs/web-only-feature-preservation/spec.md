# Spec: web-only-feature-preservation

## Purpose

Esta especificación define la preservación de features web-only de APAP durante el round-trip de migración bidireccional web↔legacy introducido por MIGRATION-01. Cubre tres mecanismos ortogonales — **shadow state** para valores sin source legacy (`DNI` en `voluntarios`), **derivation engine** para valores derivables desde datos legacy (`estado_actual_animal` a partir de la priority cascade de `DameSituacion()`), y **capa semántica** (`animal_lifecycle_events`) —, su contrato de integración con el applier de MIGRATION-01 vía el hook `post_apply_diff()`, la resolución CLI de casos `needs_review`, y la coexistencia con `sync_state.json`. Es aditiva al chain de MIGRATION-01 y no modifica los PRs 1–3 ya mergeados.

## Requirements

### Requirement: Persistencia del Shadow State con estrategia por columna

El sistema debe (`must`) persistir los valores web-only sin source legacy en una tabla SQL `web_only_feature_shadow` con CRUD atómico, índice único compuesto sobre `(legacy_pk, table_name, web_column)`, columna `last_legacy_snapshot_at` (timestamp ISO 8601 UTC, nullable) y FK lógica a la fila web vía `web_pk`. Cada `ColumnMapping` en los YAML de MIGRATION-01 debe declarar un campo `web_only_strategy` ∈ `{preserve, fixed, derived}` validado por `pydantic` al cargar. En el bootstrap inicial de la primera migración:
- Estrategia `preserve` → la shadow row se popula con el valor actual en web (puede ser NULL si la web no lo tiene).
- Estrategia `derived` → la shadow row queda en NULL; la derivación se ejecuta en cada apply.
- Estrategia `fixed` → la shadow row contiene el valor estático declarado en YAML; nunca se re-deriva.

#### Scenario: Columna web-only con estrategia `preserve` persiste valor

- **given** una fila de `voluntarios` con `DNI = "12345678A"` en web y la columna `DNI` marcada `web_only_strategy: preserve` en `voluntario.yaml`
- **when** el applier legacy→web ejecuta `post_apply_diff` para esa fila
- **then** el sistema escribe/actualiza `web_only_feature_shadow` con `(legacy_pk, table_name="voluntarios", web_column="DNI", preserved_value="12345678A", last_legacy_snapshot_at=<UTC now>)`
- **and** el lookup por `(legacy_pk, web_column)` es O(1) gracias al índice único

#### Scenario: Columna web-only con estrategia `derived` queda en NULL hasta primera derivación

- **given** una fila de `animales` migrada inicialmente sin valor de `estado_actual_animal` y la columna marcada `web_only_strategy: derived`
- **when** finaliza la migración inicial
- **then** `web_only_feature_shadow` contiene una fila con `preserved_value = NULL`, `last_legacy_snapshot_at = NULL`
- **and** el derivation engine calcula el valor en el siguiente apply y lo escribe en `animal_current_state.current_state` (no en shadow)

#### Scenario: YAML con estrategia inválida aborta antes de tocar datos

- **given** un `ColumnMapping` con `web_only_strategy: "magic"` (valor fuera del enum)
- **when** `mappings.load_mapping()` carga el YAML
- **then** la validación pydantic falla con código de salida 4
- **and** no se ejecuta ningún read/write contra `.accdb` ni web

### Requirement: Derivation Engine determinista de `estado_actual_animal`

El sistema debe (`must`) proporcionar una función pura `derive_estado_actual_animal(tb_ficha, tb_entradas, tb_acogidas, tb_adopciones) -> str` que aplique la priority cascade documentada en `docs/discovery/lifecycle-state-resolver-extraction.md §3`, replicando la lógica de `DameSituacion()` en `Funciones Generales.bas:1116-1321`. La función debe ser determinista para un input dado (mismo input → mismo output) y debe cubrir los 11 casos identificados en la exploración (§4.1): incoherente, pendiente de entrada, pendiente de nueva situación, entregado, albergue, acogida, adoptado, fallecido (con `pre_death_state`), y combinaciones activas. Tras aplicar el resultado a `animal_current_state.current_state`, el sistema debe comparar el valor derivado con el valor stored y marcar `reconciliation_status` ∈ `{matched, divergent}`; adicionalmente debe copiar `legacy_situacion` desde `TbFichaAnimal.Situacion` para auditoría.

#### Scenario: Priority cascade resuelve los 11 casos parametrizados

- **given** las 11 combinaciones documentadas en `lifecycle-state-resolver-extraction.md` como fixtures pytest parametrizadas
- **when** se ejecuta `derive_estado_actual_animal` sobre cada fixture
- **then** cada fixture produce el estado esperado (`Albergue`, `Acogida`, `Adoptado`, `Fallecido ({pre})`, `Incoherente`, `Pendiente de entrada`, `Pendiente de Nueva Situación`, `Entregado`)
- **and** los 11 tests pasan verde

#### Scenario: Coincidencia con valor stored marca `matched`

- **given** un `animal_current_state` con `current_state = "Albergue"` derivado de un intake activo en legacy
- **when** el derivation engine re-deriva el estado tras un apply legacy→web que no afecta a las 4 tablas
- **then** el valor derivado es `"Albergue"`
- **and** el sistema escribe `reconciliation_status = "matched"` y `legacy_situacion = "Albergue"`

#### Scenario: Divergencia entre derivado y stored marca `divergent`

- **given** un `animal_current_state` con `current_state = "Albergue"` (valor previo) y un nuevo intake en `TbEntradas` en legacy que pasa al animal a `Acogida`
- **when** el applier legacy→web ejecuta el derivation engine
- **then** el valor derivado es `"Acogida"` (no `"Albergue"`)
- **and** el sistema actualiza `current_state = "Acogida"` y marca `reconciliation_status = "divergent"`
- **and** el caso aparece en la lista de `needs_review` (ver REQ-005)

### Requirement: Capa Semántica de Eventos separada del diff engine

El sistema debe (`must`) implementar un módulo independiente `app/core/migration/semantic_events.py` que traduzca diffs de filas legacy (`TbEntradas`, `TbAcogidaAnimal`, `TbAdopcion`, `TbFichaAnimal`) en filas `animal_lifecycle_events` con tipo de evento (`INTAKE_STARTED`, `INTAKE_COMPLETED`, `FOSTER_STARTED`, `FOSTER_RETURNED`, `ADOPTION_STARTED`, `ADOPTION_RETURNED`, `DEATH_RECORDED`) y metadatos derivados de las columnas legacy. El módulo no debe (`must not`) ser una extensión del diff engine genérico de MIGRATION-01 (`diff_engine.py`); debe (`must`) tener su propio conjunto de pruebas y su propia función pura de traducción. La firma debe ser invocable desde el hook `post_apply_diff()` con `(diff: Diff, table_mapping: TableMapping) -> list[LifecycleEvent]`.

#### Scenario: Diff de intake legacy se traduce a evento `INTAKE_STARTED`

- **given** un `Diff(op="INSERT", legacy_table="TbEntradas", ...)` para una fila con `FechaEntrada` no nula y `FSalida` nula
- **when** `semantic_events.translate_diff(diff, entrada_mapping)` ejecuta
- **then** retorna una lista con un `LifecycleEvent(event_type="INTAKE_STARTED", animal_id=<UUID web>, event_timestamp=<FechaEntrada>, source_legacy_pk=<IdEntrada>)`

#### Scenario: Diff de defunción legacy se traduce a evento `DEATH_RECORDED`

- **given** un `Diff(op="UPDATE", legacy_table="TbFichaAnimal")` con cambio en `FDefuncion` de NULL a una fecha no nula
- **when** `semantic_events.translate_diff(diff, animal_mapping)` ejecuta
- **then** retorna `[LifecycleEvent(event_type="DEATH_RECORDED", event_timestamp=<FDefuncion>, pre_death_state=<estado previo derivado>)]`
- **and** el módulo no depende de `diff_engine.DiffEngine` para operar (importa solo el dataclass `Diff`)

### Requirement: Hook `post_apply_diff` invoca derivation engine y capa semántica

El applier de MIGRATION-01 debe (`must`) invocar un hook `post_apply_diff(direction: Literal["legacy-to-web", "web-to-legacy"], applied_diffs: list[Diff], table_mappings: dict[str, TableMapping], web_client: InsForgeClient, shadow_state: ShadowState, sync_state: SyncState) -> ReconciliationResult` inmediatamente después de `apply_diff_to_web_transactional()` (definido en `migration-01/design.md §6`) y antes de retornar el `MigrationReport`. Para dirección `legacy-to-web`, el hook debe (`must`): (a) invocar el derivation engine sobre cada fila de `animales`/`entradas`/`acogidas`/`adopciones` afectada por el diff; (b) invocar `semantic_events.translate_diff` por cada diff y persistir los eventos resultantes en `animal_lifecycle_events`; (c) actualizar `web_only_feature_shadow` con `last_legacy_snapshot_at = <UTC now>` para cada columna `preserve` afectada. Para dirección `web-to-legacy`, el hook debe (`must`) preservar los valores shadow sin re-derivación.

> **P0 para design**: la firma exacta de `post_apply_diff` debe alinearse con `app/core/migration/applier.py` cuando PR 4/6 de MIGRATION-01 lo implemente. El nombre `reconcile_after_legacy_write` mencionado en la propuesta es un alias interno; la firma canónica es `post_apply_diff`.

#### REQ-Hook-Data: Sentinels `_stored_state` y `_web_updated_at` que el applier debe poblar en cada `Diff`

Para cada `Diff` con al menos una columna `web_only_strategy: derived`, el applier de MIGRATION-01 (PR 5/6) debe (`must`) poblar dos campos sentinela en el objeto `Diff` antes de invocar `post_apply_diff`. <!-- alantyle-ignore:ALAN007 -->

- **`diff._stored_state`** — el valor que la web actualmente tiene para esa columna al momento del write (`Any`). El derivation engine lo usa como input al comparador para clasificar la columna como `matched` / `divergent` / `needs_review`. Cuando el applier no puede leer el valor stored (columna nueva en web), debe (`must`) poblar `None` y el hook clasificará la columna como `PENDING`.
- **`diff._web_updated_at`** — el timestamp de la última edición web sobre esa columna (`datetime | None`, UTC). El comparador lo usa en la regla Q2: si `web_updated_at >= last_legacy_snapshot_at` → la edición web es posterior al último snapshot legacy → `needs_review` (override manual). Cuando la columna nunca fue editada en web, debe (`must`) poblar `None`.

Estos sentinels son **parte del contrato de `Diff`** para PR 4/6 (ver `design.md §6 — Sentinel contract`). Si el applier no los popula, el hook los trata como `None` y clasifica la columna como `PENDING` — el operador debe resolver el caso vía CLI en PR 5/6. Esta es la política de backward-compat para versiones previas del applier que no conocían el contrato.

#### Scenario: Apply sin sentinel `_stored_state` clasifica la columna como `PENDING`

- **given** un `Diff` para una fila de `animales` con `current_state` marcada `web_only_strategy: derived`
- **and** el applier invoca `post_apply_diff` sin poblar `diff._stored_state` (applier pre-PR-4 o error de configuración)
- **when** el hook evalúa la columna `derived`
- **then** el comparador no puede comparar el derivado contra el stored y emite `status = "pending"`
- **and** el caso aparece en `apap-migrate reconcile --check-only` (PR 5) para resolución manual

#### Scenario: Apply legacy→web re-deriva estado y persiste eventos

- **given** un batch de 50 INSERTs en `TbEntradas` legacy correspondientes a intakes nuevos
- **when** el applier completa `apply_diff_to_web_transactional` y entra al hook `post_apply_diff`
- **then** por cada fila afectada: (a) `animal_current_state.current_state` se re-deriva; (b) `animal_lifecycle_events` recibe un `INTAKE_STARTED`; (c) shadow state se actualiza con `last_legacy_snapshot_at`
- **and** `MigrationReport` incluye un campo `reconciliation_summary` con conteo de `matched` / `divergent` / `needs_review`

#### Scenario: Override manual en web marca `needs_review` tras cambio legacy

- **given** un animal con `current_state = "Acogida"` (override manual del voluntario en web) y `updated_at = T1` posterior al último sync; legacy cambia `TbAdopcion.FContrato` que provocaría derivar `"Adoptado"`
- **when** el applier legacy→web ejecuta el hook
- **then** el derivation engine retorna `"Adoptado"` pero el stored es `"Acogida"` (override manual)
- **and** el sistema no sobrescribe el valor web
- **and** escribe `reconciliation_status = "needs_review"`, `review_reasons = ["web_manual_override_detected"]`, `last_reconciled_at = T2`
- **and** el caso aparece en `apap-migrate reconcile --interactive` (ver REQ-005)

### Requirement: CLI `apap-migrate reconcile --interactive` para resolver `needs_review`

El sistema debe (`must`) exponer el subcomando CLI `apap-migrate reconcile [--interactive] [--check-only] [--table <name>] [--since <ISO>]` que enumere todos los casos con `reconciliation_status = "needs_review"`. Con `--interactive`, el sistema debe presentar cada caso uno a uno mostrando `table`, `legacy_pk`, `web_pk`, `column`, `web_value` (valor stored), `derived_value` (último derivado), `derived_at`, `last_legacy_snapshot_at`, y debe permitir al operador elegir: (a) **keep web** → escribe `reconciled_at = <UTC now>`, `reconciliation_status = "matched"`, no modifica el valor web; (b) **accept derived** → escribe el valor derivado en la columna web, `reconciled_at = <UTC now>`, `reconciliation_status = "matched"`; (c) **defer** → el caso permanece `needs_review`. Sin `--interactive`, el comando imprime la lista en formato CLI-renderable a stdout y sale con código 0 si hay casos pendientes (no aborta).

#### Scenario: Operador acepta valor derivado para un caso `needs_review`

- **given** un caso `needs_review` con `column = "current_state"`, `web_value = "Acogida"`, `derived_value = "Adoptado"`
- **when** el operador selecciona la opción `(b) accept derived`
- **then** el sistema ejecuta `UPDATE animal_current_state SET current_state = 'Adoptado', reconciliation_status = 'matched', reconciled_at = <UTC now>` para esa fila
- **and** el siguiente `apap-migrate reconcile` ya no lista ese caso

#### Scenario: Operador difiere el caso y permanece en la lista

- **given** un caso `needs_review` listado por el CLI
- **when** el operador selecciona la opción `(c) defer`
- **then** el sistema no modifica nada
- **and** el caso permanece con `reconciliation_status = "needs_review"` para la próxima ejecución

#### Scenario: Modo `--check-only` reporta sin escribir

- **given** 7 casos `needs_review` activos
- **when** se ejecuta `apap-migrate reconcile --check-only`
- **then** la salida stdout lista los 7 casos con sus metadatos
- **and** no se ejecuta ningún write contra la web
- **and** el comando termina con exit code 0

### Requirement: Round-trip preserva valores web-only y re-deriva al cambiar legacy

Para cualquier columna `preserve` (ej. `voluntarios.DNI`), un round-trip completo web→legacy→web debe (`must`) terminar con el valor web idéntico al valor inicial antes del round-trip, porque el legacy no escribe esa columna (`legacy_column: null`) y la shadow state la repuebla en el read legacy→web. Para cualquier columna `derived` (ej. `estado_actual_animal`), un cambio legacy que afecte a las 4 tablas del ciclo de vida debe (`must`) disparar re-derivación; si el valor derivado coincide con el stored → `matched`; si difiere y no hay override manual web → se sobrescribe y se marca `divergent`; si difiere y hay override manual web → `needs_review`.

#### Scenario: Round-trip web→legacy→web preserva `DNI`

- **given** un voluntario con `DNI = "12345678A"` en web (strategy `preserve`); legacy sin columna DNI
- **when** se ejecuta `apap-migrate --direction web-to-legacy` y luego `apap-migrate --direction legacy-to-web`
- **then** el `DNI` en web al final del round-trip es exactamente `"12345678A"`
- **and** la shadow row mantiene `preserved_value = "12345678A"` y `last_legacy_snapshot_at = <UTC now>`

#### Scenario: Cambio legacy que invalida estado dispara re-derivación

- **given** un animal con `current_state = "Albergue"` (matched, sin override manual)
- **when** el operador legacy registra `FDefuncion = 2026-07-01` en `TbFichaAnimal` y se ejecuta el applier legacy→web
- **then** el derivation engine retorna `"Fallecido (Albergue)"`
- **and** `current_state` se actualiza a `"Fallecido (Albergue)"`, `reconciliation_status = "divergent"` (cambió el valor), `pre_death_state = "Albergue"`
- **and** el caso aparece en `apap-migrate reconcile --check-only` como informativo (no bloqueante)

### Requirement: Coexistencia con `sync_state.json` de MIGRATION-01

La tabla SQL `web_only_feature_shadow` debe (`must`) coexistir con `sync_state.json` (definido en `migration-01/design.md §1.1` y `§7`) como dos almacenes separados con responsabilidades distintas: `sync_state.json` mapea `legacy_id ↔ web_uuid` y `last_sync_at` por tabla (infraestructura del diff engine); `web_only_feature_shadow` almacena valores de columnas web-only por `(legacy_pk, table_name, web_column)` (lógica de negocio de preservación). El applier debe (`must`) actualizar ambos almacenes en la misma transacción web cuando aplique (`apply_diff_to_web_transactional` cubre el shadow state; `sync_state` se actualiza vía `sync_state.save()` post-COMMIT). no debe (`must not`) unificarse en un solo archivo/tabla.

#### Scenario: Applier actualiza shadow state y `sync_state` en una transacción

- **given** un batch de 100 UPDATEs legacy→web que afectan columnas `preserve`
- **when** el applier completa `apply_diff_to_web_transactional` con `COMMIT` exitoso
- **then** `web_only_feature_shadow` tiene 100 filas actualizadas (o insertadas) con `last_legacy_snapshot_at = <UTC now>`
- **and** `sync_state.json` tiene `tables[<tabla>].last_sync_at = <UTC now>` actualizado
- **and** ningún caso quedó con `last_legacy_snapshot_at` desincronizado respecto a `sync_state.json`

### Requirement: Mecanismo genérico declarativo vía YAML

Añadir una nueva columna web-only al modelo debe (`must`) requerir exclusivamente: (a) declarar la columna en el YAML de mapping correspondiente con `legacy_column: null` y `web_only_strategy ∈ {preserve, fixed, derived}`; (b) si `derived`, declarar el `derivation_rule` o `derivation_source_table` que el derivation engine sepa resolver. no debe (`must not`) requerir cambios en código Python (más allá de registrar el nuevo derivation rule si introduce una cascade nueva). El campo `web_only_strategy` debe ser obligatorio en cualquier `ColumnMapping` con `legacy_column: null`; su ausencia aborta con código 4.

#### Scenario: Nueva columna `email_secundario` se añade solo por YAML

- **given** un `voluntario.yaml` con una nueva entrada `{ web_column: email_secundario, legacy_column: null, transform: identity, web_only_strategy: preserve }`
- **when** se ejecuta una migración legacy→web completa
- **then** el sistema crea/actualiza la fila en `web_only_feature_shadow` para `email_secundario` sin necesidad de modificar `shadow_state.py`
- **and** los tests del spec que cubren `DNI` siguen pasando (no regresión)

#### Scenario: Columna sin `web_only_strategy` con `legacy_column: null` aborta

- **given** un `ColumnMapping` con `legacy_column: null` y sin `web_only_strategy`
- **when** `load_mapping()` carga el YAML
- **then** pydantic rechaza con `ValidationError` → exit code 4 antes de cualquier I/O

### Requirement: Presupuesto de rendimiento para shadow state

Lookups en `web_only_feature_shadow` por `(legacy_pk, table_name, web_column)` deben (`must`) ser O(1) gracias al índice único compuesto. Una migración inicial de 10 000 filas × 5 columnas web-only (estrategia mixta) debe (`must`) completarse en menos de 10 segundos de overhead del mecanismo de preservación (medido en el VPS de staging; сумa de read + write + derivation, excluyendo I/O Dysflow/InsForge). El reconciliation step post-applier por lote de 100 filas legacy debe (`must`) añadir menos de 1 segundo al tiempo total del applier.

#### Scenario: 10k filas × 5 cols preservadas en menos de 10s

- **given** un dataset sintético de 10 000 animales con 5 columnas web-only (mezcla de `preserve`, `derived`, `fixed`)
- **when** se ejecuta `apap-migrate reconcile --check-only` sobre todo el dataset en el VPS de staging
- **then** el comando completa en menos de 10 segundos (medido con `time`)
- **and** la métrica se reporta en la salida `--verbose`

#### Scenario: Reconciliation por lote de 100 filas en menos de 1s

- **given** un batch de 100 UPDATEs legacy→web
- **when** el applier mide el tiempo del hook `post_apply_diff` aislado
- **then** el hook completa en menos de 1 segundo
- **and** `MigrationReport.reconciliation_summary.duration_ms < 1000`

## Out of Scope

- **Interfaz web** para resolver `needs_review` (la propuesta §Alcance y la decisión Q8-A fijan CLI interactivo exclusivamente).
- **OCR** u otras fuentes de población automática de `DNI` en la migración inicial (decisión Q1-A: NULL post-migración; el voluntario rellena manualmente desde la web).
- **Auto-detección** de columnas web-only: cada nueva columna requiere declaración explícita en YAML.
- **Tablas fuera de las 5 MIGRATION-01** (`animales`, `voluntarios`, `entradas`, `acogidas`, `adopciones`). El mecanismo es extensible a otras tablas pero el alcance de este change se limita a las 5.
- **Resolución automática** de `needs_review` (Q8-A: intervención del operador vía CLI).
- **Soporte de múltiples legacys simultáneos** ni **sync en tiempo real** (heredado de MIGRATION-01 §12 limitaciones).
- **Bitemporal modeling** para auditoría retroactiva (exploración §6.3: no aplicable en esta fase).
- **Tests E2E con sandbox .accdb real**: este change se testea con mocks/fixtures; el sandbox E2E ya está cubierto por MIGRATION-01 PR 4/6+.

## Hallazgos P0 para la fase de design

1. **`post_apply_diff()` no tiene firma canónica** en `migration-01/design.md`. El diseño de este change debe acordar con el owner de PR 4/6 la firma exacta, los parámetros y el orden de invocación respecto a `apply_diff_to_web_transactional()` y `sync_state.save()`.
2. **`reconcile_after_legacy_write` (citado en la propuesta como "firma PR 3") no existe en MIGRATION-01 PR 3/6** (que cubre readers + dysflow_client stub). La función debe definirse desde cero en este change; el alias en la propuesta es ambiguo.
3. **`legacy_situacion`, `reconciliation_status`, `pre_death_state` se listan en `migration-discovery-docs/spec.md` como `state machine linked to event log`** pero no se confirma que existan como columnas de `animal_current_state`. El diseño debe verificar que la tabla destino ya está creada (ver `migration-01/design.md` Anexo A — `animal_current_state` no aparece en el schema; dependencia cruzada).
4. **Trade-off de atomicidad**: shadow state lives en la DB web, `sync_state.json` en el filesystem. Si la transacción web hace `COMMIT` pero la escritura de `sync_state.json` falla (disk full, permisos), `last_sync_at` queda desfasado de `last_legacy_snapshot_at`. Diseño debe documentar la política de recovery (¿retry? ¿alerta? ¿rebuild desde logs?).
