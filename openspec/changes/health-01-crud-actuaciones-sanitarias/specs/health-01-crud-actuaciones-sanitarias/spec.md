# Especificación: health-01-crud-actuaciones-sanitarias

## Propósito

Modelar la entidad **Actuación Sanitaria** (legacy `TbActuacionSanitaria`) como tabla propia en la nueva aplicación, separada del animal (`animales`) y de la estancia (`acogidas`). Permite registrar el historial veterinario de cada animal (vacunas, desparasitaciones, analíticas, esterilizaciones) preservando la fecha del acto, el tipo (referenciado al catálogo `catalogos_pruebas` per CATALOG-01), el veterinario, el voluntario responsable, el material utilizado y observaciones libres. El slice formaliza la regla de validación de fechas **D-24**.

## Requirements

### Requirement: Tabla `actuacion_sanitaria` con 10 columnas de dominio + 3 de auditoría

El sistema DEBE crear una tabla `actuacion_sanitaria` con 13 columnas: `id`, `animal_id`, `fecha`, `tipo_actuacion_id`, `veterinario`, `observaciones`, `voluntario_id`, `material_utilizado`, `fecha_alta`, `updated_at`, `activo`. FKs: `animal_id` → `animales(id)` (NOT NULL), `tipo_actuacion_id` → `catalogos_pruebas(id)` (NULL), `voluntario_id` → `voluntarios(id)` (NULL). La tabla se crea vía `ACTUACION_SANITARIA_CREATE_TABLE_SQL` en `app/core/domain.py`, cableada en `ensure_domain_schema`.

#### Scenario: Schema incluye todos los campos del dominio

- **WHEN** se ejecuta `ensure_domain_schema` en una base de datos limpia
- **THEN** la tabla `actuacion_sanitaria` se crea con todas las columnas listadas y las tres FKs (`animales`, `catalogos_pruebas`, `voluntarios`).

#### Scenario: Creación idempotente

- **WHEN** `ensure_domain_schema` se ejecuta en una base donde la tabla ya existe
- **THEN** la sentencia `CREATE TABLE IF NOT EXISTS` no falla ni duplica la tabla.

### Requirement: Validación D-24 de fecha en dos capas

La `fecha` de una `actuacion_sanitaria` DEBE cumplir simultáneamente:

1. Formato ISO `YYYY-MM-DD` parseable.
2. `fecha <= CURRENT_DATE` del servidor (no futuras).
3. Si el `animal_id` referenciado tiene `fecha_alta IS NOT NULL`, `fecha >= animales.fecha_alta`.

Si el animal tiene `fecha_alta IS NULL`, la regla 3 se omite (animales legacy importados sin metadato).

#### Scenario: Fecha futura rechazada (regla 2)

- **WHEN** `create_actuacion_sanitaria` recibe `fecha="2099-12-31"`
- **THEN** el servicio lanza `ValueError("fecha no puede ser futura (hoy es YYYY-MM-DD)")` antes de tocar la DB.

#### Scenario: Fecha malformada rechazada (regla 1)

- **WHEN** `create_actuacion_sanitaria` recibe `fecha="ayer"`
- **THEN** el servicio lanza `ValueError("fecha debe tener formato YYYY-MM-DD")` antes de tocar la DB.

#### Scenario: Fecha anterior al alta del animal rechazada (regla 3)

- **WHEN** `create_actuacion_sanitaria` recibe `fecha="2020-01-01"` y el animal tiene `fecha_alta="2024-06-01"`
- **THEN** la CTE devuelve 0 filas y `_raise_validation_error` lanza `ValueError("fecha es anterior al alta del animal (2024-06-01)")`.

#### Scenario: Fecha anterior permitida cuando fecha_alta es NULL (regla 3 exención)

- **WHEN** `create_actuacion_sanitaria` recibe `fecha="2020-01-01"` y el animal tiene `fecha_alta=NULL`
- **THEN** la CTE acepta la fila (la condición `fecha_alta IS NULL OR fecha_alta <= $fecha` se cumple por la rama NULL).

#### Scenario: Fecha igual al alta del animal aceptada

- **WHEN** `create_actuacion_sanitaria` recibe `fecha="2024-06-01"` y el animal tiene `fecha_alta="2024-06-01"`
- **THEN** la fila se inserta correctamente.

### Requirement: Validación de FK a `animales` activo

`animal_id` DEBE referenciar un animal existente en `animales` con `activo = true`. Si el id no existe o el animal está inactivo, el servicio DEBE lanzar `ValueError` antes de cualquier escritura.

#### Scenario: animal_id válido y activo

- **WHEN** `create_actuacion_sanitaria` recibe `animal_id` que existe en `animales` con `activo = true`
- **THEN** la fila se inserta correctamente (asumiendo fecha válida).

#### Scenario: animal_id inexistente

- **WHEN** `create_actuacion_sanitaria` recibe `animal_id` que no existe en `animales`
- **THEN** el servicio lanza `ValueError("animal_id debe apuntar a un animal activo (no encontrado: ...)")`.

#### Scenario: animal_id inactivo

- **WHEN** `create_actuacion_sanitaria` recibe `animal_id` que existe pero `activo = false`
- **THEN** el servicio lanza `ValueError("animal_id debe apuntar a un animal activo (inactivo: ...)")`.

### Requirement: Validación de FK a `voluntarios` activo (VOL-05)

`voluntario_id` es opcional. Si se proporciona, DEBE referenciar un voluntario existente en `voluntarios` con `activo = true`. Si no se proporciona o el voluntario está inactivo, el servicio debe rechazar la asignación.

#### Scenario: voluntario_id activo

- **WHEN** `create_actuacion_sanitaria` recibe `voluntario_id` que existe en `voluntarios` con `activo = true`
- **THEN** la fila se inserta correctamente con la FK asignada.

#### Scenario: voluntario_id inactivo (rechazo VOL-05)

- **WHEN** `create_actuacion_sanitaria` recibe `voluntario_id` que existe pero `activo = false`
- **THEN** el servicio lanza `ValueError("voluntario_id debe apuntar a un voluntario activo (inactivo: ...)")`.

#### Scenario: voluntario_id NULL permitido

- **WHEN** `create_actuacion_sanitaria` recibe `voluntario_id = None`
- **THEN** la fila se inserta con la FK NULL (un acto externo — p. ej. una vacunación por veterinario particular — no requiere voluntario APAP).

### Requirement: `tipo_actuacion_id` como FK opcional a `catalogos_pruebas`

`tipo_actuacion_id` es opcional. Si se proporciona, DEBE referenciar una fila existente en `catalogos_pruebas` (CATALOG-01, issue #65). El servicio NO verifica el catálogo — la FK se valida a nivel de DB. Si el id es inválido, la query falla con un `InsForgeError` que la ruta traduce a 422.

#### Scenario: tipo_actuacion_id válido

- **WHEN** `create_actuacion_sanitaria` recibe `tipo_actuacion_id` que existe en `catalogos_pruebas`
- **THEN** la fila se inserta con la FK asignada.

#### Scenario: tipo_actuacion_id NULL permitido

- **WHEN** `create_actuacion_sanitaria` recibe `tipo_actuacion_id = None`
- **THEN** la fila se inserta con la FK NULL (actuación sin clasificar — el operador la etiquetará más tarde).

### Requirement: Campos requeridos

`animal_id` y `fecha` son obligatorios. Cualquier valor vacío o None en estos campos DEBE ser rechazado con `ValueError` antes de cualquier escritura.

#### Scenario: animal_id vacío

- **WHEN** `create_actuacion_sanitaria` recibe `animal_id="   "` (whitespace)
- **THEN** el servicio lanza `ValueError("animal_id is required and cannot be empty")` sin escribir.

#### Scenario: fecha vacía

- **WHEN** `create_actuacion_sanitaria` recibe `fecha=""`
- **THEN** el servicio lanza `ValueError("fecha is required and cannot be empty")` sin escribir.

### Requirement: Soft-delete vía `activo = false`

`delete_actuacion_sanitaria` DEBE marcar la fila como `activo = false` y `updated_at = now()`. La fila permanece en `actuacion_sanitaria` para preservar el historial clínico (P1 fidelidad).

#### Scenario: Soft-delete exitoso

- **WHEN** el operador confirma `POST /sanidad/{id}/delete`
- **THEN** la fila se actualiza a `activo = false`; `list_actuaciones_sanitarias` la excluye del listado.

#### Scenario: Soft-delete atómico — fila ya inactiva

- **WHEN** `delete_actuacion_sanitaria` se invoca sobre un id ya con `activo = false`
- **THEN** el servicio devuelve `False` (la condición `WHERE activo = true` no matchea).

### Requirement: Búsqueda por `animal_id`

`search_actuaciones_by_animal(client, animal_id: str)` DEBE devolver las actuaciones activas (`activo = true`) del animal indicado, ordenadas por `fecha DESC` (más recientes primero), con `LIMIT 100`.

#### Scenario: animal con actuaciones

- **WHEN** `search_actuaciones_by_animal(client, "animal-123")` se llama y hay 3 filas activas
- **THEN** devuelve una `list` de 3 `ActuacionSanitaria`.

#### Scenario: animal sin actuaciones

- **WHEN** `search_actuaciones_by_animal(client, "animal-999")` se llama y no hay filas
- **THEN** devuelve una `list` vacía (no error).

### Requirement: `list_actuaciones_sanitarias` con filtro opcional `animal_id`

`list_actuaciones_sanitarias(client, *, animal_id: str | None = None)` DEBE devolver las actuaciones activas. Si `animal_id` se proporciona, filtra; si no, devuelve todas ordenadas por `fecha_alta DESC` con `LIMIT 100`.

#### Scenario: List sin filtro

- **WHEN** `list_actuaciones_sanitarias(client)` se llama sin `animal_id`
- **THEN** devuelve todas las actuaciones activas, más recientes primero, con `LIMIT 100`.

#### Scenario: List con filtro

- **WHEN** `list_actuaciones_sanitarias(client, animal_id="animal-123")` se llama
- **THEN** delega en `search_actuaciones_by_animal`.

### Requirement: Acceso autenticado y CSRF

Todos los endpoints de sanidad DEBEN pasar por `require_authorized_user` (lectura: cualquier usuario autorizado) o `require_writer_user` (escritura: rechaza `reader` con 403 per issue #144). Las 3 forms (new, edit, delete) DEBEN incluir un `csrf_token` oculto. La validación CSRF la aplica `CsrfMiddleware` (regla AGENTS.md §10).

### Requirement: Castellano sin jerga

Templates y mensajes DEBEN usar castellano de España sin términos internos: "Actuaciones", "Fecha", "Tipo de actuación", "Veterinario", "Observaciones", "Voluntario responsable", "Material utilizado".

### Requirement: Logging seguro

Cada evento de sanidad (create, update, delete) DEBE loggear vía `log_safe` con campos no sensibles: `event="sanidad.created|updated|deleted"`, `actuacion_id`, `animal_id`, `actor_user_id`. Nunca loggear `observaciones`, `veterinario`, `material_utilizado` (potencial PII / datos clínicos libres).

### Requirement: No SQL en routes

Las routes de sanidad DEBEN delegar a `sanidad_service` para todo acceso a datos. Ningún `client.execute_sql(...)` debe aparecer en `app/modules/sanidad/routes.py` (prohibido por regla layer boundaries AGENTS.md §1).