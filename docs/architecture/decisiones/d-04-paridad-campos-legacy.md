# D-04 — Paridad de campos del animal con el Access legacy

## Decision

El modelo `animal` (tabla y formulario) del sistema nuevo tiene paridad de campos obligatorios con el Access legacy, según [`discovery/data-model-completeness.md`](../discovery/data-model-completeness.md). Cualquier gap entre campos legacy y campos nuevos es `type:bug` con label `gap:legacy` (ver D-05 y [`proceso.md`](../proceso.md) §4.6).

## Quick path

- Cada campo `required=True` en TbFichaAnimal (Access) existe como `NOT NULL` o con valor por defecto válido en el modelo nuevo.
- Si falta un campo, se abre issue `type:bug gap:legacy` antes de cerrar cualquier PR del slice animal.
- La paridad se mide por capacidad, no por tabla legacy.

## Problem statement

Sin paridad explícita, los voluntarios que migran datos del Access al sistema nuevo descubren campos faltantes en producción (p. ej. "fecha de alta del animal" sin equivalente). Esto rompe la confianza en el sistema nuevo y obliga a re-trabajo. La paridad debe ser un contrato verificable, no un acuerdo verbal.

## Evidence and scope

- Issue #129 (fix(animals)) abrió la conversación y formalizó la regla.
- [`discovery/data-model-completeness.md`](../discovery/data-model-completeness.md) lista los campos legacy obligatorios.
- [`legacy-lifecycle-transition-rules.md`](../legacy-lifecycle-transition-rules.md) documenta los campos derivados de transiciones legacy.
- [`proceso.md`](../proceso.md) §4.6 define la label `gap:legacy`.
- [`app/modules/sanidad/service.py`](../../app/modules/sanidad/service.py) implementa D-24 sobre los campos del animal.

## Options considered

| Opción | Pros | Contras |
|---|---|---|
| Paridad explícita y verificable (aceptada) | Cierra gaps antes de producción; auditable. | Requiere discovery continuo del legacy. |
| Paridad implícita "lo que salga" (rechazada) | Más rápido al inicio. | Genera incidentes; rompe confianza. |
| Paridad solo de campos visibles en UI (rechazada) | Reduce el scope. | Pierde campos internos que afectan auditoría. |

## Goals

- 100% de los campos `required=True` del legacy existen en el modelo nuevo.
- Cada gap detectado abre un `type:bug gap:legacy` con referencia al campo legacy.
- La paridad se verifica en el cierre del PR del slice (no post-mortem).

## Non-goals

- Paridad de campos `required=False` del legacy (opcional).
- Migración automática de datos en este PR (cubre D-05 + [`migration/`](../../migration/)).
- Replicar validaciones VBA complejas del Access en la primera iteración.

## Non-negotiable invariants

- **Regla D-05**: fidelidad al legacy como superset funcional.
- **Regla D-03**: pivote sobre Animal.
- **Regla D-32**: si código y doc divergen, gana el código y se actualiza la doc en la misma sesión.

## Consequences

- El discovery del legacy es un input continuo, no un entregable único.
- Cada PR de slice animal verifica paridad con [`discovery/data-model-completeness.md`](../discovery/data-model-completeness.md) en su checklist.
- Las labels `gap:legacy` son trazables vía [`proceso.md`](../proceso.md) §6.3.
- El modelo de datos puede tener campos que el legacy NO tiene (esos requieren D-XX individual).

## When this changes

- Si el refugio elimina un campo del Access (decisión del refugio), se actualiza [`discovery/data-model-completeness.md`](../discovery/data-model-completeness.md) y la paridad de ese campo deja de ser obligatoria.
- Si se descubre que un campo legacy NO debiera existir en el nuevo (semántica obsoleta), se documenta como gap-of-fidelity con justificación.