# D-35 — Presupuesto de revisión: 400 líneas por PR

## Decision

Si la diff supera 400 líneas, dividir en PRs encadenadas vía skill `chained-pr` (default `stacked-to-main` en pre-MVP, dado que solo hay una rama — ver D-30).

## Quick path

- Diff ≤ 400 líneas por PR.
- Si supera: dividir en PRs encadenadas.
- Encadenadas usan `chained-pr`.

## Problem statement

PRs grandes (1000+ líneas) son imposibles de revisar con criterio: el revisor se pierde, los bugs se cuelan, el tiempo de revisión se dispara. Un presupuesto de 400 líneas obliga a dividir el trabajo en unidades cohesivas que se revisan en menos de treinta minutos cada una.

## Evidence and scope

- Regla histórica del proyecto.
- [`codebase/maintainer-playbook.md`](../codebase/maintainer-playbook.md) detalla el flujo de PR encadenadas.
- [`CONTRIBUTING.md`](../../CONTRIBUTING.md) menciona el presupuesto.
- `chained-pr` skill disponible en OpenCode.

## Options considered

| Opción | Pros | Contras |
|---|---|---|
| 400 líneas por PR + chained (aceptada) | Revisable en <30 min; unidades cohesivas. | Requiere disciplina de split. |
| Sin presupuesto (rechazada) | Libertad. | PRs monstruosas; review superficial. |
| 1000 líneas (rechazada) | Más margen. | Sigue siendo irrevisable con criterio. |

## Goals

- Cada PR se revisa en menos de treinta minutos.
- Una PR = una idea cohesiva.
- Los splits siguen `chained-pr` para preservar el orden de dependencias.

## Non-goals

- Fijar el presupuesto al byte exacto (es una guía, no una ley).
- Prohibir PRs grandes por motivos ceremoniales.
- Forzar splits artificiales cuando la cohesión pide una sola PR.

## Non-negotiable invariants

- **Regla D-30**: pre-MVP single branch.
- **Regla D-33**: TDD estricto (los splits mantienen tests verdes en cada paso).

## Consequences

- El mantenedor rechaza PRs que superan el presupuesto sin justificación.
- Las PRs encadenadas se mergean en orden (cada una depende de la anterior).
- `chained-pr` skill se invoca desde el orquestador cuando aplica.

## When this changes

- Si el equipo crece, el presupuesto puede relajarse a 600 líneas con reviewers dedicados.
- Si se introduce auto-merge para PRs pequeñas, el presupuesto se mantiene.