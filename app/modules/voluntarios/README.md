[← Back to CODEBASE-GUIDE](../../docs/CODEBASE-GUIDE.md)

# Voluntarios

This README documents the domain, tables, endpoints, and risks of the `voluntarios` module. Plus a Spanish opening paragraph that describes the same module.

## The sentence that organizes this module

> El módulo `voluntarios` (VOL-01) da de alta y mantiene el registro de personas voluntarias con sus teléfonos, email, DNI y roles operativos.

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

El módulo `voluntarios` cubre el alta, consulta y baja lógica de las personas voluntarias. La tabla `voluntarios` es el registro maestro: nombre obligatorio, dos teléfonos, email y DNI opcionales, todos con `activo` para el soft-delete. La tabla `roles_voluntario` es la unión que asigna uno o varios roles operativos (`intake`, `seguimiento`, `acogida`, `salud`) a cada voluntario activo.

La validación previa al SQL exige nombre no vacío y email con formato básico cuando se proporciona. La unicidad de `email` y `DNI` queda en manos de la base de datos: un duplicado propaga el `BackendError` y la ruta lo traduce a `409` con mensaje en español. El borrado es siempre lógico: se preservan las FK de intakes, estancias de acogida, adopciones y terapias para no romper la trazabilidad histórica.

## Tables

| Table | Columns (key) | Purpose |
|---|---|---|
| `voluntarios` | `id` (UUID PK), `Voluntario` (text, nombre), `Tel1` (text nullable), `Tel2` (text nullable), `Email` (text UNIQUE nullable), `DNI` (text UNIQUE nullable), `fecha_alta`, `updated_at`, `activo` (bool) | Registro maestro. `Email` y `DNI` con `UNIQUE` para deduplicación (VOL-03). |
| `roles_voluntario` | `voluntario_id` (UUID FK), `tipo_rol` (text, `RolVoluntario`) | Asignación de roles operativos. Junction con `tipo_rol` validado en el enum. |

Las columnas proceden de `app/modules/voluntarios/service.py` (`_INSERT_COLUMNS`, `_SELECT_COLUMNS`).

## Endpoints

El router se monta desde `app/main.py` con el prefijo `/voluntarios`. Auth model: GET usa `require_permission(Permission.READ_VOLUNTARIOS)`, escritura usa `Permission.WRITE_VOLUNTARIOS` (issue #144).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/voluntarios` | READ | Lista de voluntarios activos ordenados alfabéticamente. |
| GET | `/voluntarios/new` | READ | Formulario vacío de alta. |
| POST | `/voluntarios` | WRITE | Crea voluntario. `303` al detalle, `409` en email o DNI duplicado, `422` en validación. |
| GET | `/voluntarios/{id}` | READ | Detalle con la lista de roles. `404` si falta. |
| POST | `/voluntarios/{id}/deactivate` | WRITE | Soft-delete. `303` a la lista, `404` si falta o ya estaba inactivo. |

El `csrf_token` se inyecta en cada `TemplateResponse` por `csrf_token_context_processor` (AGENTS.md §10).

## Service layer

Funciones públicas del módulo (exportadas desde `app/modules/voluntarios/__init__.py`).

- `create_voluntario(client, params) -> Voluntario` — Valida nombre y formato de email. Inserta y devuelve la fila. Propaga `BackendError` sin cambios para que la ruta traduzca a 409.
- `list_voluntarios(client) -> list[Voluntario]` — Lista alfabética de activos.
- `get_voluntario_by_id(client, voluntario_id) -> Voluntario | None` — Un voluntario por id o `None`.
- `list_roles(client, voluntario_id) -> list[str]` — Roles asignados al voluntario, ordenados.
- `deactivate_voluntario(client, voluntario_id) -> bool` — Soft-delete atómico. `False` si no existe o ya estaba inactivo.

Enum exportado: `RolVoluntario` (intake, seguimiento, acogida, salud). `VALID_ROL_TYPES` se deriva del enum (AGENTS.md §4, fuente única). Helpers `_row_to_voluntario`, `_validate_create_params` y `_build_insert_params` entran en `CRITICAL_HELPERS` (AGENTS.md §11).

## Layer type

Legacy route → service layout sin `queries.py`. El módulo es uno de los previos al seam de AGENTS.md §22: SQL y validación conviven en `service.py`. El patrón destino está en `app/modules/animals/adapters/local-backend/`.

## Risks and gotchas

- **TOCTOU cerrado en `deactivate_voluntario`**: el `UPDATE` con `WHERE id = $1 AND activo = true RETURNING id` pliega el check de existencia bajo el row lock de PostgreSQL. Dos llamadas concurrentes producen exactamente un `True` y un `False`. El adaptador de animales usa el mismo patrón de soft-delete atómico.
- **Duplicado de email o DNI**: la base impone `UNIQUE`. Un duplicado propaga `BackendError` y la ruta traduce a `409` con mensaje en español.
- **Validación de email superficial**: la regla `_validate_create_params` solo exige presencia de `@`. La validación real (RFC 5322, dominio válido) queda pendiente.
- **Borrado preserva FK**: desactivar un voluntario no rompe las referencias de intakes, estancias, adopciones ni terapias. La trazabilidad histórica se mantiene.
- **Roles no se validan en este módulo**: la asignación de `roles_voluntario` pertenece a otro slice. `list_roles` es de solo lectura y devuelve los `tipo_rol` ya almacenados.

## Cross-references

- `docs/CODEBASE-GUIDE.md` — mapa general.
- `docs/proceso.md` — playbook del proyecto.
- `docs/legacy-volunteer-roles.md` — reglas operativas legacy (BR2 del discovery).
- AGENTS.md §1 (rutas sin SQL), §4 (fuente única por dominio), §11 (CRITICAL_HELPERS), §22 (seam SQL/service — pendiente aplicar), §32.P1 (perímetro — ver refuerzo de normalización de email en frontera).

## Verification checklist

- [ ] Cada endpoint de la tabla existe en `routes.py`.
- [ ] Cada función pública aparece en `__init__.py` o se exporta por convención.
- [ ] El patrón TOCTOU del `UPDATE` no se ha refactorizado a `SELECT` + `UPDATE` (engram:14518 ya lo marcó).
- [ ] La ruta traduce `BackendError(status_code=409)` a 409 con mensaje en español.
- [ ] Los cross-references resuelven a archivos existentes.
- [ ] El README cabe en 5 minutos.
