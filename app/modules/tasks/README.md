[← Back to CODEBASE-GUIDE](../../docs/CODEBASE-GUIDE.md)

# Tasks

This README documents the domain, tables, endpoints, and risks of the `tasks` module. Plus a Spanish opening paragraph that describes the same module.

## The sentence that organizes this module

> El módulo `tasks` es el motor de tareas de la protectora: una cola de pendientes manuales y automáticos (vacunas, revisiones, seguimientos) con responsable, prioridad y estado.

## Quick navigation

| Section | Purpose |
|---|---|
| [Domain](#domain) | Business capability owned by this module |
| [Tables](#tables) | Backend tables, key columns, purpose |
| [Endpoints](#endpoints) | HTTP surface, method, path, auth |
| [Service layer](#service-layer) | Public functions exported by the service |
| [Rule engine](#rule-engine) | Automatic-task generation rules |
| [Layer type](#layer-type) | Architecture pattern (legacy vs hexagonal) |
| [Risks and gotchas](#risks-and-gotchas) | Race conditions, edge cases, validations |
| [Cross-references](#cross-references) | Audits, runbooks, decisions |
| [Verification checklist](#verification-checklist) | Pre-merge checks that apply to a module README |

## Domain

El módulo `tasks` (issue #7) cubre dos caras del trabajo pendiente. La primera es la cola de tareas en sí: cada fila es una unidad de trabajo con un `tipo`, un `origen`, una `prioridad`, un `estado`, un `responsable_id` opcional y, cuando aplica, un `vencimiento_at`. La segunda es el motor de reglas automáticas que produce borradores (`TareaDraft`) a partir de eventos del dominio: vacunas próximas a vencer, seguimientos post-adopción sin completar, esterilizaciones pendientes.

Las tareas tienen ciclo de vida. Nacen en `pendiente`, pasan por `en_progreso`, terminan en `completada` o `cancelada`. El estado `vencida` es un derivado temporal que el sistema asigna cuando `vencimiento_at < now()`. El cierre es exclusivo: solo se cierra desde `pendiente` o `en_progreso`. Cerrar desde cualquier otro estado levanta `CerrarTareaError`.

## Tables

| Table | Columns (key) | Purpose |
|---|---|---|
| `tarea` | `id` (UUID PK), `tipo` (text, `TipoTarea`), `origen` (text, `OrigenTarea`), `prioridad` (text, `PrioridadTarea`), `estado` (text, `EstadoTarea`), `responsable_id` (UUID nullable), `vencimiento_at` (timestamp nullable), `vinculo_tipo` (text nullable), `vinculo_id` (UUID nullable), `metadata` (jsonb nullable), `created_at`, `updated_at` | Cola de tareas. `vinculo_tipo` + `vinculo_id` apuntan al sujeto (animal, adopción, etc). `metadata` carga contexto por tipo (días hasta vencimiento, especie, etc). |

Las columnas proceden de `app/modules/tasks/queries.py` (constantes `_WRITE_COLUMNS` y `_SELECT_COLUMNS`).

## Endpoints

El router se monta desde `app/main.py` con el prefijo `/tareas`. Auth model: todos los endpoints usan `require_authorized_user` (issue #144).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/tareas` | READ | Lista tareas con filtros opcionales (`estado`, `responsable_id`, `vinculo_tipo`, `vinculo_id`). |
| GET | `/tareas/{id}` | READ | Detalle de una tarea. `302` a `/tareas` si no existe. |
| POST | `/tareas` | READ | Crea tarea manual desde formulario. `302` a `/tareas`. |
| POST | `/tareas/{id}/asignar` | READ | Asigna o desasigna responsable. `302` al detalle. |
| POST | `/tareas/{id}/cerrar` | READ | Cierra la tarea (`completada`). Acepta `comentario` opcional. `302` al detalle. |

Las rutas de escritura usan `require_authorized_user` (sin `require_writer_user`) porque cualquier operador con sesión puede registrar tareas manuales. La validación CSRF la aplica `CsrfMiddleware` por cabecera `X-CSRFToken` o campo `csrf_token` (AGENTS.md §10).

## Service layer

Funciones públicas del módulo (exportadas desde `app/modules/tasks/__init__.py`).

- `crear_tarea(client, *, tipo, origen, prioridad, responsable_id, vencimiento_at, vinculo_tipo, vinculo_id, metadata) -> str` — Crea tarea. Devuelve el UUID. Valida los enums `TipoTarea`, `OrigenTarea`, `PrioridadTarea`.
- `listar_tareas(client, *, estado, responsable_id, vinculo_tipo, vinculo_id, limit, offset) -> list[Tarea]` — Lista con filtros. Orden por bucket de estado, `vencimiento_at`, `created_at DESC`. Hard cap configurable.
- `obtener_tarea(client, *, tarea_id) -> Tarea | None` — Una tarea o `None`.
- `actualizar_estado(client, *, tarea_id, nuevo_estado) -> Tarea` — Cambia estado. Levanta `ValueError` si la tarea no existe.
- `asignar_tarea(client, *, tarea_id, responsable_id) -> Tarea` — Asigna o desasigna. Levanta `ValueError` si no existe.
- `cerrar_tarea(client, *, tarea_id, comentario) -> Tarea` — Cierra a `completada`. Valida estado origen (`pendiente` o `en_progreso`). Levanta `CerrarTareaError` si el estado no permite cierre.

Enums exportados: `TipoTarea`, `EstadoTarea`, `PrioridadTarea`, `OrigenTarea`. Excepción específica: `CerrarTareaError`. Helper `_row_to_tarea` entra en `CRITICAL_HELPERS` (AGENTS.md §11).

## Rule engine

El motor de reglas vive en `app/modules/tasks/rules.py` y se compone de tres stubs MVP.

- `rule_vacuna_vencimiento(context) -> list[TareaDraft]` — Vacunas con vencimiento dentro de 7 días, prioridad `alta`.
- `rule_seguimiento_post_adopcion(context) -> list[TareaDraft]` — Adopciones de más de 30 días sin seguimiento posterior, prioridad `normal`.
- `rule_esterilizacion_pendiente(context) -> list[TareaDraft]` — Machos de más de 1 año sin esterilizar, prioridad `normal`.

El motor no escribe en la base: devuelve borradores (`TareaDraft`) que un job programado o un trigger manual persiste. La lista `TASK_RULES` es el registro invocable. La implementación real de cada regla queda diferida al primer MVC (los stubs validan la forma del contexto y emiten drafts correctos para datos sintéticos).

## Layer type

Legacy route → service → queries layout. SQL y parámetros viven en `app/modules/tasks/queries.py` (seam de AGENTS.md §22). El motor de reglas importa solo `TareaDraft` desde `app/core/tasks/rules.py` (re-exportado por `__init__.py`) y no toca SQL. La capa de servicio no emite `log_safe` por operación (las reglas automáticas no son auditables al nivel de las entradas manuales); las escrituras desde las reglas deben añadir el evento cuando se implemente el job programado.

## Risks and gotchas

- **Cerrar en estado inválido**: `cerrar_tarea` exige estado `pendiente` o `en_progreso`. Otros estados levantan `CerrarTareaError`. La ruta actual ignora la excepción con un `pass` — pendiente refactor para surfacing 409.
- **Filtros sin validación de enum**: la ruta acepta cualquier string en `estado` y `responsable_id`; la validación cae sobre el servicio (`_coerce_estado`). Un filtro inválido devuelve lista vacía en vez de error visible.
- **Estado `vencida` no se asigna automáticamente**: el listado ordena por `vencimiento_at` y por bucket, pero no marca como `vencida` en la base. La derivación se hace en la consulta, no en escritura.
- **Sin evento de auditoría en cierre**: el `log_safe` no se emite desde `cerrar_tarea`. Aceptable para MVP; revisar cuando se integre el job automático de reglas.
- **Reglas MVP stubs**: las tres reglas son funcionales sobre datos sintéticos pero la implementación completa del job programado queda pendiente.

## Cross-references

- `docs/CODEBASE-GUIDE.md` — mapa general.
- `docs/proceso.md` — playbook del proyecto.
- `app/core/tasks/rules.py` — motor de reglas re-exportado.
- AGENTS.md §1 (rutas sin SQL), §11 (CRITICAL_HELPERS), §22 (seam SQL/service).

## Verification checklist

- [ ] Cada endpoint de la tabla existe en `routes.py`.
- [ ] Cada función pública aparece en `__init__.py` o se exporta por convención.
- [ ] El enum `EstadoTarea` se valida al transicionar (no se acepta string libre).
- [ ] El cierre de tarea respeta la guarda de estado origen.
- [ ] El motor de reglas no importa SQL ni toca la base directamente.
- [ ] Los cross-references resuelven a archivos existentes.
- [ ] El README cabe en 5 minutos.
