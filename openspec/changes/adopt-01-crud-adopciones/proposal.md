# Propuesta: ADOPT-01 — CRUD de adopciones

skill_resolution: paths-injected

## Intención

Issue #47 cierra el primer slice de adopciones: modelar la entidad **Adopción** (legacy `TbAdopcion`) con su dominio propio, separada de la estancia (`acogidas`) y del animal (`animales`). Permite a APAP registrar el hito de "este animal deja la protectora con esta familia", preservando datos del adoptante (nombre obligatorio + DNI / teléfono / email opcionales), el voluntario de seguimiento, las fechas relevantes (adopción + devolución cuando la familia devuelve al animal), los donativos (pre-adopción + adopción) y un enlace opcional a la entrada que originó la adopción.

El módulo soporta el flujo operativo real (pre-adopción, adopción regular, judicial, devoluciones) sin obligar al operador a entrar a Access para tocar la tabla original.

## Alcance

### Dentro

- Módulo `app/modules/adopciones/` con `service.py` + `routes.py` + `__init__.py`.
- `Adopcion` dataclass frozen + slots con 14 campos del schema + `is_active` derivado de `fecha_devolucion`.
- `create_adopcion`, `list_adopciones`, `get_adopcion_by_id`, `update_adopcion`, `delete_adopcion` (soft-delete atómico).
- `search_adopciones_by_adoptante(client, nombre_parcial: str)` para el criterio de aceptación "búsqueda por nombre funciona" (ILIKE `%parcial%`).
- Validación de FKs con check `activo = true` para `animal_id` (obligatorio + activo) y `voluntario_seguimiento_id` (opcional + activo per VOL-05).
- 7 endpoints HTTP: list, new, create, detail, edit, update, delete — todos con `require_authorized_user` (key_user puede escribir per #144).
- 3 templates: `adopciones/list.html`, `adopciones/form.html` (compartido create/edit), `adopciones/detail.html`.
- Nav link "Adopciones" en `app/templates/base.html`.
- Tests TDD: 25 atoms service (validation, FK checks, soft-delete, search, is_active) + 12 atoms routes (auth, CSRF, redirects, no SQL en routes).
- Decisión sobre "tipos de adopción" (regular / pre-adopción / judicial) documentada en D-ADOPT-01.
- `log_safe` para eventos `adopciones.created`, `adopciones.updated`, `adopciones.deleted` con campos no sensibles.
- Actualizar `docs/roadmap.md` y cerrar #47 con SHA + trazabilidad.

### Fuera

- Migración de datos desde `TbAdopcion` legacy (scope del sync bidireccional web ↔ Access, issue #93).
- Generación de contrato PDF (`contratos` con FK a `adopciones.id` ya existe per `app/core/domain.py:481`) — el módulo no crea contratos, sólo el registro base.
- Cálculo automático de transiciones de estado (`animal_current_state`) desde adopciones — scope de LIFECYCLE-03 + PR 2 de `web-only-feature-preservation`.
- Workflow judicial con campos legales adicionales (prórrogas, fianzas, etc.) — scope de Fase 5b+.
- Búsqueda avanzada (por animal, por voluntario de seguimiento, por rango de fechas) — `search_adopciones_by_adoptante` cubre el criterio de aceptación mínimo del issue.

## Decisiones de producto

### D-ADOPT-01: Tipo de adopción como columna propia con CHECK enum

El issue menciona tres tipos: **regular**, **pre-adopción**, **judicial**. El schema actual (`app/core/domain.py:273-293`) no tiene esa columna. Tres opciones evaluadas:

1. **Columna propia `tipo_adopcion TEXT NOT NULL DEFAULT 'regular' CHECK (tipo_adopcion IN ('regular', 'preadopcion', 'judicial'))`**.
2. Catálogo separado `catalogos_tipos_adopcion` con FK.
3. Inferir del estado (pre-adopción si `donativo_preadopcion IS NOT NULL`, judicial si free-text en observaciones, etc.).

**Decisión**: opción 1. Razones:

- **P1 fidelidad**: el legacy `TbAdopcion` distingue regular vs pre-adopción como campos separados (pre-adopción tiene donativo previo + texto legal). Codificar el tipo en columna propia refleja la semántica del dominio sin obligar al operador a rellenar varios campos para "declarar" el tipo.
- **Catálogo overkill**: con 3 valores fijos y sin ciclo de vida (no se añaden / renombran tipos en runtime), una tabla catálogo introduce JOIN innecesario en cada SELECT y un `INSERT INTO catalogos_*` que nadie va a usar.
- **Inferencia frágil**: deducir del estado lleva a errores silenciosos (operador olvida `donativo_preadopcion` y el registro aparece como "regular" sin serlo).

Implementación: añadir la columna vía **ALTER TABLE migration** (siguiendo el patrón FOSTER-02 documentado en `app/core/domain.py:211-228` + D-EST-05). Es idempotente y no toca el `CREATE TABLE` original (P1 fidelidad + tests `test_domain.py` no necesitan actualizarse).

Default `'regular'` cubre el flujo común sin pedir campo extra al operador.

### D-ADOPT-02: FK a `voluntario_seguimiento_id` validada con check `activo = true`

Per VOL-05 (verificado en `openspec/changes/archive/...` y en `docs/architecture/decisiones-proyecto.md`), un voluntario inactivo no debe poder ser asignado a una nueva estancia/adopción. El service hace `SELECT id FROM voluntarios WHERE id = $1 AND activo = true` antes del INSERT y rechaza con `ValueError` si no hay match.

`voluntario_seguimiento_id` sigue siendo opcional (NULL permitida) — un operador puede registrar una adopción sin asignar voluntario de seguimiento, pero si lo asigna, debe estar activo.

`animal_id` también se valida con check `activo = true` (mismo patrón que `entradas._CHECK_ANIMAL_SQL` en `app/modules/entradas/service.py:64-68`).

### D-ADOPT-03: Soft-delete atómico vía `UPDATE ... WHERE id = $1 AND activo = true`

Siguiendo el patrón de `app/modules/entradas/service.py::_DELETE_ENTRADA_SQL` y `app/modules/foster/service.py::_DELETE_CASA_SQL`. La condición `AND activo = true` en el WHERE pliega la verificación de existencia + activo en una sola operación bajo el row lock de PostgreSQL.

Devuelve `True` cuando la fila estaba activa y se desactivó, `False` cuando ya estaba inactiva o el id no existe. La fila permanece en `adopciones` para preservar el histórico (P1 fidelidad — un animal adoptado y devuelto sigue siendo trazable).

### D-ADOPT-04: Búsqueda por nombre de adoptante vía ILIKE

El criterio de aceptación dice "búsqueda por nombre de adoptante funciona". Implementación: `search_adopciones_by_adoptante(client, nombre_parcial: str) -> list[Adopcion]` con `WHERE activo = true AND nombre_adoptante ILIKE '%' || $1 || '%'`. La query es case-insensitive en PostgreSQL (`ILIKE`).

El endpoint `/adopciones?adoptante=...` invoca esta función cuando el query param está presente; sin él, llama a `list_adopciones`.

### D-ADOPT-05: `is_active` derivado, no persistido

`Adopcion` dataclass incluye un `is_active` derivado (computed) que devuelve `fecha_devolucion is None`. No se persiste — se calcula en `_row_to_adopcion`. Esto evita inconsistencia entre `activo` (DB-level soft-delete) y `fecha_devolucion` (semántica de "devuelto al refugio"): una adopción con `fecha_devolucion IS NOT NULL` puede seguir marcada `activo = true` en el sistema (preservar histórico), pero el operador ve `is_active = False` (sabe que ya no está vigente).

## Trazabilidad

- **Issue GitHub:** #47 (ADOPT-01).
- **SDD anterior:** INTAKE-01, INTAKE-02, FOSTER-01, FOSTER-02, FOSTER-03 (todos en `openspec/changes/`).
- **Discovery:** `docs/discovery/feature-03-lifecycle-discovery.md` §2.3 (Adoption event lifecycle) + `legacy-discovery-interrogatorio` task 3.5.
- **Legacy:** `TbAdopcion` (verificado vía Dysflow `projectId=apap`, columnas presentes en `app/core/domain.py:273-293`). Volumetría: ~400 adopciones/año.
- **P1 (fidelidad al legacy):** superset funcional. El schema existente cubre los campos del legacy + FK estructurado a `voluntarios` (mejora justificada — el legacy guardaba el nombre del voluntario como free-text).
- **Decisiones de proyecto afectadas:** D-05 (fidelidad legacy), D-04 (paridad de campos), D-31 (workflow VBA via Dysflow).
- **Decisiones nuevas introducidas:** D-ADOPT-01 (tipo de adopción como columna con CHECK), D-ADOPT-02 (FK validation), D-ADOPT-03 (soft-delete atómico), D-ADOPT-04 (search ILIKE), D-ADOPT-05 (is_active derivado).

## Riesgos

| Riesgo | Mitigación |
|---|---|
| `tipo_adopcion` no existe en legacy — riesgo de "novel feature" | D-ADOPT-01 lo justifica: codifica semántica de dominio que el legacy distribuía en varios campos. Documentado en `docs/architecture/decisiones-proyecto.md`. |
| FK validation a `animales` + `voluntarios` añade 2 queries por create/update | Las queries son indexadas por PK (UUID), sub-ms en InsForge. Coste aceptable para garantizar integridad referencial estricta. |
| `search_adopciones_by_adoptante` sin índice trigram puede ser lenta | Volumetría ~400/año, ILIKE sobre texto sin índice es OK. Si crece, añadir índice `pg_trgm` en `nombre_adoptante` (futuro). |
| Soft-delete via UPDATE vs physical delete — riesgo de "filas zombie" | Patrón del proyecto (mirror `animales`, `voluntarios`, `entradas`, `casas_acogida`). `activo = false` filtra listados; physical delete prohibido. |

## Criterios de aceptación

1. `POST /adopciones` con datos válidos → fila en `adopciones` con `id` UUID, `activo = true`, `fecha_alta = now()`, redirect a `/adopciones/{id}`.
2. `POST /adopciones` sin `nombre_adoptante` o sin `fecha_adopcion` o sin `animal_id` → 422 con mensaje claro, sin escribir.
3. `POST /adopciones` con `animal_id` inexistente → 422 ("animal_id does not reference an existing animal").
4. `POST /adopciones` con `voluntario_seguimiento_id` inactivo → 422 ("voluntario_seguimiento_id must reference an active volunteer").
5. `POST /adopciones` con `tipo_adopcion` fuera de `'regular' / 'preadopcion' / 'judicial'` → 422 (CHECK constraint a nivel DB).
6. `GET /adopciones` lista adopciones activas ordenadas por `fecha_alta DESC`.
7. `GET /adopciones?adoptante=garcia` filtra por `ILIKE '%garcia%'` sobre `nombre_adoptante`.
8. `GET /adopciones/{id}` renderiza el detalle con los datos del adoptante, animal, voluntario de seguimiento y estado (`is_active` derivado).
9. `POST /adopciones/{id}/update` actualiza los campos modificables; redirect a detail en éxito.
10. `POST /adopciones/{id}/delete` → soft-delete (`activo = false`, `updated_at = now()`), redirect a `/adopciones`.
11. Todos los endpoints protegidos con `require_authorized_user`; las 3 forms con `csrf_token` oculto.
12. Tests service: 25 atoms cubriendo happy path, sad path por campo, FK checks, soft-delete, search, is_active.
13. Tests routes: 12 atoms cubriendo auth guard en 7 endpoints, CSRF en 3 forms, redirects, 404, 422, ausencia de SQL en routes.
14. `log_safe` para todo evento de adopciones (create, update, delete) con campos no sensibles.
15. Castellano sin jerga en templates y mensajes.
16. P1 fidelidad: el módulo cubre los campos del legacy `TbAdopcion` (verificado vía Dysflow) + FK estructurada a `voluntarios` (mejora justificada).