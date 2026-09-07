# Propuesta: INTAKE-02 — entradas batch transaccional

skill_resolution: paths-injected

## Intención

Cerrar el flujo operativo de **Entradas Múltiples** (legacy `TbEntradasMultiplesAuxIniciales`, discovery 2.1) que INTAKE-01 (#87/#88/#89) dejó abierto: la posibilidad de registrar varias entradas a la vez en una sola sesión con validación previa y commit atómico. Esto desbloquea la operativa real de intakes por lote (rescates, transferencias, camadas) sin obligar al operador a repetir N veces el formulario de alta individual.

## Alcance

### Dentro
- Endpoint `POST /entradas/batch` que recibe un array de entrada records con el mismo shape público que INTAKE-01 (`animal_id`, `fecha_entrada`, opcional `voluntario_entrada_id`, `origen`, `motivo`, `observaciones`).
- Tabla de staging `entradas_batch_staging` que persiste los registros entre requests para soportar preview antes del commit (fidelidad al patrón legacy).
- Validación por record: campos requeridos, FK `animal_id` existe, FK `voluntario_entrada_id` (si presente) apunta a voluntario activo.
- Validación cross-batch: dentro del batch no puede haber dos records con la misma `(animal_id, fecha_entrada)` (P1: no solo dejar al DB constraint pillar el duplicado).
- Commit atómico: la copia de staging a `entradas` se hace en una sola transacción PostgREST; cualquier fallo (FK, `entradas_natural_key`, etc.) provoca rollback total.
- Cancelación explícita de un batch staged (`DELETE /entradas/batch/{batch_id}`) para limpiar staging sin commit.
- Vista `GET /entradas/batch/new` con formulario que admite N filas de entradas y un botón de previsualización.
- Vista `GET /entradas/batch/{batch_id}` con preview + estado de validación por record y botones "Confirmar" / "Cancelar".
- Tests rojo→verde: validación per-record, cross-batch, atomicidad, rollback, render de preview, auth guard, no SQL en routes.
- `docs/roadmap.md` refresca: quita #40 de §4.

### Fuera
- Creación de animales nuevos dentro del batch (los `animal_id` deben existir). Crear animales vía batch es scope de Fase 4 (Ficha Animal).
- Workflow de cesiones por propietario (ya mergeado en INTAKE-03, #41).
- Campos legacy `voluntario_salida_id`, `fecha_salida`, `fecha_entrega_propietario`, `donativo_entregador` (siguen siendo columnas físicas para `entrada.yaml` pero no se exponen vía batch).
- Materialización de `estado_actual_animal` (LIFECYCLE-SCHEMA-03, #69) y eventos de ciclo de vida.
- Adjuntos/anexos (DOC-03, DOC-04).

## Decisiones de producto

### D-BATCH-01: Staging persistente entre requests

La staging table es física (`entradas_batch_staging`) y no un stash en sesión, para que:
- El preview sobreviva a refresh / navegación atrás.
- La cancelación y el commit operen sobre el mismo estado (sin re-validar en cada paso).
- La fidelidad al legacy `TbEntradasMultiplesAuxIniciales` se preserve explícitamente.

### D-BATCH-02: Atomicidad vía transacción PostgREST

LocalBackend expone `client.execute_sql(sql, params)` por statement. Para atomicidad multi-row en una sola transacción usaremos un SAVEPOINT/RPC o un script multi-statement ejecutado por el `sql_runner` de la migración. La decisión técnica final se documenta en `design.md` §"Atomicidad".

### D-BATCH-03: Cross-batch uniqueness es validación de servicio, no solo DB

El constraint `entradas_natural_key UNIQUE (animal_id, fecha_entrada)` solo pilla el duplicado cuando el segundo insert alcanza la DB. En el batch, los dos records duplicados viajan juntos; si el primero entra y el segundo falla, el comportamiento depende de la atomicidad. La validación de servicio rechaza el batch entero con un error claro ANTES de tocar staging para no escribir basura, y la validación de DB queda como red de seguridad.

### D-BATCH-04: Fidelidad al lenguaje (castellano, sin jerga)

Templates y mensajes en castellano de España. Etiquetas: "Entradas en lote", "Previsualización", "Confirmar lote", "Cancelar lote", "Animal duplicado en el lote".

## Trazabilidad

- **Issue GitHub:** #40 (INTAKE-02).
- **SDD anterior:** `openspec/changes/archive/2026-06-25-intake-entradas-crud/` (INTAKE-01 schema+service+routes).
- **Discovery:** `docs/discovery/feature-02-intake-foster-adoption.md` §2.1 ("Entradas Múltiples", "Staging table `TbEntradasMultiplesAuxIniciales`").
- **Legacy:** `TbEntradasMultiplesAuxIniciales` (tabla staging) + `TbEntradas` (commit).
- **P1 (fidelidad al legacy):** superset del comportamiento legacy de Entradas Múltiples: staging pre-commit + validación pre-commit + atomic commit + rollback total. Las funcionalidades nuevas (auth, CSRF, logs) son aditivas.
- **Decisiones de proyecto afectadas:** ninguna nueva — son extensiones dentro del modelo D-05 (fidelidad al legacy) y D-31 (workflow VBA).
- **Cierra con:** `docs(roadmap)` refresca al mergear; cierre de #40 con SHA + test path.

## Riesgos

| Riesgo | Mitigación |
|---|---|
| Atomicidad no garantizada por LocalBackend/PostgREST vía `execute_sql` por statement | Validar en `design.md` el patrón real (script SQL transaccional ejecutado por el `sql_runner` de la migración, o endpoint RPC si LocalBackend lo soporta) y cubrir con test de integración que pruebe rollback |
| Tabla staging crece sin limpieza | `cancel_batch` y `commit_batch` limpian staging en cualquier salida; opcional: cron de purga de batches >24h (scope fuera) |
| Cross-batch uniqueness añade latencia | O(N) en memoria sobre el array del batch; despreciable para N<100 (caso operativo real) |
| Form con N filas dinámicas | Decisión: empezar con N fijo (5 filas) en template, con botón "Añadir fila" vía HTMX (ya usado en otros formularios del repo) |

## Criterios de aceptación

1. `POST /entradas/batch` con array válido → todos los records commiteados en `entradas`, staging limpio, redirect a `/entradas` con mensaje de éxito.
2. `POST /entradas/batch` con array que contiene un record inválido (ej. `animal_id` no existe) → 0 inserts en `entradas`, staging poblado, redirect a preview con error por record.
3. `POST /entradas/batch` con array que contiene dos records con el mismo `(animal_id, fecha_entrada)` → 0 inserts, error "Animal duplicado en el lote" en la preview.
4. `POST /entradas/batch/{batch_id}/commit` (o el flujo equivalente) → copia staging → `entradas` atómica; cualquier FK violation / natural key violation durante la copia rollbackea total, staging limpio o intacto según decisión técnica.
5. `DELETE /entradas/batch/{batch_id}` → staging limpio, redirect a `/entradas/batch/new`.
6. `GET /entradas/batch/new` → formulario con ≥5 filas + botones "Previsualizar" / "Cancelar".
7. `GET /entradas/batch/{batch_id}` → preview con tabla: index, animal_id, fecha_entrada, estado (válido / error), error message si lo hay; botones "Confirmar" y "Cancelar".
8. Tests: validación per-record, cross-batch uniqueness, atomicidad con mixed valid/invalid (rollback test), render de preview, auth guard, ausencia de SQL en routes.
9. CSRF token presente en los tres forms (batch/new, batch/preview, batch/commit).
10. `log_safe` para todo evento de batch (stage, commit, cancel) con campos no sensibles.