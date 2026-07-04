# Especificación: foster-estancias-acogida

## Propósito

Implementar el CRUD de la **estancia de acogida** (legacy `TbAcogidaAnimal`) como una capa de servicio que referencia la entidad `casas_acogida` (FOSTER-01, #43) y los voluntarios activos. La estancia registra el período durante el cual un animal está en una casa de acogida bajo el cuidado de uno o varios voluntarios. Sin este CRUD, FOSTER-03 (gate de capacidad, que necesita consultar estancias activas por casa) y FOSTER-04 (asignación de material, que necesita la estancia como FK estable) no tienen una FK estable a la que apuntar.

## Requirements

### Requirement: Columna FK estructurada a `casas_acogida`

La tabla `acogidas` DEBE incluir una columna `casa_acogida_id UUID REFERENCES casas_acogida(id)` para referenciar la casa donde se aloja el animal. La columna es opcional (NULL permitida) para preservar la retro-compatibilidad con estancias históricas que no tienen casa asignada (D-EST-01).

#### Scenario: Migración idempotente

- **WHEN** se ejecuta `ensure_domain_schema` en una base de datos donde `acogidas` ya tiene la columna
- **THEN** el `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` no falla ni duplica la columna.

- **WHEN** se ejecuta `ensure_domain_schema` en una base de datos limpia
- **THEN** se crea la tabla `acogidas` y luego se añade `casa_acogida_id` con la FK a `casas_acogida(id)`.

### Requirement: Validación de `animal_id` activo

`animal_id` es obligatorio. DEBE referenciar un animal existente en `animales` que esté activo (`activo = true`). Un animal inactivo o inexistente DEBE ser rechazado por el servicio con `ValueError` antes de cualquier escritura.

#### Scenario: Animal válido

- **WHEN** `create_acogida` recibe `animal_id` apuntando a un animal activo
- **THEN** la fila se inserta con la FK correctamente.

#### Scenario: Animal inexistente o inactivo

- **WHEN** `create_acogida` recibe `animal_id` apuntando a un animal que no existe o que tiene `activo = false`
- **THEN** el servicio lanza `ValueError("animal_id debe apuntar a un animal activo")` y NO escribe en la base de datos.

### Requirement: Validación de `casa_acogida_id` activa

`casa_acogida_id` es opcional. Si está presente, DEBE referenciar una casa existente en `casas_acogida` que esté activa (`activo = true`). Una casa inexistente o inactiva DEBE ser rechazada por el servicio con `ValueError`.

#### Scenario: Casa válida

- **WHEN** `create_acogida` recibe `casa_acogida_id` apuntando a una casa activa
- **THEN** la fila se inserta con la FK correctamente.

#### Scenario: Casa inexistente o inactiva

- **WHEN** `create_acogida` recibe `casa_acogida_id` apuntando a una casa que no existe o que tiene `activo = false`
- **THEN** el servicio lanza `ValueError("casa_acogida_id debe apuntar a una casa activa")` y NO escribe.

#### Scenario: Casa nula (retro-compat)

- **WHEN** `create_acogida` recibe `casa_acogida_id = null`
- **THEN** la fila se inserta con `casa_acogida_id = NULL` (preserva la retro-compat con estancias históricas).

### Requirement: Validación de voluntarios activos

Cualquier `voluntario_*_id` (`voluntario_acogida_id`, `voluntario_seguimiento1_id`, `voluntario_seguimiento2_id`, `voluntario_sanitario_id`) es opcional. Si está presente, DEBE referenciar un voluntario existente en `voluntarios` que esté activo (`activo = true`). Un voluntario inactivo DEBE ser rechazado (VOL-05).

#### Scenario: Voluntario válido

- **WHEN** `create_acogida` recibe `voluntario_acogida_id` apuntando a un voluntario activo
- **THEN** la fila se inserta con la FK correctamente.

#### Scenario: Voluntario inactivo (cualquiera de los 4)

- **WHEN** `create_acogida` recibe `voluntario_seguimiento1_id` apuntando a un voluntario con `activo = false`
- **THEN** el servicio lanza `ValueError("voluntario_seguimiento1_id debe apuntar a un voluntario activo")` y NO escribe.

### Requirement: Validación de `fecha_inicio`

`fecha_inicio` es obligatorio. NO DEBE ser vacío ni solo whitespace. Una cadena vacía DEBE ser rechazada con `ValueError`.

#### Scenario: Fecha válida

- **WHEN** `create_acogida` recibe `fecha_inicio = "2026-07-04"`
- **THEN** la fila se inserta con la fecha correcta.

#### Scenario: Fecha vacía

- **WHEN** `create_acogida` recibe `fecha_inicio = ""` o `fecha_inicio = "   "`
- **THEN** el servicio lanza `ValueError("fecha_inicio es obligatorio")` y NO escribe.

### Requirement: Cálculo de duración

`compute_duracion(acogida)` DEBE devolver el número entero de días entre `fecha_inicio` y `fecha_final`, o `None` si `fecha_final IS NULL` (estancia abierta). Si `fecha_inicio == fecha_final`, la duración es 0.

#### Scenario: Estancia abierta

- **WHEN** `acogida.fecha_final IS NULL`
- **THEN** `compute_duracion(acogida)` devuelve `None`.

#### Scenario: Estancia cerrada

- **WHEN** `acogida.fecha_inicio = "2026-01-01"` y `acogida.fecha_final = "2026-01-15"`
- **THEN** `compute_duracion(acogida)` devuelve `14`.

#### Scenario: Estancia mismo día

- **WHEN** `acogida.fecha_inicio = "2026-01-01"` y `acogida.fecha_final = "2026-01-01"`
- **THEN** `compute_duracion(acogida)` devuelve `0`.

### Requirement: Detección de estancia activa

`is_active(acogida)` DEBE devolver `True` solo si la estancia está activa (`activo = true`) Y no está cerrada (`fecha_final IS NULL`). En cualquier otro caso (inactiva, cerrada, soft-deleted), DEBE devolver `False`.

#### Scenario: Estancia abierta y activa

- **WHEN** `acogida.activo = true` y `acogida.fecha_final IS NULL`
- **THEN** `is_active(acogida)` devuelve `True`.

#### Scenario: Estancia cerrada

- **WHEN** `acogida.activo = true` y `acogida.fecha_final = "2026-07-04"` (no null)
- **THEN** `is_active(acogida)` devuelve `False`.

#### Scenario: Estancia soft-deleted

- **WHEN** `acogida.activo = false`
- **THEN** `is_active(acogida)` devuelve `False`.

### Requirement: `close_acogida` no es soft-delete

`close_acogida` DEBE poner `fecha_final = current_date` y `activo` se mantiene `true`. NO DEBE poner `activo = false`. Es un evento de "fin de estancia" (ciclo de vida), distinto de soft-delete (D-EST-04).

#### Scenario: Cierre exitoso

- **WHEN** el operador confirma `POST /acogidas/{id}/close`
- **THEN** la fila se actualiza con `fecha_final = current_date` y `activo = true`.

### Requirement: `delete_acogida` es soft-delete

`delete_acogida` DEBE marcar la fila como `activo = false` y `fecha_baja = now()`. La fila permanece en `acogidas` para preservar el histórico.

#### Scenario: Soft-delete exitoso

- **WHEN** el operador confirma `POST /acogidas/{id}/delete`
- **THEN** la fila se actualiza a `activo = false` y `fecha_baja = now()`.

### Requirement: Listado con filtro opcional

`list_acogidas(client, activas_solo: bool = False)` DEBE devolver todas las estancias (activas + cerradas) cuando `activas_solo = False`, y solo las que tienen `fecha_final IS NULL` cuando `activas_solo = True`. En ambos casos, ordenadas por `fecha_inicio DESC`.

#### Scenario: Listado sin filtro

- **WHEN** `list_acogidas(client)` se llama sin filtro
- **THEN** devuelve todas las estancias ordenadas por `fecha_inicio DESC`.

#### Scenario: Listado filtrado

- **WHEN** `list_acogidas(client, activas_solo=True)` se llama
- **THEN** devuelve solo las estancias con `fecha_final IS NULL`, ordenadas por `fecha_inicio DESC`.

### Requirement: Acceso autenticado y CSRF

Todos los endpoints de estancias DEBEN pasar por `require_authorized_user`. Las 4 forms (new, update, close, delete) DEBEN incluir un `csrf_token` oculto. La validación CSRF la aplica `CsrfMiddleware` (regla AGENTS.md §10).

### Requirement: Castellano sin jerga

Templates y mensajes DEBEN usar castellano de España sin términos internos: "Estancias de acogida", "Animal", "Casa", "Fecha de inicio", "Fecha de cierre", "Voluntario de acogida", "Voluntario de seguimiento", "Voluntario sanitario", "Duración", "Activa", "Cerrada", "Dar de baja", "Cerrar estancia".

### Requirement: Logging seguro

Cada evento de estancia (create, update, close, delete) DEBE loggear vía `log_safe` con campos no sensibles: `event="foster.acogida.created|updated|closed|deleted"`, `acogida_id`, `actor_user_id`. Nunca loggear IDs de voluntarios, animales o casas (son UUIDs no sensibles pero el patrón es evitar PII).

### Requirement: No SQL en routes

Las routes de acogidas DEBEN delegar a `acogidas_service` para todo acceso a datos. Ningún `client.execute_sql(...)` debe aparecer en `app/modules/acogidas/routes.py` (prohibido por regla layer boundaries AGENTS.md §1).
