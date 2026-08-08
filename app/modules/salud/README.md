[← Back to CODEBASE-GUIDE](../../docs/CODEBASE-GUIDE.md)

# Salud

This README documents the domain, tables, endpoints, and risks of the `salud` module. Plus a Spanish opening paragraph that describes the same module.

## The sentence that organizes this module

> El módulo `salud` (HEALTH-04, issue #53) registra las sesiones de terapia aplicadas a cada animal y las recomendaciones operativas que surgen de cada sesión.

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

El módulo `salud` cubre el ciclo de terapia de un animal. Una `terapia` es una sesión registrada con su fecha, descripción, animal y voluntario responsable. Cada `terapia` admite una o varias `recomendaciones` que documentan instrucciones operativas (completar antes de una fecha, revisar X, aplicar Y). El módulo hereda la convención legacy de `TbTerapia` y `TbTerapiaRecomendacion` con dos particularidades: las recomendaciones se completan (no se borran físicamente) y una terapia no se puede desactivar mientras tenga recomendaciones pendientes sin completar.

La validación se ejecuta en un solo CTE por operación de escritura. Esto cierra la ventana TOCTOU entre el check de FK (animal activo, voluntario activo) y la propia escritura. El `RETURNING` del CTE se inspecciona para detectar fallos; cuando devuelve 0 filas se corre una desambiguación que identifica la FK que falló.

## Tables

| Table | Columns (key) | Purpose |
|---|---|---|
| `terapias` | `id` (UUID PK), `animal_id` (UUID FK), `voluntario_id` (UUID FK), `fecha` (date), `descripcion` (text nullable), `activo` (bool), `created_at`, `updated_at` | Sesiones de terapia. FK a `animales` y `voluntarios`, ambos con check de `activo = true` en el CTE. |
| `recomendaciones` | `id` (UUID PK), `terapia_id` (UUID FK), `fecha` (date), `texto` (text), `completada` (bool), `activo` (bool), `created_at` | Recomendaciones operativas ligadas a una terapia. El flag `completada` permite cerrar la recomendación sin borrado físico. |

Las columnas proceden de `app/modules/salud/queries.py` (constantes `TERAPIA_*_COLUMNS` y `RECOMENDACION_*_COLUMNS`).

## Endpoints

El router se monta desde `app/main.py` con los prefijos `/terapias` y `/recomendaciones`. Auth model: GET usa `require_permission(Permission.READ_SALUD)`, escritura usa `Permission.WRITE_SALUD` (issue #144).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/terapias` | READ | Lista de terapias activas. `?animal_id=` filtra por animal. |
| GET | `/terapias/new` | READ | Formulario vacío. |
| POST | `/terapias` | WRITE | Crea terapia. `303` al detalle, `422` en error de validación. |
| GET | `/terapias/{id}` | READ | Detalle con recomendaciones. `404` si falta. |
| GET | `/terapias/{id}/edit` | READ | Formulario de edición. |
| POST | `/terapias/{id}/update` | WRITE | Update. `303` al detalle, `422` en error. |
| POST | `/terapias/{id}/delete` | WRITE | Soft-delete. `409` con recomendaciones pendientes, `404` si falta. |
| GET | `/terapias/{terapia_id}/recomendaciones` | READ | Lista de recomendaciones activas. |
| POST | `/terapias/{terapia_id}/recomendaciones` | WRITE | Crea recomendación. `303` al detalle, `422` en error. |
| PATCH | `/recomendaciones/{id}` | WRITE | Marca como completada (`completada = true`). |
| DELETE | `/recomendaciones/{id}` | WRITE | Soft-delete de recomendación. `404` si falta. |

Los códigos `503` se reservan a fallos `InsForgeError` capturados en la ruta (con `log_safe` previo). El `csrf_token` se inyecta en cada `TemplateResponse` (AGENTS.md §10).

## Service layer

Funciones públicas del módulo (exportadas desde `app/modules/salud/__init__.py`).

- `create_terapia(client, params, *, actor_user_id=None) -> Terapia` — Inserta terapia en un CTE con check atómico de FK activas.
- `list_terapias(client, *, animal_id=None) -> list[Terapia]` — Lista terapias activas (LIMIT 100), con filtro opcional.
- `get_terapia_by_id(client, terapia_id) -> Terapia | None` — Una terapia por id o `None`.
- `update_terapia(client, terapia_id, params, *, actor_user_id=None) -> Terapia | None` — Update en un CTE atómico.
- `delete_terapia(client, terapia_id, *, actor_user_id=None) -> bool` — Soft-delete. `False` si ya estaba inactiva, levanta `TerapiaHasPendingRecomendaciones` si quedan pendientes.
- `create_recomendacion(client, params, *, actor_user_id=None) -> Recomendacion` — Inserta con CTE y FK check sobre terapia activa.
- `list_recomendaciones(client, terapia_id) -> list[Recomendacion]` — Recomendaciones activas de una terapia.
- `get_recomendacion_by_id(client, recomendacion_id) -> Recomendacion | None` — Una recomendación o `None`.
- `complete_recomendacion(client, recomendacion_id, *, actor_user_id=None) -> Recomendacion` — Marca `completada = true`. Levanta `RecomendacionNotFoundError` si falta.
- `delete_recomendacion(client, recomendacion_id, *, actor_user_id=None) -> bool` — Soft-delete idempotente.

Excepciones específicas: `TerapiaHasPendingRecomendaciones`, `TerapiaNotFoundError`, `RecomendacionNotFoundError`. Helpers `_row_to_terapia` y `_row_to_recomendacion` entran en `CRITICAL_HELPERS` (AGENTS.md §11).

## Layer type

Legacy route → service → queries layout. SQL y parámetros viven en `app/modules/salud/queries.py` (seam de AGENTS.md §22). El servicio importa los builders, aplica validación y orquesta la desambiguación. La atomicidad TOCTOU-safe se garantiza con CTE de PostgreSQL que evalúa FK + INSERT bajo el mismo snapshot. Sin estado adicional en memoria: todas las operaciones pasan por SQL.

## Risks and gotchas

- **TOCTOU cerrado por CTE**: el INSERT/UPDATE combina FK checks y escritura en un solo statement. La desambiguación post-CTE no es parte del camino de éxito, solo del de error.
- **Borrado con recomendaciones pendientes**: `delete_terapia` verifica `completada = false AND activo = true` y levanta `TerapiaHasPendingRecomendaciones`. La ruta traduce a `409`.
- **Completado idempotente**: `_COMPLETE_RECOMENDACION_SQL` no distingue "ya completada" de "no existe"; ambos casos devuelven 0 filas y la ruta traduce a `404`.
- **FK activa obligatoria**: `animal_id` y `voluntario_id` deben apuntar a filas activas. Soft-delete de cualquiera de las dos referencias rompe el `INSERT`/`UPDATE` en el CTE.
- **Filtro `LIMIT 100`**: la lista global tiene hard cap. Una sesión con miles de terapias no se descarga en una sola request.

## Cross-references

- `docs/CODEBASE-GUIDE.md` — mapa general.
- `docs/audits/health-data-crud-audit-2026-Q3.md` — auditoría de los CRUD de salud.
- `docs/decisiones-proyecto.md` — D-HEALTH-04 y siguientes.
- AGENTS.md §1 (rutas sin SQL), §9 (log_safe), §11 (CRITICAL_HELPERS), §22 (seam SQL/service).

## Verification checklist

- [ ] Cada endpoint de la tabla existe en `routes.py`.
- [ ] Cada función pública aparece en `__init__.py` o se exporta por convención.
- [ ] Las CTE de escritura aparecen en `queries.py` (no inline en `service.py`).
- [ ] Los eventos de auditoría usan `log_safe` y respetan la lista de redacción (AGENTS.md §9).
- [ ] Las pruebas E2E cubren al menos un caso de borrado con recomendaciones pendientes.
- [ ] Los cross-references resuelven a archivos existentes.
- [ ] El README cabe en 5 minutos.
