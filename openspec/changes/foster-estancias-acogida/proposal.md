# Propuesta: FOSTER-02 — CRUD de estancias de acogida con FK a casa y voluntarios

skill_resolution: paths-injected

## Intención

Issue #44 implementa el CRUD de la **estancia de acogida** (legacy `TbAcogidaAnimal`, ~38 casas con estancias activas en producción, 15 columnas legacy + 1 mejora justificada) referenciando la entidad `casas_acogida` (FOSTER-01, #43) y los voluntarios activos (para los roles de acogida, seguimiento y sanitario). Esto desbloquea FOSTER-03 (gate de capacidad, que necesita consultar estancias activas por casa) y FOSTER-04 (asignación de material, que necesita la estancia como FK estable), y completa la operativa real de "asignar animal a casa disponible" cerrando el flujo foster del operador.

## Alcance

### Dentro
- Nueva columna `acogidas.casa_acogida_id UUID REFERENCES casas_acogida(id)` vía `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` (idempotente, sin reorganizar el orden de creación de tablas en `ensure_domain_schema`).
- Módulo `app/modules/acogidas/` con `service.py` (dataclass `Acogida`, validaciones, CRUD, helpers) + `routes.py` (7 endpoints protegidos).
- Service público: `create_acogida`, `list_acogidas(activas_solo=False)`, `get_acogida_by_id`, `update_acogida`, `close_acogida` (cierra la estancia: `fecha_final = current_date`), `delete_acogida` (soft-delete: `activo = false`).
- Helpers públicos: `compute_duracion(acogida) -> int | None` (días entre fechas, `None` si sigue abierta) e `is_active(acogida) -> bool` (true cuando `activo` Y `fecha_final IS NULL`).
- Validaciones: `animal_id` requerido y debe apuntar a un animal activo; `fecha_inicio` requerida (no vacía, no futura). `casa_acogida_id` opcional; si presente debe existir y estar activa. Cualquier `voluntario_*_id` opcional; si presente debe apuntar a un voluntario activo (rechaza inactivos, mismo control que VOL-05).
- Routes `acogidas_routes.py` (sub-router con `prefix="/acogidas"`): list, new, create, detail, edit, update, close, delete.
- Templates: `acogidas/list.html`, `acogidas/form.html` (compartido create/edit), `acogidas/detail.html` con campo `duracion` calculado.
- Nav link "Estancias de acogida" en `app/templates/base.html` entre "Casas de acogida" y "Voluntarios".
- Tests TDD rojo→verde: ~25 atoms service (validación required, FK animal, FK casa activa/inactiva, FK voluntario activo/inactivo, duración, detección activa, soft-delete, close) + ~15 atoms routes (auth guard en 7 endpoints, CSRF en 4 forms, no SQL en routes, redirects, sad validation).
- `docs/roadmap.md` refresca: quita #44 de §4 abiertas, añade a §5-bis cerradas con SHA.

### Fuera
- Validación de capacidad contra estancias activas (queries cruzadas `casas_acogida` ↔ `acogidas`) — scope de FOSTER-03.
- Asignación de material a estancia — scope de FOSTER-04.
- Workflow judicial foster (variante `Acogida Judicial` con texto legal adicional) — scope de Fase 5b avanzada.
- State machine del animal (cambiar `animal_current_state` cuando se cierra una estancia) — scope de Fase 4 + LIFECYCLE-SCHEMA-02.
- Selección visual de casa/voluntario/animal vía dropdown (en esta issue los IDs son free-text UUIDs; los dropdowns vendrán con la issue que traiga el módulo de selects).

## Decisiones de producto

### D-EST-01: `casa_acogida_id` opcional (retro-compat con legacy)

El campo es **opcional** en esta issue: el legacy `TbAcogidaAnimal` no exigía el `IDAcogidaCasa` (muchas estancias históricas se mantienen sin casa tras el soft-delete de la casa). Si en una issue futura FOSTER-03 decide hacerlo obligatorio, se añadirá `NOT NULL` con migración. Mantenerlo opcional evita una ruptura de datos y respeta la realidad operativa (algunas estancias son "sueltas" por motivos históricos).

### D-EST-02: FK estructurada a `casas_acogida` en vez de free-text

Legacy guardaba `IDAcogidaCasa` como INTEGER con FK estructurada a `TbAcogidaCasas`. Web mantiene esa FK estructurada a la nueva entidad `casas_acogida(UUID PK)`. La diferencia vs legacy: el UUID es estable y portable; el `IDAcogidaCasa` INT era local de Access. Cero pérdida de información: la FK de casa es 1:1 con el legacy.

### D-EST-03: FKs estructuradas a `voluntarios` (no free-text)

El legacy `TbAcogidaAnimal` tenía `Voluntario`, `Seguimiento1`, `Seguimiento2`, `Sanitario` como TEXT (nombres). Web los traduce a FKs UUID estructuradas: `voluntario_acogida_id`, `voluntario_seguimiento1_id`, `voluntario_seguimiento2_id`, `voluntario_sanitario_id`. Validación: cada FK opcional; si presente, debe apuntar a un voluntario activo (mismo control que VOL-05). Esto es una traducción de campo legacy a FK estructurada, NO una pérdida de capacidad (el nombre del voluntario se resuelve por JOIN, igual que en legacy se buscaba por nombre).

### D-EST-04: `close_acogida` vs `delete_acogida` — separación semántica

Discovery 2.2 dice "End of foster: Returns animal to Pendiente de Nueva Situación state". Eso es un evento de ciclo de vida, no un soft-delete. Por tanto:
- `close_acogida`: pone `fecha_final = current_date`, `activo` se mantiene `true`. Es un evento de "el animal vuelve al albergue" o "el animal pasa a adopción". El registro de la estancia se conserva como histórico cerrado.
- `delete_acogida`: pone `activo = false` y `fecha_baja = now()`. Es el soft-delete real (operación errónea, datos incorrectos, etc.) — marca la estancia como inactiva. Equivalente al soft-delete de `casas_acogida`.

Esta distinción es importante porque en una issue futura (LIFECYCLE-SCHEMA-02/03) el evento de "fin de estancia" disparará una transición de `animal_current_state`; si `close_acogida` pusiera `activo = false`, el evento se confundiría con un soft-delete y el state machine no podría distinguir entre "animal vuelve al albergue" y "estancia marcada como inválida".

### D-EST-05: Migración ALTER TABLE vs modificar CREATE TABLE

He elegido **migración ALTER TABLE explícita** en lugar de añadir la columna al `ACOGIDAS_CREATE_TABLE_SQL` directamente. Razones:
1. El diff entre FOSTER-01 y FOSTER-02 muestra claramente el cambio (un `ALTER TABLE acogidas ADD COLUMN IF NOT EXISTS casa_acogida_id ...` es inequívoco).
2. El patrón `ADD COLUMN IF NOT EXISTS` es idempotente: re-ejecutar `ensure_domain_schema` no falla.
3. Mantiene el `CREATE TABLE` original congelado: cualquier lectura del `CREATE TABLE` (por el test `test_acogidas_create_table_sql_columns` en `test_domain.py`) no cambia.
4. Si en una issue futura FOSTER-03 quiere añadir más columnas a `acogidas` (e.g. `motivo_cierre`, `destino_cierre`), el patrón se replica: un nuevo `ALTER TABLE` por columna, todas con `IF NOT EXISTS`.

La alternativa (añadir al `CREATE TABLE`) haría que el CREATE TABLE de `acogidas` cambiase y el test `test_acogidas_create_table_sql_columns` tuviese que actualizarse; el test seguiría pasando, pero el diff es menos explícito.

### D-EST-06: Validación de voluntarios activos (active check)

`voluntario_*_id` se valida contra la misma regla que VOL-05: si está presente, debe apuntar a un voluntario con `activo = true`. Un voluntario inactivo NO puede ser asignado a una estancia nueva. Esto evita que el operador asigne un voluntario que ya no colabora a una estancia, lo que generaría un animal "sin seguimiento real" sin saberlo.

## Trazabilidad

- **Issue GitHub:** #44 (FOSTER-02).
- **Issue previa:** FOSTER-01 (#43) — la entidad `casas_acogida` ya existe y se posiciona antes de `acogidas` en `ensure_domain_schema`, lo que permite añadir esta FK con un simple `ALTER TABLE`.
- **Issue previa:** INTAKE-01 (#87/#88/#89) — la tabla `acogidas` ya existe (creada en FASE 5a) con 15 columnas: 4 FKs a `voluntarios`, FK a `animales`, FK a `entradas`, fechas, campos denormalizados legacy (`direccion`, `telefono`).
- **Issue previa:** VOL-05 — el patrón de validación de voluntarios activos está en `app/modules/voluntarios/service.py::_CHECK_ACTIVE_VOLUNTEER_SQL`. FOSTER-02 lo reusa sin reinventar.
- **Discovery:** `docs/discovery/feature-02-intake-foster-adoption.md` §2.2 (Foster stays, Active stay detection, End of foster transition).
- **Legacy:** `TbAcogidaAnimal` (verificado vía Dysflow `projectId=apap` el 2026-07-04, 15 columnas).
- **P1 (fidelidad al legacy):** superset funcional — 1:1 con las 15 columnas legacy + 1 mejora justificada (FK estructurada a `casas_acogida`). Las FKs a voluntarios son una **mejora de fidelidad**: legacy tenía nombres en free-text, web tiene FKs estructuradas con validación de activo. El nombre del voluntario se resuelve por JOIN (lo que en legacy era lookup manual por nombre).
- **Decisiones de proyecto afectadas:** D-05 (fidelidad legacy), D-04 (paridad de campos).
- **Cierra con:** `docs(roadmap)` refresca + cierre #44 con SHA + test path.

## Riesgos

| Riesgo | Mitigación |
|---|---|
| `casa_acogida_id` es opcional — riesgo de "estancias huérfanas" sin casa | Aceptable por retro-compat con legacy (algunas estancias son históricas y no tienen casa asignada). FOSTER-03 decidirá si lo hace obligatorio. |
| FK a `voluntarios` con `activo = true` check puede romper inserts con voluntarios inactivos | Es el comportamiento deseado (D-EST-06). Si un voluntario se desactiva, las estancias existentes NO se invalidan — solo se rechazan asignaciones nuevas. Las estancias activas con `voluntario_*_id` inactivo son legítimas (la estancia empezó cuando el voluntario estaba activo). |
| `close_acogida` no hace `activo = false` — podría parecer "soft-delete incompleto" | Decisión documentada en D-EST-04: `close` es "fin de estancia" (evento de ciclo de vida), `delete` es "soft-delete real". Operador distinguible en UI: el botón "Cerrar estancia" deja la fila visible en el listado (con `fecha_final` populated), el botón "Dar de baja" la oculta. |
| Volumetría grande (38 casas con estancias activas, posiblemente 200+ estancias históricas) — riesgo de query lenta en `list_acogidas` | Service ordena por `fecha_inicio DESC` con índice implícito en PK; sin índices adicionales. Si la volumetría crece, FOSTER-03 lo abordará. |

## Criterios de aceptación

1. `POST /acogidas` con `animal_id` válido + `fecha_inicio` válida → fila en `acogidas` con `id` UUID, redirect a `/acogidas/{id}`.
2. `POST /acogidas` con `casa_acogida_id` apuntando a una casa activa → fila insertada con la FK.
3. `POST /acogidas` con `casa_acogida_id` apuntando a una casa inexistente o inactiva → 422 con mensaje claro.
4. `POST /acogidas` con `voluntario_*_id` apuntando a un voluntario inactivo → 422 con mensaje claro.
5. `POST /acogidas` con `animal_id` inexistente → 422.
6. `POST /acogidas` con `fecha_inicio` vacía → 422.
7. `POST /acogidas` con `casa_acogida_id` null → fila insertada (opcional, retro-compat).
8. `GET /acogidas` lista estancias (activas + cerradas), ordenadas por `fecha_inicio DESC`.
9. `GET /acogidas?activas_solo=1` filtra a `fecha_final IS NULL`.
10. `POST /acogidas/{id}/close` → `fecha_final = current_date`, `activo` se mantiene `true`.
11. `POST /acogidas/{id}/delete` → `activo = false`, `fecha_baja = now()`.
12. `compute_duracion(acogida)` devuelve días enteros cuando hay `fecha_final`, `None` cuando sigue abierta.
13. `is_active(acogida)` devuelve `True` cuando `activo AND fecha_final IS NULL`, `False` en cualquier otro caso.
14. Tests service: ~25 atoms cubriendo happy path, sad path por cada validación, helpers, CRUD, soft-delete, close.
15. Tests routes: ~15 atoms cubriendo auth guard en 7 endpoints, CSRF en 4 forms, ausencia de SQL en routes.
16. `log_safe` para todo evento de estancia (create, update, close, delete) con campos no sensibles.
17. Castellano, sin jerga, en templates y mensajes.
