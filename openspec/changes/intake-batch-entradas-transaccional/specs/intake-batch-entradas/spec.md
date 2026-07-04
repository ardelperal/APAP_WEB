# Especificación: intake-batch-entradas

## Propósito

Cubrir el flujo operativo de Entradas Múltiples (legacy `TbEntradasMultiplesAuxIniciales`, discovery 2.1) que INTAKE-01 (#87/#88/#89) dejó abierto: registro de varias entradas a la vez con validación previa y commit atómico. Sin esta capability, el operador debe repetir N veces el formulario de alta individual, lo cual no modela la operativa real de intakes por lote.

## Requirements

### Requirement: Staging persistente

El sistema DEBE persistir los registros de un batch en una tabla `entradas_batch_staging` antes del commit, agrupados por un `batch_id` UUID. Cada fila DEBE preservar el orden del operador (`sequence`) y los datos del record (`animal_id`, `fecha_entrada`, `voluntario_entrada_id`, `origen`, `motivo`, `observaciones`).

#### Scenario: Stage de un batch válido

- **WHEN** el operador envía `POST /entradas/batch` con array de 5 records válidos
- **THEN** el sistema inserta 5 filas en `entradas_batch_staging` con el mismo `batch_id`
- **AND** redirige a `GET /entradas/batch/{batch_id}` mostrando preview con todas las filas en estado `valid`.

#### Scenario: Cancelación de un batch staged

- **WHEN** el operador pulsa "Cancelar" en `GET /entradas/batch/{batch_id}`
- **THEN** el sistema ejecuta `DELETE FROM entradas_batch_staging WHERE batch_id = :batch_id`
- **AND** redirige a `GET /entradas/batch/new`.

### Requirement: Validación por record

Cada record DEBE pasar las mismas validaciones que el CRUD individual de INTAKE-01: `animal_id` requerido y existente, `fecha_entrada` requerida, `voluntario_entrada_id` (si presente) debe apuntar a voluntario activo. Errores per-record se reportan en la preview SIN abortar el batch entero.

#### Scenario: Record con animal inexistente

- **WHEN** un record contiene `animal_id` que no existe en `animales`
- **THEN** ese record se stagea con `status="invalid"` y `error="animal_id no existe"`
- **AND** el resto de records válidos se stagean en estado `valid`.

#### Scenario: Record con voluntario inactivo

- **WHEN** un record contiene `voluntario_entrada_id` cuyo voluntario tiene `activo = false`
- **THEN** ese record se stagea con `status="invalid"` y `error="voluntario no está activo"`.

### Requirement: Unicidad cross-batch

Dentro de un mismo batch, NO puede haber dos records con la misma `(animal_id, fecha_entrada)`. Si la validación lo detecta, el batch entero es rechazado con `BatchValidationError` ANTES de cualquier escritura en staging.

#### Scenario: Duplicado dentro del batch

- **WHEN** el array contiene dos records con `animal_id="a1"` y `fecha_entrada="2026-07-04"`
- **THEN** el sistema rechaza el batch entero con 422 y error "Animal duplicado en el lote"
- **AND** `entradas_batch_staging` permanece vacío para ese `batch_id`.

### Requirement: Commit atómico

La copia de staging a `entradas` DEBE ocurrir en una sola transacción SQL. Si cualquier `INSERT INTO entradas` falla (FK violation, `entradas_natural_key` violation, etc.), TODOS los inserts del batch DEBEN rollbackear; staging DEBE quedar intacto para diagnóstico.

#### Scenario: Commit exitoso

- **WHEN** el operador confirma un batch con 5 records todos válidos
- **THEN** los 5 records aparecen en `entradas` con sus UUIDs asignados
- **AND** las 5 filas en `entradas_batch_staging` se eliminan en la misma transacción
- **AND** se redirige a `/entradas` con mensaje de éxito.

#### Scenario: Commit con violación durante la copia

- **WHEN** un INSERT del batch viola `entradas_natural_key UNIQUE (animal_id, fecha_entrada)` porque en la base de datos YA existe esa combinación para otro batch ya commiteado
- **THEN** NINGÚN record del batch aparece en `entradas`
- **AND** staging queda intacto con sus filas
- **AND** el sistema muestra en preview el error específico por record.

### Requirement: Acceso autenticado

Todos los endpoints de batch (`/entradas/batch/new`, `/entradas/batch`, `/entradas/batch/{id}`, `/entradas/batch/{id}/commit`, `/entradas/batch/{id}` con `DELETE`) DEBEN pasar por `require_authorized_user`. Un usuario no autenticado recibe 302 a `/login`.

### Requirement: Form con N filas

`GET /entradas/batch/new` DEBE renderizar un formulario con 5 filas de intake visibles por defecto y un control para añadir más filas (HTMX o equivalente). Todas las filas DEBEN incluir un `csrf_token` oculto (CSRF-01).

### Requirement: Castellano sin jerga

Templates y mensajes DEBEN usar castellano de España sin términos internos: "Entradas en lote", "Previsualización", "Confirmar lote", "Cancelar lote", "Animal duplicado en el lote", "animal_id no existe".

### Requirement: Logging seguro

Cada evento de batch (stage, commit, cancel) DEBE loggear vía `log_safe` desde `app/core/logging.py` con campos no sensibles: `event="entradas.batch.staged|committed|cancelled"`, `batch_id`, `record_count`, `actor_user_id`.

### Requirement: No SQL en routes

Las routes de batch DEBEN delegar a `batch_service` para todo acceso a datos. Ningún `client.execute_sql(...)` debe aparecer en `app/modules/entradas/batch_routes.py` (prohibido por regla layer boundaries AGENTS.md §1).