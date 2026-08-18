# Propuesta: HEALTH-01 — CRUD de actuaciones sanitarias

skill_resolution: paths-injected

## Intención

Issue #50 implementa el CRUD de la entidad **Actuación Sanitaria** (legacy `TbActuacionSanitaria` / similar) en la nueva aplicación, modelada como tabla propia separada del animal (`animales`) y de la estancia (`acogidas`). Permite a APAP registrar el historial veterinario de cada animal (vacunas, desparasitaciones, analíticas, esterilizaciones, etc.) preservando la fecha del acto, el tipo (referenciado al catálogo de pruebas), el veterinario que lo realizó, el voluntario responsable, el material utilizado y observaciones libres.

El slice incluye la regla de validación de fechas **D-24** (documentada formalmente en este slice — antes solo se referenciaba en `docs/roadmap.md` sin definición operativa), que garantiza que ninguna actuación se registre con fecha futura ni anterior al alta del animal en el sistema. La regla es la pieza central de este slice porque condiciona la utilidad clínica del módulo: sin ella se pueden introducir registros incoherentes (fechas del año 3000, fechas anteriores al ingreso del animal) que contaminan el historial veterinario.

El módulo soporta el flujo operativo real del refugio (vacunación, desparasitación, esterilización, analíticas, controles) sin obligar al operador a entrar a Access.

## Alcance

### Dentro

- Módulo `app/modules/sanidad/` con `service.py` + `routes.py` + `__init__.py`.
- Tabla `actuacion_sanitaria` (10 columnas de dominio + 3 de auditoría) creada vía `ACTUACION_SANITARIA_CREATE_TABLE_SQL` en `app/core/domain.py`, cableada en `ensure_domain_schema`.
- `ActuacionSanitaria` dataclass frozen + slots con todos los campos del schema.
- `ActuacionSanitariaConflictError(ValueError)` (reservado para futuros UNIQUE constraints — paralelo a `AdopcionConflictError`).
- Validaciones: `animal_id` requerido + activo en `animales`; `fecha` requerida + validación D-24; `voluntario_id` opcional pero si presente, activo en `voluntarios` per VOL-05.
- `create_actuacion_sanitaria`, `list_actuaciones_sanitarias`, `get_actuacion_sanitaria_by_id`, `update_actuacion_sanitaria`, `delete_actuacion_sanitaria` (soft-delete atómico con CTE).
- `search_actuaciones_by_animal(client, animal_id)` para el criterio de aceptación "búsqueda por animal funciona" (filtro en list + endpoint dedicado).
- Validación D-24 con helper privado `_validate_fecha_d24(fecha, animal_fecha_alta) -> str | None`.
- 7 endpoints HTTP: list (con filtro `?animal_id=`), new, create, detail, edit, update, delete — todos con `require_authorized_user` para reads y `require_writer_user` para writes.
- 3 templates: `sanidad/list.html`, `sanidad/form.html` (compartido create/edit), `sanidad/detail.html`.
- Nav link "Actuaciones" en `app/templates/base.html` (mobile + desktop).
- Tests TDD: 25 atoms service + 14 atoms routes = 39 atoms nuevos.
- Definición formal de **D-24** en `docs/architecture/decisiones-proyecto.md` (ver D-HEALTH-02).
- `log_safe` para eventos `sanidad.created|updated|deleted` con campos no sensibles.
- Actualizar `docs/roadmap.md` y cerrar #50 con SHA + trazabilidad.

### Fuera

- Migración de datos desde `TbActuacionSanitaria` legacy (scope del sync bidireccional web ↔ Access, issue #93).
- Workflow de seguimiento (`proxima_fecha`, recordatorios automáticos) — futuro, no en este slice.
- Adjuntar documentos (analíticas PDF, fotos de la cartilla) — la tabla `actuacion_sanitaria` no tiene FK a storage; scope de Fase 7+.
- Integración con `cartillas_sanitarias` o `numero_colegiado` (campos veterinarios regulados) — scope separado.
- Búsqueda avanzada (por tipo, por rango de fechas, por veterinario) — `search_actuaciones_by_animal` cubre el criterio de aceptación mínimo del issue.

## Decisiones de producto

### D-HEALTH-01: `tipo_actuacion_id` como FK a `catalogos_pruebas` (no TEXT)

El campo `tipo_actuacion` del legacy se almacenaba como free-text o como código sin FK. Tres opciones evaluadas:

1. **FK `tipo_actuacion_id UUID REFERENCES catalogos_pruebas(id)`** (propuesta).
2. Texto libre `tipo_actuacion TEXT`.
3. Catálogo separado `catalogos_tipos_actuacion_sanitaria` con FK (sobreingeniería, los valores son los mismos que en `catalogos_pruebas`).

**Decisión**: opción 1. Razones:

- **Reutilización del catálogo existente**: `catalogos_pruebas` (issue #65 CATALOG-01) ya tiene 13 valores seed (`Básico`, `Rabia`, `Esterilización`, `Trivalente`, etc.) que cubren exactamente los tipos de actuación sanitaria del refugio. Crear otro catálogo sería duplicar sin valor.
- **Integridad referencial**: el CHECK enum se delega a la PK del catálogo; si se añade un nuevo tipo, basta con un `INSERT INTO catalogos_pruebas` (ya cubierto por `ensure_catalogs`).
- **Consistencia con `contratos`**: el patrón FK a catálogo (`contratos.tipo_contrato_id` → `catalogos_tipos_contrato`) ya está establecido en el proyecto. HEALTH-01 lo replica.
- **UX mejor**: el form muestra un dropdown poblado desde `list_catalogos_pruebas(client)`, evitando typos del operador y nombres inconsistentes.

Costo: una query extra (`list_catalogos_pruebas`) en el GET del form. Mitigada por el cache de catálogo si se añade en el futuro.

### D-HEALTH-02: Regla D-24 — validación de fecha en la capa de servicio

Esta decisión formaliza **D-24**, referenciada en `docs/roadmap.md` (línea 254) pero sin definición operativa previa. La regla:

> **D-24**: La `fecha` de una `actuacion_sanitaria` DEBE cumplir simultáneamente:
>
> 1. Ser una fecha ISO válida (parseable como `YYYY-MM-DD`).
> 2. Ser ≤ `CURRENT_DATE` del servidor (no se permiten fechas futuras).
> 3. Si el `animal_id` referenciado tiene `fecha_alta IS NOT NULL`, la `fecha` DEBE ser ≥ `animales.fecha_alta` (no se permiten fechas anteriores al alta del animal en el sistema).
>
> Si el animal tiene `fecha_alta IS NULL` (animales legacy importados sin metadato), la cota inferior de la regla 3 se omite — solo se aplican las reglas 1 y 2.

**Implementación en dos capas**:

1. **Validación pura (sin DB)** en `_validate_fecha_d24(fecha: str) -> str | None`:
   - Parsea `fecha` como `date`; si falla, retorna `"fecha debe tener formato YYYY-MM-DD"`.
   - Compara con `date.today()`; si es futura, retorna `"fecha no puede ser futura (hoy es YYYY-MM-DD)"`.

2. **Validación con DB** dentro de la CTE (regla 3, atómica con el FK check):
   - `checked_animal` filtra `WHERE id = $1 AND activo = true AND (fecha_alta IS NULL OR fecha_alta <= $3::date)`.
   - Si la CTE devuelve 0 filas por esta razón, `_raise_validation_error` re-ejecuta la query para distinguir "animal inexistente" de "fecha anterior al alta" y emitir mensaje específico.

**Por qué en dos capas**:
- La validación pura evita un round-trip a la DB para errores obvios (formato mal, fecha futura).
- La validación con DB dentro de la CTE cierra el TOCTOU entre "comprobar fecha_alta" e "INSERT" (mismo patrón que adopciones).
- Si `_raise_validation_error` reporta "fecha anterior al alta del animal", el operador sabe exactamente qué corregir.

**Por qué no más restrictivo** (p. ej., no anterior al `FNacimiento` del animal):
- El refugio a veces registra vacunas administradas antes del alta del animal (p. ej., camadas recogidas con cachorros ya vacunados por el particular). El `fecha_alta` es el límite inferior porque refleja cuándo APAP tiene constancia del animal.

### D-HEALTH-03: Soft-delete atómico vía `UPDATE ... WHERE id = $1 AND activo = true`

Siguiendo el patrón de `app/modules/entradas/service.py::_DELETE_ENTRADA_SQL` y `app/modules/adopciones/service.py::_DELETE_ADOPCION_SQL`. La condición `AND activo = true` en el WHERE pliega la verificación de existencia + activo en una sola operación bajo el row lock de PostgreSQL.

Devuelve `True` cuando la fila estaba activa y se desactivó, `False` cuando ya estaba inactiva o el id no existe. La fila permanece en `actuacion_sanitaria` para preservar el histórico clínico (P1 fidelidad — un animal con 5 vacunas debe mostrar todas incluso si una fue registrada por error y luego "borrada").

### D-HEALTH-04: Búsqueda por `animal_id` vía filtro en list + `search_actuaciones_by_animal`

El criterio de aceptación dice "búsqueda por animal funciona" (el operador necesita ver el historial sanitario de un animal concreto). Implementación:

- `GET /sanidad?animal_id=<uuid>` filtra la lista al animal.
- `search_actuaciones_by_animal(client, animal_id: str) -> list[ActuacionSanitaria]` es la función de service que ejecuta el filtro.
- Sin `animal_id`, devuelve todas las actuaciones activas ordenadas por `fecha_alta DESC` (más recientes primero), con `LIMIT 100`.

El criterio de aceptación del issue no menciona búsqueda por texto (no hay campo `nombre_animal` en la tabla — el nombre se obtiene vía JOIN con `animales` que está fuera de alcance). El animal se selecciona por id (UUID).

### D-HEALTH-05: CTE para validación FK atómica (TOCTOU-safe)

`animal_id` y `voluntario_id` se validan en una sola CTE junto al INSERT (mismo patrón que adopciones y entradas), evitando la ventana TOCTOU entre "SELECT FK row" e "INSERT". PostgreSQL evalúa toda la CTE bajo el mismo statement snapshot.

Placeholders:
- `$1` `animal_id` (FK required)
- `$2` `voluntario_id` (FK opcional; NULL cuando no se proporciona)
- `$3` `fecha` (DATE)
- `$4` `tipo_actuacion_id` (FK opcional al catálogo)
- `$5` `veterinario`
- `$6` `observaciones`
- `$7` `material_utilizado`
- `$8` `updated_at` (lo setea la CTE con `now()`)

## Trazabilidad

- **Issue GitHub:** #50 (HEALTH-01).
- **SDD anteriores:** INTAKE-01/02/03, FOSTER-01/02/03, ADOPT-01 (todos en `openspec/changes/`).
- **Discovery:** `docs/discovery/feature-03-lifecycle-discovery.md` §2.4 (Health event lifecycle) + legado `TbActuacionSanitaria` (a verificar vía Dysflow si surge duda).
- **Legacy:** `TbActuacionSanitaria` — volumetría esperada: ~5-10 actuaciones por animal × ~200 animales/año ≈ 1000-2000 filas/año.
- **P1 (fidelidad al legacy):** superset funcional. El schema cubre los campos del legacy + FK estructurada a `catalogos_pruebas` (mejora justificada — el legacy guardaba el tipo como free-text).
- **Decisiones de proyecto afectadas:** D-05 (fidelidad legacy), D-04 (paridad de campos), D-31 (workflow VBA via Dysflow).
- **Decisión formalizada:** **D-24** (regla de validación de fechas, antes solo referenciada en roadmap.md — ahora operativa en `docs/architecture/decisiones-proyecto.md`).
- **Decisiones nuevas introducidas:** D-HEALTH-01 (FK a catalogos_pruebas), D-HEALTH-02 (D-24 formal), D-HEALTH-03 (soft-delete), D-HEALTH-04 (search por animal), D-HEALTH-05 (CTE TOCTOU).

## Riesgos

| Riesgo | Mitigación |
|---|---|
| `tipo_actuacion_id` FK exige que `catalogos_pruebas` exista antes | El proyecto ya cablea `ensure_catalogs` antes de `apply_sql_migrations`; la tabla se crea vía `CREATE TABLE IF NOT EXISTS` y los seeds corren con `ON CONFLICT DO NOTHING`. Si en producción se rompe el orden, el error de FK es loud y se diagnostica en el primer arranque. |
| Validación D-24 dentro de CTE bloquea el INSERT si la fecha es anterior al alta | Mensaje de error específico en `_raise_validation_error` indica al operador que la fecha es anterior al alta; el operador puede corregir el alta o la fecha. |
| Volumetría 1000-2000 filas/año × N años puede hacer lento `list` sin paginación | `LIMIT 100` en `_LIST_ACTUACIONES_SANITARIAS_SQL` + orden por `fecha_alta DESC` cubren el caso operativo; paginación futura si crece >50k. |
| Soft-delete via UPDATE vs physical delete — riesgo de "filas zombie" | Patrón del proyecto (mirror `animales`, `voluntarios`, `entradas`, `adopciones`). `activo = false` filtra listados; physical delete prohibido. |
| D-24 no estaba formalmente definida antes | Este slice la define y la testea con 5 atoms específicos (D-HEALTH-02). Si la regla resulta demasiado restrictiva para casos reales (p. ej., camadas con historial pre-alta), se ajusta en un slice futuro. |
| `voluntario_id` opcional — si se olvida capturar, el operador no sabe quién hizo la actuación | El form lo deja opcional por D-HEALTH-05 (algunas actuaciones las hace el veterinario externo, no un voluntario APAP). El log_safe captura `actor_user_id` para auditoría. |

## Criterios de aceptación

1. `POST /sanidad` con datos válidos → fila en `actuacion_sanitaria` con `id` UUID, `activo = true`, `fecha_alta = now()`, redirect a `/sanidad/{id}`.
2. `POST /sanidad` sin `animal_id` o sin `fecha` → 422 con mensaje claro, sin escribir.
3. `POST /sanidad` con `animal_id` inexistente → 422 ("animal_id debe apuntar a un animal activo").
4. `POST /sanidad` con `animal_id` inactivo → 422 ("animal_id debe apuntar a un animal activo").
5. `POST /sanidad` con `voluntario_id` inactivo (per VOL-05) → 422 ("voluntario_id debe apuntar a un voluntario activo").
6. `POST /sanidad` con `fecha` futura (D-24 regla 2) → 422 ("fecha no puede ser futura").
7. `POST /sanidad` con `fecha` anterior a `animales.fecha_alta` cuando el animal tiene fecha_alta (D-24 regla 3) → 422 ("fecha es anterior al alta del animal").
8. `POST /sanidad` con `fecha` anterior a `animales.fecha_alta` cuando el animal tiene fecha_alta NULL (D-24 exención) → 200 (animal legacy sin fecha_alta, regla 3 no aplica).
9. `POST /sanidad` con `fecha` malformada (no ISO) → 422 ("fecha debe tener formato YYYY-MM-DD").
10. `GET /sanidad` lista actuaciones activas ordenadas por `fecha_alta DESC` con `LIMIT 100`.
11. `GET /sanidad?animal_id=<uuid>` filtra al animal concreto.
12. `GET /sanidad/{id}` renderiza el detalle con los datos del acto (tipo via JOIN a catalogos_pruebas, veterinario, voluntario, fecha, material, observaciones).
13. `POST /sanidad/{id}/update` actualiza los campos modificables; redirect a detail en éxito.
14. `POST /sanidad/{id}/delete` → soft-delete (`activo = false`, `updated_at = now()`), redirect a `/sanidad`.
15. Todos los endpoints protegidos con `require_authorized_user` (reads) o `require_writer_user` (writes). Las 3 forms con `csrf_token` oculto.
16. Tests service: 25 atoms cubriendo happy path, sad path por campo (animal, voluntario, fecha), FK checks, soft-delete, search, D-24 (5 atoms específicos), CTE TOCTOU.
17. Tests routes: 14 atoms cubriendo auth guard en 7 endpoints, CSRF en 3 forms, redirects, 404, 422, ausencia de SQL en routes.
18. `log_safe` para todo evento de sanidad (create, update, delete) con `actor_user_id`.
19. Castellano sin jerga en templates y mensajes.
20. P1 fidelidad: el módulo cubre los campos del legacy + FK estructurada a `catalogos_pruebas` (mejora justificada).