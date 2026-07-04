# Propuesta: FOSTER-03 — Gate de especie + advisory de capacidad con override auditado

skill_resolution: paths-injected

## Intención

Issue #45 implementa la **regla de admisión** que une las dos entidades creadas por FOSTER-01 (#43, casas de acogida) y FOSTER-02 (#44, estancias de acogida) en un flujo operativo real: "¿puedo asignar este animal a esta casa?".

La regla tiene dos partes ortogonales:

1. **Gate de especie (hard block):** una casa con `especie_preferente = 'FELINA'` no admite un perro. Sin override. El operador tiene que buscar otra casa.
2. **Advisory de capacidad (warning + override):** cuando una casa ya tiene N estancias activas de su especie preferente y N >= `capacidad`, el sistema avisa pero deja continuar. El operador puede registrar un `motivo` obligatorio (override auditado) para confirmar la asignación por encima del límite.

Esto cierra el gap funcional con el legacy `TbAcogidaCasas`: el legacy tenía `EspeciePreferente` y `Capacidad` como campos informativos pero NO bloqueaba la asignación en el formulario — el operador se enteraba del mismatch al revisar la estancia. Web introduce el gate como regla estructurada del servicio, traducible a tests, audit, y vista previa al commit.

## Alcance

### Dentro

- Nueva tabla `foster_capacity_overrides` (id, casa_acogida_id, animal_id, operador_user_id, motivo, created_at) para auditar los overrides de capacidad. Es tabla propia (D-GC-01) y no reusa `animal_lifecycle_events` porque la pregunta "dame todos los overrides de esta casa" es un patrón claro y la tabla dedicada evita mezclar eventos de ciclo de vida con auditoría de capacidad.
- Módulo `app/modules/foster/assignment.py` con:
  - `AssignmentDecision` dataclass (`decision: Literal["admit", "block", "admit_with_warning"]`, `reason: str | None`, `warnings: tuple[str, ...]`).
  - `FosterCapacityOverride` dataclass (id, casa_acogida_id, animal_id, operador_user_id, motivo, created_at).
  - `evaluate_assignment(client, animal_id, casa_id) -> AssignmentDecision`: gate de especie (hard block) + capacity check (advisory). Levanta `ValueError` si el animal o la casa no existen, o si la casa está inactiva.
  - `record_override(client, casa_id, animal_id, operador_user_id, motivo) -> FosterCapacityOverride`: valida `motivo` non-empty (raise `ValueError` si vacío o solo whitespace), INSERT INTO foster_capacity_overrides, `log_safe("foster.capacity_override.recorded", ...)`.
  - `list_overrides_for_casa(client, casa_id) -> list[FosterCapacityOverride]`: para el historial en detail/overrides.
- Sub-router `app/modules/foster/assignment_routes.py` con:
  - `GET /casas-acogida/{id}/asignar` — form para evaluar la asignación de un animal a la casa.
  - `POST /casas-acogida/{id}/asignar` — ejecuta `evaluate_assignment`. Si `block` → 422 con error. Si `admit` → 303 a `/acogidas/new?animal_id=X&casa_acogida_id=Y` (pre-fill). Si `admit_with_warning` → re-render del form con banner amarillo + campo motivo opcional (obligatorio solo si confirma).
  - `GET /casas-acogida/{id}/overrides` — tabla con el historial de overrides aplicados a esa casa.
- Templates: `casas_acogida/asignar.html` (form + resultado) y `casas_acogida/overrides.html` (historial).
- Modificación de `casas_acogida/detail.html`: añade "Estancias activas" (count de `acogidas` WHERE `casa_acogida_id = this AND activo = true AND fecha_final IS NULL`), botón "Asignar animal", y "Histórico de overrides" (últimos 10).
- `app/main.py`: incluye `assignment_router` después de `foster_router` (mismo prefijo `/casas-acogida`, paths `/asignar` y `/overrides` no colisionan).
- `app/modules/foster/__init__.py`: re-exporta `assignment_service` para mantener la API consistente.
- Tests TDD rojo→verde: ~25 atoms service + ~15 atoms routes + tests XSS para los 2 nuevos templates.
- `docs/roadmap.md` refresca: quita #45 de §4 abiertas, añade a §5-bis cerradas con SHA.

### Fuera

- Validación de capacidad con respecto al histórico TOTAL de la casa (no solo activas) — scope de Fase 5b si surge la necesidad.
- State machine del animal disparado por el gate — el gate NO crea la estancia; el operador decide. La estancia se crea en `/acogidas/new` post-decisión.
- Capacidad por separado por especie cuando una casa tiene `especie_preferente = NULL` (cualquier especie). D-GC-03 cierra esto: una casa "cualquier especie" cuenta TODAS sus estancias activas contra `capacidad`, mezclando especies. Esa es la lectura conservadora que respeta el patrón "cualquier especie" del FOSTER-01.
- Roles diferenciados (admin vs key_user) para el gate — el operador autorizado actual ya tiene permisos. FOSTER-04 decidirá si añade gates por rol.
- UI de autocompletar/selección visual de animal vía dropdown — en esta issue el campo `animal_id` se introduce como UUID free-text, mismo patrón que `casa_acogida_id` en FOSTER-02.

## Decisiones de producto

### D-GC-01: Tabla propia `foster_capacity_overrides` vs reusar `animal_lifecycle_events`

**Elección:** tabla propia.

**Justificación:**

1. La query de "dame todos los overrides de esta casa" (`SELECT ... WHERE casa_acogida_id = $1 ORDER BY created_at DESC`) es un patrón claro y trivialmente indexable con un índice BTREE en `casa_acogida_id`. Si reusamos `animal_lifecycle_events`, la query requiere filtrar por `event_type = 'CAPACITY_OVERRIDE'` y `source_entity_type = 'casa_acogida'`, que es un full table scan sin índice apropiado.
2. `animal_lifecycle_events` es append-only de eventos del **animal** (INTAKE_STARTED, FOSTER_STARTED, ADOPTION_RETURNED...). Un override de capacidad es un evento del **operador** sobre la asignación; semánticamente no es un evento de ciclo de vida del animal (el animal ni siquiera ha sido asignado todavía).
3. Mezclar ambos en la misma tabla introduce ambigüedad en la deducción del state machine del animal. La derivación futura (PR 2 de `web-only-feature-preservation`) debe poder escanear eventos del animal sin tener que filtrar overrides de capacidad.
4. La tabla propia tiene 5 columnas (sin contar `id` y `created_at`); añadir CHECK enum y FKs a `animales` + `casas_acogida` + `usuarios_autorizados` (operador) es directo y aporta integridad referencial.

**Coste:** una tabla más en `ensure_domain_schema`. Ya hay 12 tablas (más la 13ª con el ALTER de FOSTER-02); añadir la 14ª es marginal.

### D-GC-02: Identidad del operador = `user_id` de la sesión, no email

**Elección:** `user_id` (UUID de `usuarios_autorizados.id`).

**Justificación:**

1. `user_id` es el join key natural con `usuarios_autorizados`. Permite consultar "todos los overrides hechos por María en los últimos 30 días" con un JOIN directo. Email puede cambiar; UUID no.
2. `user_id` ya está en `request.session` (campo `user_id`) vía `read_session_payload`. El handler lo tiene disponible sin tocar nada.
3. GDPR minimisation: `motivo` puede llevar texto libre (justificación del override). El operador que lo escribió queda identificado por UUID, no por PII directamente visible en logs.
4. `log_safe` sigue funcionando: el campo `operador` en el log no es un campo sensible de la lista cerrada (12 campos), así que no se redacta por accidente.

**Coste:** ninguno material.

### D-GC-03: Cómo contar estancias activas de la especie preferida

**Elección:** `JOIN acogidas JOIN animales WHERE casa_acogida_id = $1 AND fecha_final IS NULL AND activo = true AND (animales.especie = casas_acogida.especie_preferente OR casas_acogida.especie_preferente IS NULL)`.

**Justificación:**

1. Cierra OD-3a (capacity counted only for preferred species). Una casa con `especie_preferente = 'FELINA'` NO cuenta un perro en su capacidad, aunque el perro esté asignado en una estancia histórica (que es un caso raro de error de datos, no operativo).
2. La cláusula `OR especie_preferente IS NULL` replica el patrón conservador del FOSTER-01 (la casa "cualquier especie" cuenta TODAS sus estancias). Esto es una decisión deliberada: la casa "cualquier especie" no discrimina por especie, así que TODAS las estancias activas cuentan contra su capacidad.
3. El JOIN a `animales` es necesario para conocer la especie del animal asignado (la `acogidas` solo guarda `animal_id`, no la especie denormalizada).
4. Solo estancias con `fecha_final IS NULL AND activo = true` cuentan. Una estancia cerrada (`fecha_final` populated) ya no ocupa la casa. Una estancia soft-deleted (`activo = false`) tampoco.

**Coste:** un JOIN extra. Sin índices adicionales: el PK de `acogidas` cubre el lookup por `casa_acogida_id` (escenario común para capacity checks repetidos por la misma casa). En producción hay ~38 casas con estancias activas; el coste es despreciable.

### D-GC-04: Shape de la respuesta del servicio cuando hay warning de capacidad

**Elección:** `AssignmentDecision` con `decision: Literal["admit", "block", "admit_with_warning"]` + `reason: str | None` + `warnings: tuple[str, ...]`.

**Justificación:**

1. `Literal` permite que los tests exauen sobre el set exacto de valores (no strings sueltos).
2. `decision = "block"` lleva un `reason` obligatorio (texto en castellano claro: "la casa solo admite FELINA, no CANINA"). El route renderiza el `reason` en el banner de error.
3. `decision = "admit_with_warning"` lleva uno o más `warnings` (tupla inmutable; el servicio no los modifica post-creación). El route renderiza cada `warning` en el banner amarillo. La asignación procede (no es block).
4. `decision = "admit"` lleva `warnings = ()` (tupla vacía) y `reason = None`. Es el caso verde sin observaciones.
5. No hay un campo `can_proceed` redundante: el handler lo deriva de `decision in {"admit", "admit_with_warning"}`. Single source of truth.

**Coste:** el dataclass tiene 3 campos. Los tests verifican la forma completa en cada path.

### D-GC-05: `evaluate_assignment` es una operación separada, NO un cambio a `create_acogida`

**Elección:** nuevo módulo `foster.assignment` con su propio API público (`evaluate_assignment`, `record_override`, `list_overrides_for_casa`). `acogidas.service.create_acogida` NO se modifica.

**Justificación:**

1. La pregunta "¿puedo asignar este animal a esta casa?" es **ortogonal** a "¿se crea esta estancia?". Un gate evalúa admisión; un create persiste. Mezclar ambos en una sola función rompe el principio de responsabilidad única y haría que el gate se ejecutase SIEMPRE, incluso en migraciones batch o scripts de seed (que necesitan bypass legítimo).
2. El flujo del operador: `GET /casas-acogida/{id}/asignar` → `POST /casas-acogida/{id}/asignar` (evalúa) → si `admit` o `admit_with_warning + motivo`, redirect 303 a `/acogidas/new?animal_id=X&casa_acogida_id=Y` (pre-fill) → el create de la estancia se hace vía `POST /acogidas` (FOSTER-02). El gate vive en su propio formulario con su propio audit log; el create vive en su propio formulario con su propio log.
3. El override (`record_override`) se graba al confirmar el `admit_with_warning`, ANTES del redirect. Esto garantiza que el audit log persiste incluso si el operador abandona el create de la estancia después. La query "todas las overrides aplicadas pero sin estancia resultante" es trivial y permite limpiar overrides huérfanos.
4. Los tests de `acogidas.service` no cambian — el gate es un módulo nuevo. Cero regresión.

**Coste:** un módulo más (`assignment.py`). Pero ya hay precedente en el proyecto: `app/modules/entradas/batch_service.py` separa batch intake del simple intake. Mismo patrón.

## Trazabilidad

- **Issue GitHub:** #45 (FOSTER-03).
- **Issue previa:** FOSTER-01 (#43) — entidad `casas_acogida` con campo `especie_preferente` y `capacidad`.
- **Issue previa:** FOSTER-02 (#44) — entidad `acogidas` con FK a `casas_acogida` y voluntarios activos. La JOIN `acogidas JOIN animales` para capacity check requiere ambas entidades en su lugar.
- **Decisión D-18:** resuelto (capacidad contada solo para la especie preferida — OD-3a).
- **Decisión D-19:** resuelto (override auditado con motivo obligatorio — D-GC-01 + D-GC-02).
- **Discovery:** `docs/discovery/feature-02-intake-foster-adoption.md` §2.2 (Foster stays, Capacity validation, Gate de especie implícito en el filtro del legacy).
- **Legacy:** `TbAcogidaCasas` tenía `EspeciePreferente` y `Capacidad` como campos informativos; el legacy NO bloqueaba, web sí (gate de especie) + avisa (capacity).
- **P1 (fidelidad al legacy):** superset funcional. El filtro de especie implícito del legacy se traduce a un gate explícito en el servicio. El capacity advisory preserva el comportamiento legacy (el legacy NO bloqueaba over-capacity) pero añade audit trail.
- **Decisiones de proyecto afectadas:** D-05 (fidelidad legacy), D-04 (paridad de campos), D-18 (capacity counted only for preferred species — resuelta en esta issue).
- **Cierra con:** `docs/roadmap.md` refresca + cierre #45 con SHA + test path.

## Riesgos

| Riesgo | Mitigación |
|---|---|
| JOIN `acogidas JOIN animales` puede ser lento si la volumetría crece | Sin índices adicionales hoy (PK cubre el lookup por `casa_acog_id`). En producción hay ~38 casas con estancias activas; el coste es despreciable. Si crece, FOSTER-04+ añadirá índice BTREE en `acogidas(casa_acogida_id, fecha_final) WHERE activo = true`. |
| Operador confunde "override auditado" con "anulación silenciosa" | El formulario exige `motivo` no vacío. La tabla de overrides tiene `motivo TEXT NOT NULL`. La UI muestra el motivo en el historial. Tres barreras técnicas (form check + service raise + DB NOT NULL). |
| `user_id` puede no estar en la sesión (caso edge de cookie pre-fix) | El handler hace `if not current_user.get("user_id"): raise 401`. Defensa explícita. En la práctica todas las cookies modernas ya llevan el campo. |
| Casa con `especie_preferente = NULL` (cualquier especie) puede llenarse con muchos animales de especies distintas y la capacity cuenta TODAS | Es la decisión D-GC-03 documentada. Una casa "cualquier especie" es más flexible pero su capacidad es global. Si en una issue futura se quiere separar capacidad por especie, se reemplaza la tabla `casas_acogida` con un JSONB `capacidad_por_especie` o dos columnas `capacidad_canina` + `capacidad_felina`. Out of scope hoy. |
| Override aplicado pero estancia nunca creada (operador abandona tras warning) | Audit log persiste el override. Es trazabilidad: si la casa tiene N overrides y M estancias resultantes (M <= N), podemos detectar overrides "huérfanos" en una query futura. NO bloquea nada — la trazabilidad es la herramienta correctiva, no la preventina. |

## Criterios de aceptación

1. `evaluate_assignment(client, animal_id, casa_id)` con animal CANINA y casa `especie_preferente = 'FELINA'` → `decision = "block"`, `reason` empieza con "la casa solo admite FELINA".
2. `evaluate_assignment` con animal CANINA y casa `especie_preferente = NULL` (cualquier especie) → `decision = "admit"` (no hay gate de especie).
3. `evaluate_assignment` con animal FELINA y casa `especie_preferente = 'FELINA'` y N estancias activas de FELINA < capacidad → `decision = "admit"`.
4. `evaluate_assignment` con animal FELINA y casa `especie_preferente = 'FELINA'` y N estancias activas de FELINA >= capacidad → `decision = "admit_with_warning"`, `warnings` contiene "capacidad excedida".
5. `evaluate_assignment` con animal_id inexistente → raise `ValueError` antes de evaluar el gate (no llega a hacer queries de casas).
6. `evaluate_assignment` con casa_id inexistente → raise `ValueError` antes de evaluar el gate.
7. `evaluate_assignment` con casa inactiva (`activo = false`) → raise `ValueError("la casa está dada de baja")`.
8. Capacity cuenta solo estancias con `animales.especie = casa.especie_preferente` (no mezcla especies en el count).
9. Capacity incluye casas con `especie_preferente = NULL` (cualquier especie): cuentan TODAS las estancias activas, sin importar la especie del animal.
10. `record_override` con `motivo` non-empty → INSERT en `foster_capacity_overrides`, retorna `FosterCapacityOverride` con los 6 campos.
11. `record_override` con `motivo = ""` → raise `ValueError("motivo es obligatorio")`, NO INSERT.
12. `record_override` con `motivo = "   "` (solo whitespace) → raise `ValueError`, NO INSERT.
13. `list_overrides_for_casa` devuelve overrides ordenados por `created_at DESC`.
14. `list_overrides_for_casa` con `casa_id` sin overrides → `[]`.
15. `GET /casas-acogida/{id}/asignar` renderiza form con campo `animal_id` UUID + (condicional) `motivo`. CSRF token presente.
16. `POST /casas-acogida/{id}/asignar` con `animal_id` válido, sin motivo, y `decision = "admit"` → 303 a `/acogidas/new?animal_id=X&casa_acogida_id=Y`.
17. `POST /casas-acogida/{id}/asignar` con `decision = "block"` → 422, render form con mensaje de error.
18. `POST /casas-acogida/{id}/asignar` con `decision = "admit_with_warning"` y `motivo` non-empty → graba override + redirect 303.
19. `POST /casas-acogida/{id}/asignar` con `decision = "admit_with_warning"` y `motivo` vacío → re-render form con warning visible y mensaje "el motivo es obligatorio para continuar".
20. `GET /casas-acogida/{id}/overrides` renderiza tabla con `created_at`, `animal_id`, `motivo`, `operador_user_id`.
21. `casas_acogida/detail.html` muestra "Estancias activas" (count), botón "Asignar animal" (link a `/asignar`), y sección "Histórico de overrides" (últimos 10).
22. Tests service: ~25 atoms cubriendo todos los paths del gate, capacity calculation, override validation, listado de overrides.
23. Tests routes: ~15 atoms cubriendo auth guard en 3 endpoints, CSRF en forms, no SQL en routes, redirects según decisión, render de warnings, override recording.
24. `log_safe` para `foster.capacity_override.recorded` con `casa_acogida_id`, `animal_id`, `operador`. NO expone el `motivo` (puede llevar PII).
25. Castellano, sin jerga, en templates y mensajes.