# D-36 — Mantenedor único: aroman

## Decision

aroman autoaprueba issues y PRs del proyecto. Documentado en [`roadmap.md`](../roadmap.md) §1.

## Quick path

- aroman = mantenedor único.
- Autoaprueba issues y PRs del proyecto.
- No hay CODEOWNERS formal por persona; el flujo es por confianza.

## Problem statement

En un proyecto pre-MVP con un solo responsable, un CODEOWNERS formal con múltiples approvers bloquea decisiones que el responsable del proyecto puede y debe tomar. La autoaprobación por el mantenedor único es la regla operativa mientras no haya más contribuidores con peso de decisión.

## Evidence and scope

- [`roadmap.md`](../roadmap.md) §1 fija el rol.
- [`AGENTS.md`](../../AGENTS.md) menciona el mantenedor en las premisas.
- [`CODEOWNERS`](../../CODEOWNERS) documenta la cobertura por path.

## Options considered

| Opción | Pros | Contras |
|---|---|---|
| Mantenedor único con autoaprobación (aceptada) | Velocidad; sin bloqueos. | Concentración de conocimiento. |
| Aprobación por CODEOWNERS多人 (rechazada) | Distribución. | Inviabilidad operativa en pre-MVP. |
| Aprobación externa (rechazada) | Independencia. | Latencia insoportable. |

## Goals

- Cero bloqueos por falta de approver.
- Trazabilidad: cada merge cita SHA + test path (D-41).
- El mantenedor documenta sus decisiones en este registro.

## Non-goals

- Multi-mantenedor antes de que el proyecto lo justifique.
- CODEOWNERS多人 (permanece referencial, no activo).
- Delegación de merge sin trazabilidad.

## Non-negotiable invariants

- **Regla D-30**: pre-MVP single branch.
- **Regla D-41**: trazabilidad obligatoria al cerrar issues.

## Consequences

- aroman mergea sus propios PRs con `--no-ff`.
- Las decisiones se documentan con autor explícito.
- El proyecto depende de la disponibilidad del mantenedor; se documenta como riesgo conocido.

## When this changes

- Si entran dos o más contribuidores con peso de decisión, se activa CODEOWNERS多人.
- Si el mantenedor delega explícitamente (issue + ADR), se documenta la delegación.