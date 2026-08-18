# D-24 — Regla de validación de fechas en actuaciones sanitarias

## Decision

La `fecha` de una `actuacion_sanitaria` debe cumplir simultáneamente:

1. **Formato ISO `YYYY-MM-DD`** parseable como `date`.
2. **`fecha <= CURRENT_DATE`** del servidor (no se permiten fechas futuras).
3. **Si el animal referenciado tiene `fecha_alta IS NOT NULL`, `fecha >= animales.fecha_alta`** (no se permiten fechas anteriores al alta del animal en el sistema).

Si el animal tiene `fecha_alta IS NULL` (animales legacy importados sin metadato), la cota inferior de la regla 3 se omite — solo se aplican las reglas 1 y 2.

## Quick path

- Fecha ISO `YYYY-MM-DD`, parseable como `date`.
- No futuro (regla del servidor).
- No anterior al alta del animal (cuando `fecha_alta` existe).
- Exención: animales sin `fecha_alta` (legacy) solo aplican reglas 1 y 2.

## Problem statement

Una fecha mal validada en una actuación sanitaria contamina la historia clínica del animal: fechas futuras rompen los informes de seguimiento, fechas anteriores al alta contradicen el alta formal del animal. La validación debe ser atómica para cerrar la ventana TOCTOU entre el SELECT del animal y el INSERT de la actuación.

## Evidence and scope

- Issue #50 (HEALTH-01, Fase 6a) abrió la conversación.
- [`roadmap.md`](../roadmap.md) §3 referencia la regla desde la planificación inicial.
- Implementación en dos capas ([`app/modules/sanidad/service.py`](../../app/modules/sanidad/service.py)):
  - Validación pura (sin DB) en `_validate_fecha_d24(fecha)` corre antes del INSERT/UPDATE.
  - Validación atómica con CTE en `_INSERT_ACTUACION_SANITARIA_SQL` y `_UPDATE_ACTUACION_SANITARIA_SQL`.
- Disambiguation en `_raise_validation_error` re-ejecuta la query cuando la CTE devuelve 0 filas.
- Tests: [`tests/test_sanidad.py`](../../tests/test_sanidad.py) cubre las 5 átomos TDD (reglas 1+2 puras + regla 3 atómica + exención NULL).

## Options considered

| Opción | Pros | Contras |
|---|---|---|
| Validación pura + CTE atómica (aceptada) | Cierra TOCTOU; mensaje claro al usuario. | Más SQL; requiere tests cuidadosos. |
| Validación solo en el service (rechazada) | Más simple. | TOCTOU permite fechas anteriores al alta entre SELECT y WRITE. |
| Validación solo en el form (rechazada) | UI amable. | Backends sin form (imports, scripts) la evaden. |
| Cota inferior con `animales.FNacimiento` (rechazada) | Más estricta. | Rompe el caso real: camadas con cachorros ya vacunados por el particular antes del alta. |

## Goals

- 100% de las `actuaciones_sanitarias` validadas atómicamente antes del commit en BD.
- Mensaje de error específico al usuario cuando falla la regla 3 (fecha anterior al alta vs animal inactivo vs voluntario inactivo vs tipo inexistente).
- Trazabilidad: la regla vive en código, se documenta aquí y se testea en [`tests/test_sanidad.py`](../../tests/test_sanidad.py).

## Non-goals

- Migrar `animales.FNacimiento` al modelo nuevo (la fecha de alta es la cota, no la de nacimiento).
- Aplicar la misma regla a otras entidades (cada entidad decide su regla de fecha).
- Bloquear fechas anteriores al alta del animal cuando la vacunación venga del particular (caso real documentado).

## Non-negotiable invariants

- **Regla D-04**: paridad de campos del animal con el legacy.
- **Regla D-05**: fidelidad al legacy (la fecha del alta es el límite inferior correcto).
- **Regla D-32**: código gana sobre doc; si cambia la implementación, esta ADR se actualiza en la misma sesión.

## Consequences

- El service de sanidad contiene dos validaciones (pura + CTE atómica); el linter no las puede fusionar porque cada una cumple un rol distinto.
- [`tests/test_sanidad.py`](../../tests/test_sanidad.py) cubre las 5 átomos (reglas 1, 2, 3, exención NULL, disambiguation).
- Los mensajes de error están en castellano de España (ver D-10).
- La regla es referencia para futuras entidades con validación temporal (peso, terapias, etc.).

## When this changes

- Si el refugio define un evento "primer contacto conocido" distinto al alta, se re-evalúa la cota inferior.
- Si se decide aplicar la misma regla a peso o terapias, se abre D-HEALTH-XX con la extensión.