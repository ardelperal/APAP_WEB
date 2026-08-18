# D-41 — Trazabilidad obligatoria al cerrar issues

## Decision

Cada `gh issue close #N` incluye:

1. SHA(s) del commit de implementación (verificable con `git merge-base --is-ancestor <sha> main`).
2. Referencia al test que prueba el cumplimiento (path del módulo + nombre del test).
3. PR referencia.

Ver [`proceso.md`](../proceso.md) §6.3 y la regla global `github-issue-closure-traceability`.

## Quick path

- Cerrar issue = SHA(s) + test path + PR ref.
- Verificable con `git merge-base --is-ancestor`.
- Sin trazabilidad = issue no cerrada.

## Problem statement

Las issues cerradas sin trazabilidad son inútiles para auditoría: no se puede verificar qué cambió, qué test cubre el cambio, ni qué PR lo introdujo. Una "fix bug X" sin SHA es folklore. La trazabilidad es el contrato que permite que un revisor futuro pueda verificar el cumplimiento.

## Evidence and scope

- [`proceso.md`](../proceso.md) §6.3 codifica la regla.
- Regla global `github-issue-closure-traceability`.
- [`AGENTS.md`](../../AGENTS.md) §Premisas operativas refuerza.
- Cada cierre de issue del repo sigue este formato.

## Options considered

| Opción | Pros | Contras |
|---|---|---|
| SHA + test path + PR ref (aceptada) | Auditable; verificable; reproduce contexto. | Más fricción por issue. |
| Solo descripción libre (rechazada) | Cierre rápido. | No auditable. |
| Solo SHA (rechazada) | Más simple. | Sin evidencia de que el cambio funciona. |

## Goals

- 100% de las issues cerradas tienen SHA + test path + PR ref.
- El cierre es verificable con un comando git estándar.
- Las decisiones de scope se trazan al commit que las introdujo.

## Non-goals

- Forzar el formato SHA en issues de tipo `type:docs` (no aplica).
- Internacionalizar el formato de cierre.
- Reemplazar el cierre por un script automático (la decisión humana sigue siendo clave).

## Non-negotiable invariants

- **Regla D-30**: trazabilidad por SHA al cerrar.
- **Regla D-33**: TDD estricto (los tests verdes son la evidencia).
- **Regla D-36**: mantenedor único verifica antes de cerrar.

## Consequences

- El cierre de issue es un comando git + issue comment + verificación.
- Las issues sin trazabilidad se reabren hasta que se complete.
- El historial del repo es auditable de punta a punta.

## When this changes

- Si el equipo crece, la trazabilidad se mantiene (es la regla de auditoría).
- Si GitHub cambia el formato de issue closure, se actualiza esta ADR.