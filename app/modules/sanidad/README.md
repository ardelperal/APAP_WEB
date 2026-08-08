[← Back to CODEBASE-GUIDE](../../docs/CODEBASE-GUIDE.md)

# Sanidad

This README documents the domain, tables, endpoints, and risks of the `sanidad` module. Plus a Spanish opening paragraph that describes the same module.

## The sentence that organizes this module

> El módulo `sanidad` registra las actuaciones veterinarias aplicadas a un animal (vacunas, desparasitaciones, analíticas) en modo individual, en lote y como resumen por tipo.

## Quick navigation

| Section | Purpose |
|---|---|
| [Domain](#domain) | Business capability owned by this module |
| [Tables](#tables) | Backend tables, key columns, purpose |
| [Endpoints](#endpoints) | HTTP surface, method, path, auth |
| [Service layer](#service-layer) | Public functions exported by the service |
| [Layer type](#layer-type) | Architecture pattern (legacy vs hexagonal) |
| [Risks and gotchas](#risks-and-gotchas) | Race conditions, edge cases, validations |
| [Cross-references](#cross-references) | Audits, runbooks, decisions |
| [Verification checklist](#verification-checklist) | Pre-merge checks that apply to a module README |

## Domain

El módulo `sanidad` cubre tres casos. HEALTH-01 (issue #50) es el alta, edición y borrado individual de una `actuacion_sanitaria`. HEALTH-02 (issue #51) es el alta por lote con vista previa obligatoria (5+ registros) y commit atómico. HEALTH-03 (issue #52) es el resumen por animal, que devuelve la última actuación de cada tipo (`catalogos_pruebas.observaciones`). Las tres áreas comparten la tabla `actuacion_sanitaria` y el catálogo `catalogos_pruebas`.

La validación de la fecha se rige por la regla D-24 declarada en este slice. La regla tiene tres partes: formato `YYYY-MM-DD`, no futura, y no anterior al `fecha_alta` del animal. Las dos primeras se validan en Python antes de tocar la base. La tercera vive dentro del CTE, junto con los checks de FK (animal activo, voluntario activo, tipo de prueba existente). El módulo espeja la tabla legacy `TbActuacionSanitaria` con la mejora de soft-delete por `activo` y la columna de metadato `material_utilizado`.

## Tables

| Table | Columns (key) | Purpose |
|---|---|---|
| `actuacion_sanitaria` | `id` (UUID PK), `animal_id` (UUID FK), `voluntario_id` (UUID FK nullable), `fecha` (date), `tipo_actuacion_id` (UUID FK nullable), `veterinario` (text), `observaciones` (text), `material_utilizado` (text), `fecha_alta`, `updated_at`, `activo` (bool) | Registro clínico por animal. Las FKs se validan en CTE con check de `activo = true` (animal y voluntario). |
| `catalogos_pruebas` | `id` (UUID PK), `codigo`, `observaciones` (text, agrupa el tipo), `periodicidad_meses` (int nullable), `especie` (text nullable) | Catálogo de tipos de prueba (CATALOG-01, #65). `observaciones` es la dimensión que `get_resumen_sanitario` usa como bucket. |

Las columnas proceden de `app/modules/sanidad/service.py` (`_WRITE_COLUMNS`, `_SELECT_COLUMNS`) y de `app/modules/sanidad/queries.py` (`BATCH_WRITE_COLUMNS`, `BUILD_RESUMEN_SANITARIO_SQL`).

## Endpoints

Los routers se montan desde `app/main.py` con el prefijo `/sanidad` (HEALTH-01) y `/sanidad/...` (HEALTH-02). Auth model: GET usa `require_permission(Permission.READ_SALUD)`, escritura usa `Permission.WRITE_SALUD` (issue #144). El endpoint de resumen HEALTH-03 vive en `app/modules/animals/routes.py` (prefijo `/animales`) y delega en `get_resumen_sanitario` de este módulo.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/sanidad` | READ | Lista de actuaciones activas. `?animal_id=` filtra por animal (LIMIT 100). |
| GET | `/sanidad/new` | READ | Formulario vacío con dropdown de `catalogos_pruebas`. |
| POST | `/sanidad` | WRITE | Crea actuación. `303` al detalle, `422` en validación, `503` en `InsForgeError`. |
| GET | `/sanidad/{id}` | READ | Detalle con el `tipo_actuacion` resuelto del catálogo. |
| GET | `/sanidad/{id}/edit` | READ | Formulario de edición prefilled. |
| POST | `/sanidad/{id}/update` | WRITE | Update. Mismo contrato 303/422/503 que el alta. |
| POST | `/sanidad/{id}/delete` | WRITE | Soft-delete. `404` si falta. |
| GET | `/sanidad/batch/new` | READ | Formulario vacío con 5 filas (`BATCH_MIN_RECORDS`). |
| POST | `/sanidad/actuaciones/batch` | WRITE | Lote atómico. `dry_run=true` previsualiza sin commit. `422` por debajo de 5 registros o por validación fallida. `303` en commit correcto. |
| GET | `/animales/{animal_id}/salud/resumen` | READ | Resumen de la última actuación por tipo para un animal. La ruta HTTP vive en `app/modules/animals/routes.py`; la función `get_resumen_sanitario` se importa desde `app.modules.sanidad`. |

Los códigos `503` mapean `InsForgeError`; el `csrf_token` se inyecta por `csrf_token_context_processor` (AGENTS.md §10).

## Service layer

Funciones públicas del módulo (exportadas desde `app/modules/sanidad/__init__.py`).

- `create_actuacion_sanitaria(client, params, *, actor_user_id=None) -> ActuacionSanitaria` — CTE con FK + D-24 regla 3.
- `list_actuaciones_sanitarias(client, *, animal_id=None) -> list[ActuacionSanitaria]` — Lista global o por animal. Hard LIMIT 100.
- `list_catalogos_pruebas(client) -> list[dict]` — Reexporta el catálogo para los formularios.
- `list_catalogos_periodicidad(client) -> list[dict]` — Reglas de periodicidad por especie (HEALTH-06, #55).
- `get_actuacion_sanitaria_by_id(client, actuacion_id) -> ActuacionSanitaria | None` — Una actuación o `None`.
- `update_actuacion_sanitaria(client, actuacion_id, params, *, actor_user_id=None) -> ActuacionSanitaria | None` — Update en CTE atómico.
- `delete_actuacion_sanitaria(client, actuacion_id, *, actor_user_id=None) -> bool` — Soft-delete idempotente.
- `search_actuaciones_by_animal(client, animal_id) -> list[ActuacionSanitaria]` — Lista por animal (LIMIT 100).
- `get_resumen_sanitario(client, animal_id) -> SaludResumen` — HEALTH-03. Una fila por `catalogos_pruebas.observaciones` con la última fecha y resultado.

Funciones del sub-módulo de lote (`batch_service`).

- `commit_batch(client, records, *, actor_user_id=None) -> BatchResult` — Commit CTE único. Levanta `BatchValidationError` si cualquier fila falla.
- `preview_batch(client, records) -> BatchPreview` — Mismo CTE con `dry_run=true`. Nunca levanta `BatchValidationError`.

Excepciones específicas: `BatchValidationError` (con `failed_indices` y `reasons`). Helpers `_row_to_actuacion_sanitaria` entran en `CRITICAL_HELPERS` (AGENTS.md §11).

## Layer type

Legacy route → service → queries layout. SQL y parámetros viven en `app/modules/sanidad/queries.py` (seam de AGENTS.md §22). El servicio importa los builders, aplica validación y orquesta la desambiguación. HEALTH-02 vive en `batch_service.py` y `batch_routes.py` para mantener cada archivo por debajo del límite de 700 líneas (AGENTS.md §21). La atomicidad del lote se garantiza con un CTE único que evalúa todas las filas y la INSERT bajo el mismo snapshot; el gate `bool_and(is_valid)` impide el commit parcial. La atomicidad del CRUD individual usa el mismo patrón a nivel de una fila.

## Risks and gotchas

- **D-24 regla 3 dentro del CTE**: la fecha no anterior a `animales.fecha_alta` se evalúa junto con la INSERT, no antes. Una desambiguación post-CTE traduce el fallo a mensaje en español.
- **Atomicidad del lote**: `bool_and(is_valid)` en el CTE impide commit parcial. Un solo registro inválido descarta los demás sin escribir nada. `dry_run=true` invierte el filtro para previsualizar sin commit.
- **Límite por defecto de 5 registros**: `BATCH_MIN_RECORDS = 5` se aplica en la ruta. El servicio acepta cualquier `n >= 1` para importadores programáticos.
- **Filtros FK activa**: `voluntario_id` y `tipo_actuacion_id` opcionales. Cuando se proporcionan, deben apuntar a filas activas (FK check dentro del CTE).
- **Catálogo species-aware**: `catalogos_pruebas.especie` puede ser `NULL` (todas), `canina` o `felina`. `list_catalogos_periodicidad` lo usa para resolver periodicidades por especie.

## Cross-references

- `docs/CODEBASE-GUIDE.md` — mapa general.
- `docs/audits/health-data-crud-audit-2026-Q3.md` — auditoría CRUD sanidad/salud.
- `docs/decisiones-proyecto.md` — D-24 y D-HEALTH-01..05.
- AGENTS.md §1 (rutas sin SQL), §9 (log_safe), §11 (CRITICAL_HELPERS), §21 (presupuesto 700 líneas), §22 (seam SQL/service), §23 (E2E).

## Verification checklist

- [ ] Cada endpoint de la tabla existe en `routes.py` o `batch_routes.py`.
- [ ] Cada función pública aparece en `__init__.py`.
- [ ] El CTE de `build_batch_insert` mantiene el gate `bool_and`.
- [ ] Los eventos de auditoría usan `log_safe` y respetan la redacción (AGENTS.md §9).
- [ ] Al menos un test E2E cubre el camino `dry_run=true` → `dry_run=false` del lote.
- [ ] Los cross-references resuelven a archivos existentes.
- [ ] El README cabe en 5 minutos.
