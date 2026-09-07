# Spec: LIFECYCLE — Animal State Resolver (issue #33, task 3.1)

## Context

Issue #33. Implementar el resolver de estado del animal (`calculateAnimalState()`,
`persistAnimalState()`, `closeAllOnDeath()`, `closePreviousSituation()`,
`canDeleteAnimal()`). El estado del animal es **calculado**, no almacenado, a partir
de los registros activos en las tablas de lifecycle (entradas, acogidas, adopciones).

## Current state on main@0ab533d

**Ya existe:**
- Tabla `animals` con columnas `fecha_alta`, `fecha_baja`, `activo` (soft-delete).
- Tabla `entradas` con `fecha_entrada`, `fecha_salida`, `activo`.
- Tabla `acogidas` con `fecha_inicio`, `fecha_final`, `activo`.
- Tabla `adopciones` con `fecha_adopcion`, `fecha_devolucion`, `activo`.
- `docs/discovery/state-machines.md` §1 con la state machine completa.
- `docs/legacy-lifecycle-transition-rules.md` con la derivación de estados.
- Issue #32 (`0049708`) — schema append-only `animal_lifecycle_events` + cache
  `animal_current_state` (LIFECYCLE-02) mergeado PR #320.

**Falta:**
- Servicio `calculateAnimalState()` que compute el estado actual derivándolo de
  los registros activos.
- Servicio `persistAnimalState()` que escriba el estado en `TbFichaAnimal.Situacion`
  y en `animal_current_state.cache_value`.
- `closeAllOnDeath()` — cierra todas las situaciones abiertas del animal.
- `closePreviousSituation()` — cierra la situación anterior antes de abrir una nueva.
- `canDeleteAnimal()` — verifica si un animal puede eliminarse (sin registros
 .lifecycle).
- Helpers para los 8 estados derivables y sus transiciones permitidas.

## Required contract

### Service functions

```python
def calculateAnimalState(client: SqlExecutor, nchip: str) -> AnimalState:
    """
    Deriva el estado actual del animal a partir de registros activos.
    No realiza writes — solo lee.

    Returns AnimalState enum: ALBERGUE | ACOGIDA | ADOPTADO | PENDIENTE_ENTRADA
    | PENDIENTE_NUEVA_SITUACION | ENTREGADO | FALLECIDO | INCOHERENTE
    """

def persistAnimalState(client: SqlExecutor, nchip: str, state: AnimalState) -> bool:
    """
    Escribe el estado en animal_current_state (cache) y en
    animal_lifecycle_events (append-only log).
    Retorna True si se escribió, False si no cambió.
    """

def closeAllOnDeath(client: SqlExecutor, nchip: str, fecha_defuncion: date) -> None:
    """
    Ante una defunción: cierra todas las situaciones abiertas
    (entrada activa, acogida activa, adopción activa) con la fecha de defunción.
    """

def closePreviousSituation(client: SqlExecutor, nchip: str, fecha_cierre: date,
                           tipo_situacion: SituacionTipo) -> None:
    """
    Cierra la situación anterior (Albergue → cierra entrada, Acogida → cierra
    acogida, Adoptado → cierra adopción) antes de abrir una nueva.
    """

def canDeleteAnimal(client: SqlExecutor, nchip: str) -> CanDeleteResult:
    """
    Verifica si un animal puede eliminarse. Retorna:
    CanDeleteResult(can_delete=True) si no tiene registros.lifecycle.
    CanDeleteResult(can_delete=False, reason="...")
    """
```

### Estado derivation rules (source: legacy `DameSituacion()`)

| Active record condition | Derived state |
|------------------------|---------------|
| Ningún registro activo + sin defunción + sin entradas | `PENDIENTE_ENTRADA` |
| Ningún registro activo + sin defunción + entradas existentessin entrega propietario | `PENDIENTE_NUEVA_SITUACION` |
| Ningún registro activo + sin defunción + última entrada con `FEntregaAPropietario` | `ENTREGADO` |
| Solo 1 entrada activa (`FSalida IS NULL`) + sin acogida/adopción activas | `ALBERGUE` |
| Solo 1 acogida activa (`FFinal IS NULL`) + sin entrada/adopción activas | `ACOGIDA` |
| Solo 1 adopción activa (`FDevolucion IS NULL`) + sin entrada/acogida activas | `ADOPTADO` |
| `FDefuncion` rellenada | `FALLECIDO` |
| Más de 1 tipo de registro activo simultáneamente | `INCOHERENTE` |

### Validación de integridad

- No puede haber más de 1 entrada activa, 1 acogida activa y 1 adopción activa
  simultáneamente (estado `INCOHERENTE` si se detecta).
- `AnimalBorrable` requiere: sin entradas, sin acogidas, sin adopciones,
  sin actuaciones sanitarias, sin terapias.

## Dependencies

- Task 3.1b (LIFECYCLE-02 schema append-only) — ya mergeado, PR #320 (`0049708`).
- Tablas `entradas`, `acogidas`, `adopciones` ya existentes en schema.
- LocalBackend client con `execute_sql`.

## Acceptance criteria

1. `calculateAnimalState` para cada uno de los 8 estados devuelve el estado correcto
   según las derivation rules documentadas.
2. `calculateAnimalState` para un animal con múltiples registros activos simultáneos
   devuelve `INCOHERENTE`.
3. `persistAnimalState` escribe en `animal_lifecycle_events` (append-only, sin overwrite).
4. `persistAnimalState` actualiza `animal_current_state.cache_value`.
5. `closeAllOnDeath` cierra todas las situaciones abiertas del animal.
6. `closePreviousSituation` cierra solo el tipo de situación indicado.
7. `canDeleteAnimal` rechaza animales con cualquier registro asociado.
8. Todos los helper functions son transaction-safe (atomic).

## Out-of-scope

- UI/rutas de la ficha animal (FE base #6 primero).
- Actualización de contadores globales del legacy (`CerrarTodasLasSituacionesPorFallecimiento`).
- El botón "Entrega a Propietario" desde estado Albergue (flujo completo).
- `RegistrarSituacion` con actualización de `UltimoEstadoAntesDeFallecido` en la tabla
  del animal (solo se actualiza el cache).
