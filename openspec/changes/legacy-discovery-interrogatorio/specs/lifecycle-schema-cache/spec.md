# Spec: LIFECYCLE-02 — Schema Append-Only + Cache Materializado (issue #69, task 3.1b)

## Context

Issue #69. Crear tabla `animal_lifecycle_events` (append-only log de eventos de
ciclo de vida) y `animal_current_state` (cache materializado del estado actual).
Este slice ya está **implementado y mergeado** — esta spec documenta el estado final.

## Current state on main@0ab533d

**[x] IMPLEMENTED.** PR #320 (`0049708`) mergeado. El commit `0049708` creó:

- Tabla `animal_lifecycle_events` (12 columnas + 14-event CHECK + 2 índices).
  Columnas: `id`, `nchip`, `event_type`, `fecha_evento`, `fecha_creacion`,
  `id_entrada`, `id_acogida`, `id_adopcion`, `id_animal`, `notas`, `operador_user_id`,
  `activo`. CHECK constraint `event_type IN ('entrada_creada', 'entrada_cerrada',
  'acogida_iniciada', 'acogida_cerrada', 'adopcion_registrada', 'adopcion_devolucion',
  'fallecimiento_registrado', 'animal_reactivado', 'chip_cambiado', 'situacion_cerrada',
  'estado_calculado', 'observacion_manual')`.
- Tabla `animal_current_state` (11 columnas). Cache materializado del estado actual.
  Columnas: `nchip`, `current_state`, `cached_at`, `entrada_activa_id`, `acogida_activa_id`,
  `adopcion_activa_id`, `ultima_entrada_fecha`, `ultima_entrada_tipo`, `fecha_defuncion`,
  `fallback_situacion_legacy`, `cache_version`.
- Trigger o servicio `evaluate_causal_pair` que mantiene la consistencia entre el
  append-only log y el cache.

**Validación de la implementación:** Los tests de integración para este feature
fueron **eliminados por el revert #329**. La funcionalidad sigue en el schema
pero los tests específicos de la tabla no existen en el codebase actual.

## Required contract

El schema creado por PR #320:

### `animal_lifecycle_events`

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `id` | UUID | PK |
| `nchip` | TEXT | FK → animals.nchip |
| `event_type` | TEXT | CHECK IN (14 eventos) |
| `fecha_evento` | DATE | Fecha del evento |
| `fecha_creacion` | TIMESTAMPTZ | Timestamp de registro |
| `id_entrada` | UUID | FK opcional → entradas |
| `id_acogida` | UUID | FK opcional → acogidas |
| `id_adopcion` | UUID | FK opcional → adopciones |
| `id_animal` | UUID | FK → animals.id |
| `notas` | TEXT | Notas opcionales |
| `operador_user_id` | TEXT | Operador que registró |
| `activo` | BOOLEAN | Soft-delete |

Índices: `UNIQUE (nchip, event_type, fecha_evento)` + `INDEX (nchip, fecha_evento DESC)`.

### `animal_current_state`

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `nchip` | TEXT | PK, FK → animals.nchip |
| `current_state` | TEXT | Estado calculado |
| `cached_at` | TIMESTAMPTZ | Última actualización del cache |
| `entrada_activa_id` | UUID | FK opcional → entradas |
| `acogida_activa_id` | UUID | FK opcional → acogidas |
| `adopcion_activa_id` | UUID | FK opcional → adopciones |
| `ultima_entrada_fecha` | DATE | Última fecha de entrada |
| `ultima_entrada_tipo` | TEXT | Tipo de última entrada |
| `fecha_defuncion` | DATE | Fecha de defunción (si existe) |
| `fallback_situacion_legacy` | TEXT | Estado legacy para fallback |
| `cache_version` | INTEGER | Versión del cache |

## Dependencies

- Ninguna — es un feature standalone que provee infraestructura para 3.1 (state resolver).

## Acceptance criteria

> **Nota:** Acceptance es `[x]` para el schema. Los tests de integración fueron
> eliminados por el revert #329. Antes de اعتبار هذا feature como completo,
> regenerar los tests en un slice dedicado.

- [x] Schema `animal_lifecycle_events` creado con 12 columnas + CHECK + índices.
- [x] Schema `animal_current_state` creado con 11 columnas.
- [x] Servicio `evaluate_causal_pair` mantiene consistencia.
- [ ] Tests de integración regenerados (bloqueado por #329 revert).

## Out-of-scope

- Tests de integración (eliminados por revert #329 — regenerar en slice separado).
- UI de timeline para la ficha animal.
