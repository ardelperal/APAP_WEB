# Especificación: adopt-01-crud-adopciones

## Propósito

Modelar la entidad **Adopción** (legacy `TbAdopcion`) como tabla propia en la nueva aplicación, separada de la estancia (`acogidas`) y del animal (`animales`). Permite registrar el hito de "este animal deja la protectora con esta familia" preservando datos del adoptante, el voluntario de seguimiento, las fechas relevantes, los donativos y el tipo de adopción (regular / pre-adopción / judicial).

## Requirements

### Requirement: Schema adopciones con campos estructurados del adoptante

El sistema DEBE crear una tabla `adopciones` con 16 columnas (`id`, `animal_id`, `voluntario_seguimiento_id`, `fecha_adopcion`, `fecha_devolucion`, `donativo_preadopcion`, `donativo_adopcion`, `nombre_adoptante`, `dni_adoptante`, `telefono_adoptante`, `email_adoptante`, `entrada_origen_id`, `observaciones`, `fecha_alta`, `updated_at`, `activo`) + UNIQUE en `(animal_id, fecha_adopcion)`. Los datos del adoptante son columnas estructuradas (DNI, teléfono, email como `TEXT` separado), NO un único campo free-text.

#### Scenario: Schema incluye todos los campos del legacy

- **WHEN** se ejecuta `ensure_domain_schema` en una base de datos limpia
- **THEN** la tabla `adopciones` se crea con todas las columnas listadas, FKs a `animales`, `voluntarios` y `entradas`, y UNIQUE `(animal_id, fecha_adopcion)`.

### Requirement: Tipo de adopción como columna propia con CHECK enum

El sistema DEBE añadir la columna `tipo_adopcion TEXT NOT NULL DEFAULT 'regular' CHECK (tipo_adopcion IN ('regular', 'preadopcion', 'judicial'))` a la tabla `adopciones` vía migración `005_add_tipo_adopcion.sql`.

#### Scenario: Migration es idempotente

- **WHEN** `apply_sql_migrations` se ejecuta en una base con la tabla `adopciones` ya creada y la columna `tipo_adopcion` ausente
- **THEN** se aplica `005_add_tipo_adopcion.sql` y la columna aparece con default `'regular'` y CHECK constraint activo.

#### Scenario: Migration ya aplicada es no-op

- **WHEN** `apply_sql_migrations` se ejecuta en una base donde `005_add_tipo_adopcion.sql` ya fue aplicada
- **THEN** no se vuelve a aplicar (bookkeeping `web_sql_migrations` + `ADD COLUMN IF NOT EXISTS`).

### Requirement: Validación de FK a `animales` activo

`animal_id` DEBE referenciar un animal existente en `animales` con `activo = true`. Si el id no existe o el animal está inactivo, el servicio DEBE lanzar `ValueError` antes de cualquier escritura.

#### Scenario: animal_id válido y activo

- **WHEN** `create_adopcion` recibe `animal_id` que existe en `animales` con `activo = true`
- **THEN** la fila se inserta correctamente.

#### Scenario: animal_id inexistente

- **WHEN** `create_adopcion` recibe `animal_id` que no existe en `animales`
- **THEN** el servicio lanza `ValueError("animal_id does not reference an existing animal")` y NO escribe.

#### Scenario: animal_id inactivo

- **WHEN** `create_adopcion` recibe `animal_id` que existe pero `activo = false`
- **THEN** el servicio lanza `ValueError("animal_id does not reference an active animal")` y NO escribe.

### Requirement: Validación de FK a `voluntarios` activo (VOL-05)

`voluntario_seguimiento_id` es opcional. Si se proporciona, DEBE referenciar un voluntario existente en `voluntarios` con `activo = true`. Si no se proporciona o el voluntario está inactivo, el servicio debe rechazar la asignación.

#### Scenario: voluntario_seguimiento_id activo

- **WHEN** `create_adopcion` recibe `voluntario_seguimiento_id` que existe en `voluntarios` con `activo = true`
- **THEN** la fila se inserta correctamente con la FK asignada.

#### Scenario: voluntario_seguimiento_id inactivo (rechazo VOL-05)

- **WHEN** `create_adopcion` recibe `voluntario_seguimiento_id` que existe pero `activo = false`
- **THEN** el servicio lanza `ValueError("voluntario_seguimiento_id must reference an active volunteer")` y NO escribe.

#### Scenario: voluntario_seguimiento_id NULL permitido

- **WHEN** `create_adopcion` recibe `voluntario_seguimiento_id = None`
- **THEN** la fila se inserta con la FK NULL (un operador puede registrar una adopción sin asignar voluntario de seguimiento).

### Requirement: Campos requeridos

`animal_id`, `fecha_adopcion` y `nombre_adoptante` son obligatorios. Cualquier valor vacío o None en estos campos DEBE ser rechazado con `ValueError` antes de cualquier escritura.

#### Scenario: Campo requerido vacío

- **WHEN** `create_adopcion` recibe `nombre_adoptante="   "` (whitespace)
- **THEN** el servicio lanza `ValueError("nombre_adoptante is required and cannot be empty")` sin escribir.

#### Scenario: fecha_adopcion vacía

- **WHEN** `create_adopcion` recibe `fecha_adopcion=""`
- **THEN** el servicio lanza `ValueError("fecha_adopcion is required and cannot be empty")` sin escribir.

### Requirement: Soft-delete vía `activo = false`

`delete_adopcion` DEBE marcar la fila como `activo = false` y `updated_at = now()`. La fila permanece en `adopciones` para preservar el histórico (P1 fidelidad — un animal adoptado y devuelto sigue siendo trazable).

#### Scenario: Soft-delete exitoso

- **WHEN** el operador confirma `POST /adopciones/{id}/delete`
- **THEN** la fila se actualiza a `activo = false`; `list_adopciones` la excluye del listado.

#### Scenario: Soft-delete atómico — fila ya inactiva

- **WHEN** `delete_adopcion` se invoca sobre un id ya con `activo = false`
- **THEN** el servicio devuelve `False` (la condición `WHERE activo = true` no matchea).

### Requirement: Búsqueda por nombre de adoptante

`search_adopciones_by_adoptante(client, nombre_parcial: str)` DEBE devolver las adopciones activas cuyo `nombre_adoptante` contiene el texto parcial (case-insensitive vía `ILIKE`).

#### Scenario: Búsqueda parcial case-insensitive

- **WHEN** `search_adopciones_by_adoptante(client, "garcia")` se llama
- **THEN** devuelve las adopciones activas con `nombre_adoptante ILIKE '%garcia%'`.

#### Scenario: Búsqueda con match exacto

- **WHEN** `search_adopciones_by_adoptante(client, "María García López")` se llama
- **THEN** devuelve la adopción cuyo `nombre_adoptante` es exactamente `"María García López"`.

### Requirement: `is_active` derivado

`Adopcion.is_active` DEBE ser `True` cuando `fecha_devolucion is None`, `False` cuando `fecha_devolucion` tiene valor. NO se persiste como columna.

#### Scenario: Adopción vigente

- **WHEN** una adopción tiene `fecha_devolucion = None`
- **THEN** `adopcion.is_active` devuelve `True`.

#### Scenario: Adopción devuelta

- **WHEN** una adopción tiene `fecha_devolucion = "2026-08-15"`
- **THEN** `adopcion.is_active` devuelve `False`.

### Requirement: Acceso autenticado y CSRF

Todos los endpoints de adopciones DEBEN pasar por `require_authorized_user` (cubre key_user / admin / developer per #144). Las 3 forms (new, edit, delete) DEBEN incluir un `csrf_token` oculto. La validación CSRF la aplica `CsrfMiddleware` (regla AGENTS.md §10).

### Requirement: Castellano sin jerga

Templates y mensajes DEBEN usar castellano de España sin términos internos: "Adopciones", "Nombre del adoptante", "Fecha de adopción", "Fecha de devolución", "Donativo", "Tipo de adopción", "Voluntario de seguimiento".

### Requirement: Logging seguro

Cada evento de adopciones (create, update, delete) DEBE loggear vía `log_safe` con campos no sensibles: `event="adopciones.created|updated|deleted"`, `adopcion_id`, `animal_id`, `actor_user_id`. Nunca loggear `nombre_adoptante`, `dni_adoptante`, `telefono_adoptante`, `email_adoptante` (PII).

### Requirement: No SQL en routes

Las routes de adopciones DEBEN delegar a `adopciones_service` para todo acceso a datos. Ningún `client.execute_sql(...)` debe aparecer en `app/modules/adopciones/routes.py` (prohibido por regla layer boundaries AGENTS.md §1).