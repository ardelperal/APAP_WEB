# D-32 — Documentación refleja código (Premisa P3)

## Decision

La doc (incluido este registro y [`roadmap.md`](../roadmap.md)) **refleja** el código, no al revés. Si divergen, gana el código. La actualización de la doc ocurre en la misma sesión en que se detecta la divergencia. Esto no es opcional — ver [`roadmap.md`](../roadmap.md) §9.

## Quick path

- Si código y doc divergen: gana el código.
- Actualizar doc en la misma sesión.
- Doc desactualizada = bug, no nota pendiente.

## Problem statement

La doc tiende a quedarse obsoleta: el código cambia, el redactor pospone la actualización, el siguiente contribuidor lee doc desactualizada y perpetúa el error. Este ciclo solo se cierra si la actualización de la doc es tan obligatoria como el commit, no una tarea de "cuando pueda".

## Evidence and scope

- Codificado en [`proceso.md`](../proceso.md) §0 P3.
- [`roadmap.md`](../roadmap.md) §9 lo refuerza.
- [`AGENTS.md`](../../AGENTS.md) §Premisas operativas P3.
- [`decisiones-proyecto.md`](decisiones-proyecto.md) § "Cómo revisar este documento" operativa la regla.

## Options considered

| Opción | Pros | Contras |
|---|---|---|
| Doc refleja código, actualización misma sesión (aceptada) | Cierra el ciclo de obsolescencia. | Sesiones más largas. |
| Doc primero, código después (rechazada) | Diseño upfront. | Código siempre va por delante de la doc; rompe el modelo mental. |
| Doc opcional, no mantenida (rechazada) | Menos trabajo. | Genera doc basura que nadie lee. |

## Goals

- Toda doc de comportamiento es coherente con el código en el momento del commit.
- La doc no es "wishful thinking"; describe lo que está en `main`.
- Las decisiones de diseño obsoletas se marcan como SUPERSEDED, no se borran.

## Non-goals

- Reescribir la historia de la doc.
- Eliminar decisiones obsoletas del registro.
- Forzar actualización de doc por commits cosméticos.

## Non-negotiable invariants

- **Regla D-30**: trazabilidad por SHA al cerrar issues.
- **Regla D-41**: trazabilidad obligatoria al cerrar issues.

## Consequences

- Las PRs que cambian comportamiento incluyen actualización de doc en el mismo commit (o PR enlazada).
- Las decisiones obsoletas se marcan SUPERSEDED dentro del ADR; no se borran (auditoría).
- Las issues `type:docs` reflejan drift detectado entre código y doc.

## When this changes

- Si el equipo crece y la doc se mantiene por un rol separado, se evalúa la separación.
- Si la doc pasa a generarse automáticamente desde código (typedoc, etc.), esta regla se reescribe para reflejar la nueva fuente.