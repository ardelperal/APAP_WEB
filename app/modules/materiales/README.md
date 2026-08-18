[← Back to CODEBASE-GUIDE](../../docs/CODEBASE-GUIDE.md)

# Materiales

This README documents the domain, tables, endpoints, and risks of the `materiales` module. Plus a Spanish opening paragraph that describes the same module.

## The sentence that organizes this module

> El módulo `materiales` es el catálogo de bienes físicos que la protectora asigna a cada estancia de acogida, junto con la cantidad y notas asociadas.

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

El módulo `materiales` (FOSTER-04, issue #46) cubre dos áreas. La primera es el catálogo de materiales: mantas, transportines, correas, arneses y demás enseres físicos que la protectora presta a las casas de acogida. La segunda es la tabla de unión `estancia_materiales` que registra qué material se asignó a cada estancia, en qué cantidad y con qué notas. El catálogo espeja la tabla legacy `TbMaterial` y conserva la clave natural `material + tamano + color` con la restricción `UNIQUE` que la legacy ya imponía.

La asignación respeta dos invariantes. Un material solo se asigna a una estancia activa sin `fecha_final`. Un material solo se asigna si sigue activo en el catálogo. Ambas comprobaciones viven en el servicio y se ejecutan antes del `INSERT` para evitar escrituras inválidas.

## Tables

| Table | Columns (key) | Purpose |
|---|---|---|
| `materiales` | `id` (UUID PK), `material` (text), `tamano` (text), `color` (text), `observaciones` (text nullable), `activo` (bool), `fecha_alta`, `fecha_baja`, `updated_at` | Catálogo de enseres físicos. Clave natural `UNIQUE (material, tamano, color)`. |
| `estancia_materiales` | `id` (UUID PK), `estancia_id` (UUID FK), `material_id` (UUID FK), `cantidad` (int), `notas` (text nullable), `fecha_alta`, `activo` (bool) | Asignación material-estancia. Índice parcial `estancia_materiales_active_unique (estancia_id, material_id) WHERE activo = true`. |

Las columnas proceden de `app/modules/materiales/queries.py` (constantes `MATERIAL_*_COLUMNS` y `JUNCTION_*_COLUMNS`) y de los `RETURNING` del servicio (`app/modules/materiales/service.py`).

## Endpoints

Los routers se montan desde `app/main.py` con los prefijos `/materiales` y `/acogidas` (sub-router `acogida_routes`). Auth model: GET usa `require_permission(Permission.READ_MATERIALES)`, POST usa `Permission.WRITE_MATERIALES` (issue #144, REQ-FOSTER-04-03).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/materiales` | READ | List active catalog rows ordered by `fecha_alta DESC`. |
| GET | `/materiales/new` | READ | Empty create form. |
| POST | `/materiales` | WRITE | Create. `303` on success, `409` on duplicate natural-key, `422` on validation. |
| GET | `/materiales/{id}` | READ | Detail view. `404` when the id is missing. |
| GET | `/materiales/{id}/edit` | READ | Edit form prefilled. |
| POST | `/materiales/{id}/edit` | WRITE | Update. Same 303/409/422 contract as create. |
| POST | `/materiales/{id}/deactivate` | WRITE | Soft-delete. `303` on success, `404` on missing or already inactive. |
| GET | `/acogidas/{estancia_id}/materiales` | READ | Per-stay junction list. |
| POST | `/acogidas/{estancia_id}/materiales` | WRITE | Assign material to stay. `303` on success, `409` on duplicate, `422` on invalid FK. |
| POST | `/acogidas/{estancia_id}/materiales/{mid}/delete` | WRITE | Remove junction row. `303` on success, `404` on missing or already inactive. |

Códigos `409` se reservan a `MaterialConflictError` con mensaje en español. Códigos `422` se reservan a errores `ValueError` desde el servicio (campo obligatorio vacío, estancia cerrada, material inactivo, `cantidad` inválida). El `csrf_token` se inyecta en cada `TemplateResponse` por `csrf_token_context_processor` (AGENTS.md §10).

## Service layer

Funciones públicas del módulo (exportadas desde `app/modules/materiales/__init__.py`).

- `create_material(client, params) -> Material` — Inserta un material. Traduce `InsForgeError(23505)` a `MaterialConflictError`.
- `get_material_by_id(client, material_id) -> Material | None` — Devuelve un material por id o `None`.
- `list_materials(client, activos_solo=True) -> list[Material]` — Lista por `fecha_alta DESC`. `activos_solo=False` incluye inactivos.
- `update_material(client, material_id, params) -> Material | None` — Update parcial. Misma traducción de `23505` a `MaterialConflictError`.
- `deactivate_material(client, material_id) -> bool` — Soft-delete atómico. Cascada de desactivación sobre `estancia_materiales`.
- `assign_material_to_estancia(client, estancia_id, material_id, cantidad=1, notas=None) -> EstanciaMaterial` — Asigna material a estancia. Valida estancia activa y material activo antes del `INSERT`.
- `list_materials_for_estancia(client, estancia_id, activos_solo=True) -> list[EstanciaMaterial]` — Lista las asignaciones activas de una estancia.
- `remove_material_from_estancia(client, junction_id) -> bool` — Soft-delete idempotente de una asignación.

Las funciones `_row_to_material`, `_row_to_estancia_material`, `_is_unique_violation`, `_validate_estancia_open_and_active` y `_validate_material_active` son helpers internos. Las dos primeras entran en el gate `CRITICAL_HELPERS` (AGENTS.md §11) y requieren cobertura al 100 %.

## Layer type

Legacy route → service → queries layout. SQL y parámetros viven en `app/modules/materiales/queries.py` (seam de AGENTS.md §22). El servicio importa esos builders, aplica validación de dominio y habla con `SqlExecutor`. Las rutas son HTTP glue. La función de cascada `deactivate_material` ejecuta dos `UPDATE` secuenciales: primero el catálogo, después la cascada. El módulo está en el `BASELINE` del gate de 700 líneas (AGENTS.md §21) por `service.py` (367 líneas) — no debe crecer.

## Risks and gotchas

- **Carrera TOCTOU en desactivación**: dos llamadas concurrentes a `deactivate_material` con el mismo `material_id` producen exactamente un `True` y un `False` (row lock PostgreSQL, `WHERE id = $1 AND activo = true`).
- **Cascada no transaccional**: el catálogo y la cascada se ejecutan como dos `UPDATE` separados. Si la cascada falla, el material queda inactivo pero las asignaciones pueden seguir activas (defensa en profundidad vía el servicio).
- **Conflicto de clave natural**: `UNIQUE (material, tamano, color)` es DB-enforced. La ruta traduce `23505` a `MaterialConflictError` → 409 con mensaje en español (`service.py::_is_unique_violation`).
- **Asignación a estancia cerrada o inactiva**: rechazada en el servicio con 422 (`_validate_estancia_open_and_active`).
- **Cantidad no entera o negativa**: rechazada en el builder `queries._validate_cantidad` antes del SQL.

## Cross-references

- `docs/CODEBASE-GUIDE.md` — mapa general del repo.
- `docs/runbooks/foster-04-materiales-unique-index-failure.md` — intervención cuando el índice parcial `estancia_materiales_active_unique` no se crea en una migración.
- `docs/proceso.md` — playbook del proyecto (P1 fidelidad a `TbMaterial`).
- `docs/architecture/decisiones-proyecto.md` — decisiones D-FOSTER-04.
- AGENTS.md §1 (rutas sin SQL), §11 (CRITICAL_HELPERS), §22 (seam SQL/service), §33 (futuro hexagonal).

## Verification checklist

Esta lista aplica al README de un módulo. Marque lo ejecutado.

- [ ] Cada endpoint de la tabla existe en `routes.py` o `acogida_routes.py`.
- [ ] Cada función pública del servicio está exportada en `__init__.py`.
- [ ] Las tablas referenciadas existen en el schema (`app/core/migration/`).
- [ ] Los cross-references resuelven a archivos existentes.
- [ ] El README cabe en 5 minutos de lectura.
- [ ] No hay marketing fluff ni anglicismos innecesarios.
- [ ] Las notas sobre TOCTOU y cascada siguen vigentes (refactor defensivo si cambian).
