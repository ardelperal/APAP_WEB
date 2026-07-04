# Especificación: foster-casas-acogida

## Propósito

Modelar la entidad **Casa de Acogida** (legacy `TbAcogidaCasas`, 21 columnas, 38 casas con estancias activas en producción) como tabla propia en la nueva aplicación, separada de la estancia (`acogidas`, ya creada en INTAKE-01). Sin esta entidad, FOSTER-02 (estancias con FK a casa), FOSTER-03 (gate de capacidad) y FOSTER-04 (asignación de material) no tienen una FK estable a la que apuntar.

## Requirements

### Requirement: Tabla propia con 1:1 al legacy

El sistema DEBE crear una tabla `casas_acogida` con 19 columnas de negocio del legacy `TbAcogidaCasas` (verificado vía Dysflow `projectId=apap` el 2026-07-04) en snake_case español + 2 mejoras justificadas (`id` UUID PK, `capacidad` INTEGER positivo).

#### Scenario: Schema incluye todos los campos legacy

- **WHEN** se ejecuta `ensure_domain_schema` en una base de datos limpia
- **THEN** la tabla `casas_acogida` se crea con al menos las columnas: `id`, `nombre`, `apellidos`, `dni_acogedor`, `calle`, `numero`, `piso`, `letra`, `localidad`, `provincia`, `cp`, `telefono`, `telefono2`, `email`, `vinculacion`, `caracteristicas`, `coche`, `especie_preferente`, `observaciones`, `capacidad`, `fecha_alta`, `fecha_baja`, `activo`, `updated_at`.

### Requirement: Validación de especie preferente

`especie_preferente` DEBE ser NULL o uno de los valores del enum legacy: `CANINA`, `FELINA`. Cualquier otro valor DEBE ser rechazado por el servicio con `ValueError` antes de cualquier escritura.

#### Scenario: Especie válida

- **WHEN** `create_casa_acogida` recibe `especie_preferente="CANINA"`
- **THEN** la fila se inserta correctamente.

#### Scenario: Especie inválida

- **WHEN** `create_casa_acogida` recibe `especie_preferente="AVES"`
- **THEN** el servicio lanza `ValueError("especie_preferente debe ser CANINA, FELINA o null")` y NO escribe en la base de datos.

### Requirement: Validación de capacidad

`capacidad` DEBE ser un entero positivo (> 0). Valores no enteros, cero o negativos DEBEN ser rechazados.

#### Scenario: Capacidad válida

- **WHEN** `create_casa_acogida` recibe `capacidad=3`
- **THEN** la fila se inserta con `capacidad=3`.

#### Scenario: Capacidad inválida

- **WHEN** `create_casa_acogida` recibe `capacidad=0` o `capacidad=-1`
- **THEN** el servicio lanza `ValueError("capacidad debe ser un entero positivo")`.

### Requirement: Validación de coche con tildes preservadas

`coche` DEBE ser exactamente `Sí` o `No` (con tilde en `Sí`). El constraint CHECK preserva la grafía legacy para evitar mojibake en round-trips de exportación.

#### Scenario: Coche válido

- **WHEN** `create_casa_acogida` recibe `coche="Sí"`
- **THEN** la fila se inserta con el valor exacto (incluida la tilde).

#### Scenario: Coche inválido

- **WHEN** `create_casa_acogida` recibe `coche="Si"` (sin tilde) o `coche="yes"`
- **THEN** el servicio lanza `ValueError("coche debe ser 'Sí' o 'No'")`.

### Requirement: Campos requeridos

`nombre`, `apellidos`, `calle`, `telefono` y `coche` son obligatorios. `capacidad` es obligatorio. Cualquier valor vacío o None en estos campos DEBE ser rechazado con `ValueError` antes de cualquier escritura.

#### Scenario: Campo requerido vacío

- **WHEN** `create_casa_acogida` recibe `nombre="   "` (whitespace)
- **THEN** el servicio lanza `ValueError("nombre es obligatorio")` sin escribir.

### Requirement: Soft-delete vía `activo = false`

`delete_casa_acogida` DEBE marcar la fila como `activo = false` y `fecha_baja = now()`. La fila permanece en `casas_acogida` para preservar el histórico de estancias (P1 fidelidad).

#### Scenario: Soft-delete exitoso

- **WHEN** el operador confirma `POST /casas-acogida/{id}/delete`
- **THEN** la fila se actualiza a `activo = false` y `fecha_baja = now()`; `list_casas_acogida` la excluye del listado por defecto.

### Requirement: Búsqueda por especie preferente

`list_casas_acogida(client, especie: str | None = None)` DEBE devolver las casas activas que aceptan la especie solicitada. Una casa con `especie_preferente IS NULL` cuenta como match para cualquier especie (casa "cualquier especie"), siguiendo el patrón conservador del legacy donde el filtro de especie solo se aplica si está definido.

#### Scenario: Búsqueda sin filtro

- **WHEN** `list_casas_acogida(client)` se llama sin especie
- **THEN** devuelve todas las casas activas ordenadas por `fecha_alta DESC`.

#### Scenario: Búsqueda con especie

- **WHEN** `list_casas_acogida(client, especie="CANINA")` se llama
- **THEN** devuelve las casas activas con `especie_preferente = 'CANINA'` OR `especie_preferente IS NULL`.

### Requirement: Acceso autenticado y CSRF

Todos los endpoints de foster DEBEN pasar por `require_authorized_user`. Las 3 forms (new, edit, delete) DEBEN incluir un `csrf_token` oculto. La validación CSRF la aplica `CsrfMiddleware` (regla AGENTS.md §10).

### Requirement: Castellano sin jerga

Templates y mensajes DEBEN usar castellano de España sin términos internos: "Casas de acogida", "Nombre", "Apellidos", "Dirección", "Código postal", "Teléfono", "Especie preferente", "Capacidad", "Coche disponible".

### Requirement: Logging seguro

Cada evento de foster (create, update, delete) DEBE loggear vía `log_safe` con campos no sensibles: `event="foster.casa_acogida.created|updated|deleted"`, `casa_acogida_id`, `actor_user_id`. Nunca loggear teléfono, email o DNI completo.

### Requirement: No SQL en routes

Las routes de foster DEBEN delegar a `foster_service` para todo acceso a datos. Ningún `client.execute_sql(...)` debe aparecer en `app/modules/foster/routes.py` (prohibido por regla layer boundaries AGENTS.md §1).