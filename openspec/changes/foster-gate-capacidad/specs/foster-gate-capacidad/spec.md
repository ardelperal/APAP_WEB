# Spec: FOSTER-03 — Gate de especie + advisory de capacidad con override auditado

skill_resolution: paths-injected

## ADDED Requirements

### REQ-GC-1: Gate de especie (hard block)

El sistema DEBE rechazar (decision `block`) la asignación de un animal a una casa cuya `especie_preferente` es distinta de la `Especie` del animal, sin permitir override. Si la casa tiene `especie_preferente IS NULL` (cualquier especie), el gate NO aplica (la casa acepta cualquier especie).

#### Scenario: Casa con especie preferente FELINA recibe animal CANINA → block

- **DADO** una casa con `especie_preferente = 'FELINA'`, `capacidad = 2`, `activo = true`
- **Y** un animal activo con `Especie = 'CANINA'`
- **CUANDO** `evaluate_assignment(client, animal_id, casa_id)`
- **ENTONCES** retorna `AssignmentDecision(decision = "block", reason = "la casa solo admite FELINA, no CANINA", warnings = ())`

#### Scenario: Casa con especie preferente NULL recibe animal CANINA → admit

- **DADO** una casa con `especie_preferente = NULL`, `capacidad = 2`, `activo = true`
- **Y** un animal activo con `Especie = 'CANINA'`
- **CUANDO** `evaluate_assignment(client, animal_id, casa_id)`
- **ENTONCES** retorna `AssignmentDecision(decision = "admit", reason = None, warnings = ())`

### REQ-GC-2: Capacity advisory (warning cuando se excede)

El sistema DEBE contar las estancias activas de la especie preferida en la casa y comparar contra `capacidad`. Si el count es `>= capacidad`, retorna `decision = "admit_with_warning"` con un `warning` describiendo el desborde. Si el count es `< capacidad`, retorna `decision = "admit"` sin warnings. El warning NO bloquea: la asignación puede proceder si el operador registra un override con motivo.

#### Scenario: Casa FELINA con capacidad 2 y 1 estancia activa de FELINA → admit

- **DADO** una casa con `especie_preferente = 'FELINA'`, `capacidad = 2`, `activo = true`
- **Y** una estancia activa en esa casa (`fecha_final IS NULL AND activo = true`) con animal FELINA
- **CUANDO** `evaluate_assignment(client, animal_felina_id, casa_id)`
- **ENTONCES** retorna `AssignmentDecision(decision = "admit", warnings = ())`

#### Scenario: Casa FELINA con capacidad 2 y 2 estancias activas de FELINA → admit_with_warning

- **DADO** una casa con `especie_preferente = 'FELINA'`, `capacidad = 2`, `activo = true`
- **Y** DOS estancias activas en esa casa con animales FELINA
- **CUANDO** `evaluate_assignment(client, animal_felina_id, casa_id)`
- **ENTONCES** retorna `AssignmentDecision(decision = "admit_with_warning", warnings = ("capacidad excedida: 2/2",))`

### REQ-GC-3: Capacity cuenta solo la especie preferida

El count de estancias activas DEBE filtrar por `animales.especie = casas_acogida.especie_preferente` cuando la casa tiene una especie preferente explícita. Una estancia con animal de OTRA especie NO cuenta contra la capacidad de la casa (es una anomalía operativa, no un ocupante legítimo de la capacidad).

#### Scenario: Casa FELINA con capacidad 2 y 1 estancia activa de CANINA → admit (la estancia CANINA no cuenta)

- **DADO** una casa con `especie_preferente = 'FELINA'`, `capacidad = 2`, `activo = true`
- **Y** una estancia activa en esa casa con animal CANINA
- **CUANDO** `evaluate_assignment(client, animal_felina_id, casa_id)`
- **ENTONCES** retorna `decision = "admit"` (la estancia CANINA no cuenta; el count de FELINA es 0)

### REQ-GC-4: Capacity en casa "cualquier especie" incluye todas las estancias

Cuando la casa tiene `especie_preferente IS NULL`, el count DEBE incluir TODAS las estancias activas (sin importar la especie del animal), porque la casa es indiferente a la especie.

#### Scenario: Casa "cualquier especie" con capacidad 2 y 2 estancias activas de especies distintas → admit_with_warning

- **DADO** una casa con `especie_preferente = NULL`, `capacidad = 2`, `activo = true`
- **Y** dos estancias activas: una con animal CANINA y otra con animal FELINA
- **CUANDO** `evaluate_assignment(client, animal_cualquiera_id, casa_id)`
- **ENTONCES** retorna `decision = "admit_with_warning"` (count = 2, capacidad = 2, excedida)

### REQ-GC-5: Validación de animal y casa antes del gate

`evaluate_assignment` DEBE verificar la existencia y actividad del animal y de la casa antes de evaluar el gate. Si alguno no existe o está inactivo, raise `ValueError` con un mensaje claro. NO procede con el gate si alguna entidad falta.

#### Scenario: Animal no existe → raise ValueError

- **DADO** un `animal_id` que no existe en `animales`
- **Y** una casa activa
- **CUANDO** `evaluate_assignment(client, animal_id, casa_id)`
- **ENTONCES** raise `ValueError("el animal no existe o no está activo")`

#### Scenario: Casa no existe → raise ValueError

- **DADO** un animal activo
- **Y** un `casa_id` que no existe en `casas_acogida`
- **CUANDO** `evaluate_assignment(client, animal_id, casa_id)`
- **ENTONCES** raise `ValueError("la casa no existe")`

#### Scenario: Casa inactiva (soft-deleted) → raise ValueError

- **DADO** un animal activo
- **Y** una casa con `activo = false`
- **CUANDO** `evaluate_assignment(client, animal_id, casa_id)`
- **ENTONCES** raise `ValueError("la casa está dada de baja")`

### REQ-GC-6: Override con motivo obligatorio

`record_override` DEBE requerir un `motivo` no vacío (tras `.strip()`). Si `motivo` es vacío o solo whitespace, raise `ValueError` y NO ejecuta el INSERT.

#### Scenario: Override con motivo "emergencia" → INSERT + retorna FosterCapacityOverride

- **DADO** un `motivo = "emergencia"`
- **Y** un `casa_id`, `animal_id`, `operador_user_id` válidos
- **CUANDO** `record_override(client, casa_id, animal_id, operador_user_id, "emergencia")`
- **ENTONCES** ejecuta `INSERT INTO foster_capacity_overrides ...`
- **Y** retorna un `FosterCapacityOverride` con los 6 campos

#### Scenario: Override con motivo vacío → raise ValueError, sin INSERT

- **DADO** un `motivo = ""`
- **CUANDO** `record_override(client, casa_id, animal_id, operador_user_id, "")`
- **ENTONCES** raise `ValueError("motivo es obligatorio y no puede estar vacio")`
- **Y** NO ejecuta ningún SQL

#### Scenario: Override con motivo solo whitespace → raise ValueError, sin INSERT

- **DADO** un `motivo = "   "`
- **CUANDO** `record_override(client, casa_id, animal_id, operador_user_id, "   ")`
- **ENTONCES** raise `ValueError("motivo es obligatorio y no puede estar vacio")`
- **Y** NO ejecuta ningún SQL

### REQ-GC-7: Listado de overrides por casa

`list_overrides_for_casa` DEBE devolver los overrides ordenados por `created_at DESC` (más reciente primero). Si la casa no tiene overrides, devuelve `[]`.

#### Scenario: Casa con 3 overrides → lista con 3 FosterCapacityOverride ordenados DESC

- **DADO** una casa con 3 overrides aplicados en distintos timestamps
- **CUANDO** `list_overrides_for_casa(client, casa_id)`
- **ENTONCES** retorna `list[FosterCapacityOverride]` con 3 elementos
- **Y** el primer elemento es el más reciente (`created_at` mayor)

#### Scenario: Casa sin overrides → lista vacía

- **DADO** una casa sin overrides aplicados
- **CUANDO** `list_overrides_for_casa(client, casa_id)`
- **ENTONCES** retorna `[]`

### REQ-GC-8: Route GET asignar renderiza form

`GET /casas-acogida/{id}/asignar` DEBE renderizar el formulario de asignación con el campo `animal_id` (UUID, vacío inicialmente) y un campo `motivo` (vacío, oculto si no hay warning previo). El form DEBE incluir el CSRF token.

#### Scenario: GET /casas-acogida/{casa_id}/asignar → 200 con form

- **DADO** una casa activa
- **CUANDO** `GET /casas-acogida/{casa_id}/asignar` con sesión autorizada
- **ENTONCES** retorna 200
- **Y** el HTML contiene un input `name="animal_id"`
- **Y** el HTML contiene `<input type="hidden" name="csrf_token" value="...">`

### REQ-GC-9: Route POST asignar ejecuta el gate y redirige

`POST /casas-acogida/{id}/asignar` DEBE ejecutar `evaluate_assignment` y según la decisión:

- `block` → 422 con el form re-renderizado y el mensaje de error.
- `admit` → 303 redirect a `/acogidas/new?animal_id=X&casa_acogida_id=Y`.
- `admit_with_warning` con `motivo` non-empty → graba override + 303 a `/acogidas/new?animal_id=X&casa_acogida_id=Y`.
- `admit_with_warning` sin `motivo` o con `motivo` whitespace → 422 con el form re-renderizado, el warning visible, y el mensaje "el motivo es obligatorio para continuar por encima de la capacidad".

#### Scenario: POST admit → 303 con query params

- **DADO** una casa y un animal que pasan el gate (especie OK, capacidad OK)
- **CUANDO** `POST /casas-acogida/{casa_id}/asignar` con `animal_id` válido
- **ENTONCES** retorna 303
- **Y** la cabecera `Location` es `/acogidas/new?animal_id=X&casa_acogida_id=Y`

#### Scenario: POST block → 422 con error

- **DADO** una casa FELINA y un animal CANINA (especie mismatch)
- **CUANDO** `POST /casas-acogida/{casa_id}/asignar` con `animal_id` del CANINA
- **ENTONCES** retorna 422
- **Y** el HTML contiene el mensaje "la casa solo admite FELINA, no CANINA"

#### Scenario: POST admit_with_warning con motivo → 303 + override registrado

- **DADO** una casa FELINA con capacidad 2 y 2 estancias activas de FELINA
- **Y** un animal FELINA
- **CUANDO** `POST /casas-acogida/{casa_id}/asignar` con `animal_id` y `motivo = "caso urgente"`
- **ENTONCES** ejecuta `INSERT INTO foster_capacity_overrides`
- **Y** retorna 303 a `/acogidas/new?animal_id=X&casa_acogida_id=Y`

#### Scenario: POST admit_with_warning sin motivo → 422 con warning visible

- **DADO** una casa con capacity excedida
- **CUANDO** `POST /casas-acogida/{casa_id}/asignar` con `animal_id` y `motivo = ""`
- **ENTONCES** retorna 422
- **Y** el HTML contiene el mensaje "capacidad excedida"
- **Y** el HTML contiene el mensaje "el motivo es obligatorio para continuar por encima de la capacidad"

### REQ-GC-10: Route GET overrides renderiza tabla

`GET /casas-acogida/{id}/overrides` DEBE renderizar una tabla con todas las overrides aplicadas a esa casa, ordenadas por `created_at DESC`.

#### Scenario: GET overrides con 3 overrides → tabla con 3 filas

- **DADO** una casa con 3 overrides aplicados
- **CUANDO** `GET /casas-acogida/{casa_id}/overrides` con sesión autorizada
- **ENTONCES** retorna 200
- **Y** el HTML contiene 3 filas en la tabla
- **Y** cada fila tiene `created_at`, `animal_id`, `motivo`, `operador_user_id`

### REQ-GC-11: Detail muestra estancias activas + botón asignar + histórico

`GET /casas-acogida/{id}` (detail) DEBE incluir:
- Una sección "Estancias activas" con el count de estancias activas de la casa.
- Un botón "Asignar animal" que enlaza a `/casas-acogida/{id}/asignar`.
- Una sección "Histórico de overrides" con los últimos 10 overrides (o mensaje "sin overrides" si está vacío).

#### Scenario: GET detail con 2 estancias activas y 1 override → muestra count, botón, override

- **DADO** una casa con 2 estancias activas y 1 override aplicado
- **CUANDO** `GET /casas-acogida/{casa_id}` con sesión autorizada
- **ENTONCES** retorna 200
- **Y** el HTML contiene "Estancias activas: 2"
- **Y** el HTML contiene un link `href="/casas-acogida/{casa_id}/asignar"`
- **Y** el HTML contiene una sección "Histórico de overrides" con 1 fila

### REQ-GC-12: Auditoría estructurada vía `log_safe`

`record_override` DEBE emitir un log estructurado `foster.capacity_override.recorded` con los campos `casa_acogida_id`, `animal_id`, `operador`. El `motivo` NO se loguea (puede llevar PII en texto libre).

#### Scenario: record_override emite log_safe sin el motivo

- **DADO** un override aplicado
- **CUANDO** se llama a `record_override(...)`
- **ENTONCES** se invoca `log_safe("foster.capacity_override.recorded", casa_acogida_id=..., animal_id=..., operador=...)`
- **Y** el log NO contiene el campo `motivo`

### REQ-GC-13: Auth guard y CSRF en todos los endpoints nuevos

Los 3 endpoints nuevos (`GET /asignar`, `POST /asignar`, `GET /overrides`) DEBEN requerir sesión autorizada (302 a `/login` si anónimo) y los forms POST DEBEN validar CSRF token (403 si falta).

#### Scenario: GET asignar anónimo → 302 /login

- **DADO** un cliente sin sesión
- **CUANDO** `GET /casas-acogida/{casa_id}/asignar`
- **ENTONCES** retorna 302 a `/login`

#### Scenario: POST asignar con CSRF inválido → 403

- **DADO** una sesión autorizada pero un POST sin CSRF token
- **CUANDO** `POST /casas-acogida/{casa_id}/asignar` con datos válidos
- **ENTONCES** retorna 403

## Skill Resolution

skill_resolution: paths-injected