# Design: web-only-feature-preservation

> **Nota (2026-06-22)**: este `design.md` se crea como parte del PR 4/6 del
> change. El code review de PR 3/6 (#98) señaló (P2 #1) que el doc estaba
> stale y que la sección §9 estaba sin el rationale por-transform de
> `_STRATEGY_EXEMPT_TRANSFORMS`. Este PR cierra ese gap y además cubre las
> secciones §6, §7 y §8 que la `spec.md` y el código referencian
> (``shadow_state.py:9``, ``cli.py:144``, ``mappings/__init__.py:161,214,228``).
>
> Las secciones §1–§5 (contexto, capas, modelo de datos, etc.) se
> mantuvieron fuera de scope del PR 4: ya están cubiertas en la
> `spec.md` del change y en los docstrings de cada módulo
> (``shadow_state.py``, ``derivation.py``, ``semantic_events.py``,
> ``reconcile.py``). El doc prioriza los huecos que la `spec.md` y el
> código efectivamente referencian como "ver design.md §X".

## Technical Approach

El change se entrega como cadena de 6 PRs (`force-chained`) sobre la
rama `staging`, construidos sobre la dependencia MIGRATION-01 PR 4/6
(diff engine + sync_state + lock). Cada PR cierra una unidad de valor
revisable independientemente:

| PR | Alcance | Salida principal |
|----|---------|------------------|
| 1 | Schema + shadow_state CRUD | `animal_current_state` + `animal_lifecycle_events` + `web_only_feature_shadow` |
| 2 | Derivation engine + semantic events | `derive_estado_actual_animal()` + `translate_diff()` puros |
| 3 | YAML mappings + strict validator | `ColumnMapping.web_only_strategy` requerido en web-only |
| 4 | Hook integration | `post_apply_diff()` + `MigrationReport.reconciliation_summary` (este PR) |
| 5 | CLI `apap-migrate reconcile` | `--interactive`, `--check-only`, `--table`, `--since` |
| 6 | Round-trip tests + perf | Validación end-to-end + benchmark 10k filas <10s |

PR 4 (este) conecta los módulos puros de PR 1–3 con el applier de
MIGRATION-01: el hook `post_apply_diff` corre inmediatamente después
de `apply_diff_to_web_transactional()` y antes de retornar el
`MigrationReport`. La regla "staging como única fuente de verdad"
mantiene el contrato: el hook sólo escribe a `staging` (web) y a
`sync_state.json`; nunca toca el legacy `.accdb` directamente.

## Architecture decisions

| Decision | Choice | Alternative | Why |
|----------|--------|-------------|-----|
| **Lugar del hook** | Después de `apply_diff_to_web_transactional()`, antes del `MigrationReport` | Antes del COMMIT; en una capa middleware | Co-loca el hook con el commit del applier para minimizar ventanas de inconsistencia; el `MigrationReport` lleva el resumen al operador. |
| **Forma del resumen** | `ReconciliationSummary` dataclass embebido en `MigrationReport` | Lista cruda de outcomes; archivo JSON separado | El reporte es inmutable y audit-evident (regla §1.4 de `reporting.py`); embeber el resumen evita acoplar dos artefactos. |
| **Persistencia de eventos** | INSERT directo en `animal_lifecycle_events` desde el hook | Event-sourcing puro (append-only log → state) | El hook solo materializa el cache `animal_current_state` cuando aplica; el log es append-only por construcción (spec REQ-Capa Semantica). |
| **`_STRATEGY_EXEMPT_TRANSFORMS`** | `frozenset({"default_uuid", "default_now", "fk_lookup"})` | Lista de YAMLs `legacy_column=null` sin strategy; opt-out por columna | (Justificación por transform en §9.) |
| **Manejo de errores en `post_apply_diff`** | Capturar excepciones del derivation engine y mapear a `errors` en el `ReconciliationResult` | Propagar y abortar el run | Una fila mal derivada no debe abortar 1000 filas OK; el reporte lleva el conteo de errores y la tabla `MigrationReport.reconciliation_summary.errors` para diagnóstico. |
| **Dirección `web→legacy`** | No-op en el hook | Re-derivar al revés | El shadow state preserva el valor web verbatim; re-derivar al revés no aporta información (regla REQ-Hook spec). |
| **Atomicidad mixta** | Idempotente + retry del siguiente `apply` | Transacción distribuida web+filesystem | El derivation engine es puro + idempotente; un retry en el siguiente apply es ≤2 rondas (spec REQ-Atomicidad). |

## §6 — Integración con MIGRATION-01 (hook `post_apply_diff`)

El applier de MIGRATION-01 (PR 5/6) llama `post_apply_diff` **inmediatamente
después** de `apply_diff_to_web_transactional()` y **antes** de retornar
el `MigrationReport`. La firma canónica (alineada con la `spec.md`
REQ-Hook y con la implementación actual de `reconcile.py`) es:

```python
def post_apply_diff(
    *,
    direction: Literal["legacy-to-web", "web-to-legacy"],
    applied_diffs: Sequence[Diff],
    table_mappings: Mapping[str, TableMapping],
    web_client: InsForgeClient,
    shadow_state: ShadowStateRepository,
    sync_state: SyncState,
) -> ReconciliationResult:
```

### Comportamiento por dirección

- **`direction == "legacy-to-web"`** (camino feliz):
  1. Por cada `diff` en `applied_diffs`:
     - Si `table_mappings[diff.table]` no existe → emitir outcome
       `MATCHED` con `errors=("no_table_mapping",)` (no abortar).
     - Si `table_mapping.columns` tiene columnas con
       `web_only_strategy in {"preserve", "derived"}`, llamar
       `reconcile_after_legacy_write()` con los inputs correspondientes
       (legado + web stored + `last_legacy_snapshot_at = <UTC now>`).
       El dispatcher interno (`_reconcile_preserve`,
       `_reconcile_derived`, `_reconcile_fixed`) ya está implementado
       en `reconcile.py`.
     - Llamar `semantic_events.translate_diff(diff, table_mapping)`
       y persistir los `LifecycleEvent` retornados en
       `animal_lifecycle_events` vía `web_client.execute_sql` (INSERT
       directo; el contrato de la tabla está en
       `app/core/domain.py::ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL`).
  2. Devolver `ReconciliationResult(outcomes=…, errors=…)`.

- **`direction == "web-to-legacy"`**: no-op. Devolver
  `ReconciliationResult(outcomes=(), errors=())`. El shadow state no
  se toca (los valores web sobreviven al round-trip verbatim) y la
  re-derivación no aporta información (spec REQ-Hook).

### Persistencia de eventos

Para cada `LifecycleEvent` retornado por `translate_diff`, el hook
ejecuta un INSERT en `animal_lifecycle_events` con los campos:

| Campo | Origen |
|-------|--------|
| `animal_id` | `lookup_web_pk(sync_state, "animales", diff.legacy_pk)` cuando aplique; `None` si el diff no es de `TbFichaAnimal` |
| `event_type` | `event.event_type` |
| `event_timestamp` | `event.event_timestamp.isoformat()` |
| `legacy_source_table` | `event.legacy_source_table` |
| `legacy_source_id` | `event.legacy_source_id` (puede ser `None` para `DEATH_RECORDED` — ver `semantic_events.py` §P1 #2) |
| `source_entity_type` | `event.source_entity_type` |
| `metadata` | `json.dumps(event.metadata)` cuando aplique |
| `created_by` | Resolver del InsForge auth context (out of scope del test — el hook acepta `created_by` como parámetro opcional) |

Errores de INSERT se acumulan en `ReconciliationResult.errors` (no
aborta el batch; el siguiente apply puede reintentar la fila).

### Orden de invocación

```text
applier.apply_diff_to_web_transactional()       # COMMIT en InsForge
   │
   ├─→ post_apply_diff()                          # ← ESTE HOOK
   │     ├─ reconcile_after_legacy_write()        # shadow_state.upsert
   │     └─ translate_diff() → INSERT events      # animal_lifecycle_events
   │
   ├─→ sync_state.save()                          # post-COMMIT
   │
   └─→ MigrationReport(reconciliation_summary=…)
```

El orden `hook → sync_state.save()` es intencional: el `last_sync_at`
de `sync_state.json` se actualiza **después** de que el shadow state y
los eventos están persistidos. Si el proceso muere entre el hook y el
`sync_state.save()`, el derivation engine es idempotente y el
siguiente `apply` corrige en ≤2 rondas (spec REQ-Atomicidad — ver §8).

### Sentinel contract (sentinels en `Diff`)

El comparador de la columna `derived` (vía
`derivation.compare_derived_to_stored`) necesita dos piezas de
información que **no viven en el derivation engine ni en
`diff.legacy_row`**: el valor que la web tiene en este momento y la
fecha de la última edición web. Esos dos datos los lleva el applier
porque es quien está a punto de escribir la fila web — el hook
no tiene una vista estable de la DB web en ese instante.

**Definición del contrato** (alineada con la spec REQ-Hook-Data):

| Sentinel | Tipo | Origen | Semántica |
|----------|------|--------|-----------|
| `diff._stored_state` | `Any` | `diff.web_row[column]` cuando el applier lo leyó antes del write; `None` si no existe en la fila web (columna nueva) | Valor que la web sostiene en el instante previo al write del applier. El comparador lo confronta con el derivado. |
| `diff._web_updated_at` | `datetime \| None` (UTC) | `diff.web_row["updated_at"]` cuando la tabla destino tiene columna `updated_at`; `None` en caso contrario | Timestamp de la última edición web sobre esa columna. El comparador lo usa en la regla Q2: `web_updated_at >= last_legacy_snapshot_at → NEEDS_REVIEW` (override manual). |

**Cómo los popula el applier (PR 5/6)**:

```python
# En el applier de MIGRATION-01, justo antes de invocar el hook:
diff._stored_state = (
    diff.web_row.get(column.web_column) if diff.web_row else None
)
diff._web_updated_at = (
    datetime.fromisoformat(diff.web_row["updated_at"])
    if diff.web_row and "updated_at" in diff.web_row
    else None
)
```

**Interacción con `Diff`**:

El dataclass `Diff` en `app/core/migration/reporting.py` (PR 4) NO
añade estos campos como atributos formales — vienen como **side
channel** sobre el `legacy_snapshot` que el applier pasa al hook (los
helper `_reconcile_column` / `_build_derived_inputs` los `pop()` antes
de invocar la derivación). Esta decisión preserva la
backward-compat con `Diff` (MIGRATION-01 PR 4/6) sin tocar su firma
pública — el campo canónico para el sentinels en una iteración
futura podría ser `Diff._stored_state: Any = None` y
`Diff._web_updated_at: datetime | None = None` (PR 5+ puede
promoverlos a campos formales sin romper callers existentes porque
los defaults son `None`).

**Fallback cuando el sentinel falta**:

Si el applier pasa `legacy_snapshot` sin `_stored_state` o
`_web_updated_at`, el hook (`reconcile._reconcile_column:677-678`)
los recibe como `None` y `_reconcile_derived` (vía
`compare_derived_to_stored`) clasifica la columna como
`ReconciliationStatus.PENDING`. El operador debe resolver el caso
vía CLI en PR 5/6. Esta es la política explícita de backward-compat:
un applier pre-PR-4 (que no conoce los sentinels) sigue siendo
compatible, solo que todos los `derived` se inicializan como
`PENDING` en lugar de `MATCHED`. Documentado en la spec
REQ-Hook-Data + escenario "Apply sin sentinel `_stored_state`
clasifica la columna como `PENDING`".

## §7 — CLI `apap-migrate reconcile`

Subcomando del CLI `app/core/migration/__main__.py` (PR 5 llena el
cuerpo; PR 1 ya tiene el skeleton con los 4 flags documentados en
`cli.py:34-97`). Contrato:

| Flag | Tipo | Efecto |
|------|------|--------|
| `--check-only` | bool | Lista casos `needs_review` a stdout sin escribir. Exit 0 si hay pendientes (no aborta). |
| `--interactive` | bool | Prompt por cada caso: (a) keep web / (b) accept derived / (c) defer / (q) quit. |
| `--table <name>` | str | Filtra por tabla (`animales`, `voluntarios`, etc.). |
| `--since <ISO>` | str | Filtra por `last_legacy_snapshot_at >= since`. |

### Formato stdout (no-interactive)

Una línea por caso en formato `key=value` para pipe a `jq`/`grep`:

```text
table=animales legacy_pk=001 web_column=current_state status=needs_review \
  web_value=Acogida derived_value=Adoptado derived_at=2026-06-21T10:00:00+00:00 \
  last_legacy_snapshot_at=2026-06-21T11:00:00+00:00
```

### Exit codes (alineados con `reporting.py` y `mappings/__init__.py`)

| Code | Significado |
|------|-------------|
| 0 | OK (incluso si hay `needs_review` pendientes en `--check-only`) |
| 4 | `ValidationError` del YAML (regla `EXIT_CODE_YAML_VALIDATION_ERROR`) |
| 5 | I/O error contra la DB o `sync_state.json` |

## §8 — Política de atomicidad mixta

El shadow state vive en la DB web (`web_only_feature_shadow`) y
`sync_state.json` en el filesystem. Esto es una **decisión
deliberada** (spec REQ-Coexistencia): los dos almacenes cubren
preocupaciones ortogonales y NO se unifican.

### Ventana de inconsistencia

```text
T0  COMMIT en InsForge             ← shadow_state actualizado
T1  procesos mueren / disco lleno
T2  sync_state.json queda stale    ← last_sync_at desfasado
```

### Política de recovery

1. **Idempotencia del derivation engine**: `derive_estado_actual_animal`
   es puro y determinista (spec §6 + `derivation.py` docstring). Re-aplicar
   el mismo diff con `last_legacy_snapshot_at` posterior corrige la
   divergencia sin escribir valores espurios.
2. **Repair pass**: el applier detecta `last_sync_at < last_legacy_snapshot_at`
   en el primer `apply` post-fallo y emite un warning. No aborta — el
   reconciliation corre y la próxima ronda cierra el gap.
3. **Cap a 2 rondas**: si el hook vuelve a fallar (mismo error dos
   veces consecutivas), el applier aborta con exit 6 ("recovery_loop")
   y requiere intervención del operador (regla #13474 v2: nunca
   silent retry indefinido).
4. **Sin transacción distribuida**: `sync_state.json` se actualiza
   post-COMMIT vía `sync_state.save()` (escritura atómica con
   `os.replace` para evitar JSON corrupto — ver `sync_state.py:117`).

### Justificación de NO usar 2PC / saga

El shadow state y `sync_state.json` cubren dominios separados (negocio
vs infraestructura) y se actualizan en pasos linealmente ordenados. Un
2PC añadiría latencia y complejidad sin beneficio observable (el
"recovery en 2 rondas" es aceptable — está documentado en la spec
REQ-Atomicidad y en `tasks.md` Notas finales).

## §9 — Configuración YAML: `web_only_strategy`

Cada `ColumnMapping` con `legacy_column=null` (columna web-only /
greenfield) **debe** declarar un `web_only_strategy ∈ {preserve,
fixed, derived}`. El validador estricto en
`app/core/migration/mappings/__init__.py:185-230`
(`_require_strategy_for_web_only`) aborta con código
`EXIT_CODE_YAML_VALIDATION_ERROR` (4) si la combinación
"web-only + sin strategy" no está en la lista de transforms exentas.

### Lista exenta: `_STRATEGY_EXEMPT_TRANSFORMS`

```python
_STRATEGY_EXEMPT_TRANSFORMS: frozenset[str] = frozenset(
    {"default_uuid", "default_now", "fk_lookup"}
)
```

Definida en `app/core/migration/mappings/__init__.py:89-91`.
**Esta es la única fuente de verdad** — el validador referencia la
constante y este doc la documenta.

### Rationale por transform

| Transform | Por qué exenta | Ejemplo |
|-----------|----------------|---------|
| **`default_uuid`** | La web genera un UUID v4 mecánico para la PK `id`. No hay valor de negocio que preservar (el UUID es identidad sintética, no dato). Forzar `web_only_strategy` aquí duplicaría un mecanismo sin valor. | `id` PK en las 5 tablas |
| **`default_now`** | La web estampa `utcnow()` en INSERT/UPDATE. El valor es timestamp del momento del write — no hay dato legacy del cual derivar y la columna no representa un input de negocio. | `fecha_alta`, `updated_at` en las 5 tablas |
| **`fk_lookup`** | FKs cross-table (`animal_id`, `voluntario_*_id`, `entrada_origen_id`) se resuelven vía `sync_state.json` (mapping `legacy_id ↔ web_uuid`). Declarar `web_only_strategy` aquí sería un mecanismo duplicado — `sync_state` ya es la fuente de verdad para FK resolution. | `animal_id` en `entradas`/`acogidas`/`adopciones`, FKs a `voluntarios` |

### Por qué `default_true` (columna `activo`) NO es exenta

`default_true` aplica a la columna soft-delete `activo`. El web **es
dueña** del flag (`activo=true` al INSERT, `activo=false` al archive);
el legacy no tiene un equivalente directo. Pero esta columna SÍ
representa una decisión de negocio (¿está archivado el animal?),
así que la shadow-state repository necesita saber que el web owns la
columna y que **no** debe intentar reconciliarla con el legacy. La
estrategia correcta es `web_only_strategy: fixed` (declarada
explícitamente en los 5 YAMLs; verificada por
`tests/test_migration.py::TestYamlWebOnlyStrategyRegression::
test_activo_column_declares_fixed_strategy_in_each_yaml`).

### Por qué `identity` / `currency_to_numeric` / `double_to_numeric` NO son exentas

Estos transforms llevan **valores de negocio** (ej: `DNI` con
`identity`, `donativo` con `currency_to_numeric`, `peso_kg` con
`double_to_numeric`). Si la columna es web-only (`legacy_column=null`),
el valor no tiene contraparte legacy pero sí tiene valor de negocio que
el operador espera preservar. Por tanto, el validador exige una
estrategia explícita (`preserve` / `fixed` / `derived`).

### Tabla resumen de decisiones

| Transform | ¿Exenta? | Strategy típica (cuando no exenta) |
|-----------|-----------|-----------------------------------|
| `default_uuid` | ✅ | — |
| `default_now` | ✅ | — |
| `fk_lookup` | ✅ | — |
| `identity` | ❌ | `preserve` (ej: `DNI`), `derived` (ej: estado derivado) |
| `currency_to_numeric` | ❌ | `preserve` (ej: donativos) |
| `double_to_numeric` | ❌ | `preserve` (ej: pesos) |
| `default_true` | ❌ | `fixed` (ej: `activo` soft-delete) |

### Añadir un nuevo transform a la lista exenta

**Criterio**: el transform no debe llevar nunca un valor de negocio
que necesite preservación. Ejemplos válidos: un futuro
`default_zero` para enteros auto-iniciales (sin valor de negocio). NO
válido: añadir `default_true` (ya argumentado arriba).

**Procedimiento**: editar `_STRATEGY_EXEMPT_TRANSFORMS` en
`app/core/migration/mappings/__init__.py`, añadir un test en
`tests/test_migration.py::TestStrictWebOnlyStrategyValidator` que
cubra el caso, y actualizar este doc con el rationale (PR review debe
aprobar el rationale antes de mergear).

## Performance budgets

| Métrica | Objetivo | Cómo se mide |
|---------|----------|--------------|
| Reconciliation por lote de 100 filas | <1s | `MigrationReport.reconciliation_summary.duration_ms < 1000` (spec REQ-Performance) |
| 10k filas × 5 cols preservadas | <10s | `apap-migrate reconcile --check-only` + `--verbose` (spec REQ-Performance) |
| O(1) lookup en `web_only_feature_shadow` | index scan | UNIQUE `(table_name, legacy_pk, web_column)` |

## File changes (PR 4)

| File | Action | Description |
|------|--------|-------------|
| `openspec/changes/web-only-feature-preservation/design.md` | Create | Este doc (cierra P2 #1 del review de PR 3/6). |
| `app/core/migration/reconcile.py` | Modify | Añadir `post_apply_diff()` (T4.1–T4.5). |
| `app/core/migration/reporting.py` | Modify | Añadir `reconciliation_summary: ReconciliationSummary` a `MigrationReport` (T4.6). |
| `tests/test_reconcile.py` | Modify | Tests de integración del hook (T4.7–T4.8). |
| `tests/test_migration.py` | Modify | Test del wire-up `MigrationReport.reconciliation_summary` (T4.6). |
| `openspec/changes/web-only-feature-preservation/tasks.md` | Modify | Marcar T4.1–T4.11 como `[x]` al cierre. |

## Out of scope (PR 5+)

- CLI interactivo `--interactive` con prompts (a/b/c/q) — PR 5.
- Round-trip test E2E con sandbox .accdb real — PR 6.
- Repair pass automático post-fallo de `sync_state.save()` — PR 6.
- Tests de perf (10k filas) — PR 6.

## Referencias

- `openspec/changes/web-only-feature-preservation/specs/web-only-feature-preservation/spec.md` — contrato REQ-Hook, REQ-CLI, REQ-Atomicidad, REQ-YAML, REQ-Performance.
- `app/core/migration/shadow_state.py` — CRUD del shadow state (PR 1).
- `app/core/migration/derivation.py` — derivation engine puro (PR 2).
- `app/core/migration/semantic_events.py` — translator diff→event (PR 2).
- `app/core/migration/reconcile.py` — dispatcher `reconcile_after_legacy_write` (PR 2) + hook `post_apply_diff` (PR 4 — este).
- `app/core/migration/mappings/__init__.py` — `_STRATEGY_EXEMPT_TRANSFORMS` + validador estricto (PR 3).
- `app/core/migration/sync_state.py` — `sync_state.json` + `lookup_web_pk` (MIGRATION-01 PR 4/6).
- `app/core/migration/diff_engine.py` — `Diff` dataclass (MIGRATION-01 PR 4/6).
- `app/core/domain.py::ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL` — schema del log de eventos.
