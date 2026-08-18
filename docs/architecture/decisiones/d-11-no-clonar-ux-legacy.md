# D-11 — No clonar la UX del legacy

## Decision

El Access legacy tiene una UX específica que no se replica. La nueva UI usa los mismos datos y reglas, pero con un patrón moderno: componentes reutilizables, sistema de diseño, navegación clara. Ver [`legacy-initial-dashboard.md`](../legacy-initial-dashboard.md) y [`legacy-health-ui-workflow.md`](../legacy-health-ui-workflow.md) solo como referencia de QUÉ hace el legacy, no de CÓMO se ve.

## Quick path

- Los docs legacy son referencia de capacidad, no de UI.
- La nueva UI nace de los wireframes + design system, no del Access.
- Si un wireframe se parece al Access, es coincidencia, no objetivo.

## Problem statement

Los voluntarios que ya usan el Access tienden a esperar la misma disposición visual. Si APAP_WEB replica esa UX, perpetúa decisiones heredadas de los 2000 (formularios largos, navegación en cascada, layout denso) que el refugio arrastra por inercia. El cambio de plataforma es una oportunidad para modernizar la interacción sin romper la operativa.

## Evidence and scope

- Issue #130 (producto standalone) fija el target moderno.
- [`legacy-initial-dashboard.md`](../legacy-initial-dashboard.md) y [`legacy-health-ui-workflow.md`](../legacy-health-ui-workflow.md) son referencia de capacidad.
- [`openspec/changes/ux-ui-foundation/`](../../openspec/changes/ux-ui-foundation/) trabaja el sistema de diseño moderno.
- [`decisiones-proyecto.md` § D-12](decisiones-proyecto.md) design system pendiente.

## Options considered

| Opción | Pros | Contras |
|---|---|---|
| UX moderna, no clon del Access (aceptada) | Adoptable por audiencias nuevas; mejor contraste con productos comparables. | Voluntarios legacy necesitan un periodo de adaptación. |
| Skin 1:1 del Access (rechazada) | Familiaridad inmediata para el usuario actual. | Perpetúa decisiones de UX obsoletas; desalineado con D-01. |
| Híbrido con secciones clonadas (rechazada) | Compromiso aparente. | Inconsistencia; peor que elegir una dirección. |

## Goals

- La UI de APAP_WEB es reconocible como un producto de su tiempo, no como un clon retro.
- La operativa del refugio se preserva sin arrastrar el chrome del Access.
- Los voluntarios legacy pueden usar APAP_WEB con una sesión de onboarding, no con formación extensa.

## Non-goals

- Reescribir todas las pantallas del Access en paralelo.
- Eliminar la posibilidad de flujos equivalentes al Access (la operativa se conserva; el chrome cambia).
- Rediseñar la operativa del refugio.

## Non-negotiable invariants

- **Regla D-01**: APAP_WEB es producto standalone.
- **Regla D-05**: la fidelidad al legacy es de funcionalidad, no de UX.
- **Regla D-12** (cuando se implemente): design system reutilizable.

## Consequences

- Los wireframes se trabajan desde cero, no se copian del Access.
- Las issues `legacy-*` documentan QUÉ hace el legacy; los ADRs y wireframes definen CÓMO lo hace APAP_WEB.
- El onboarding de voluntarios legacy es parte del deliverable (ver [`openspec/changes/ux-ui-foundation/`](../../openspec/changes/ux-ui-foundation/)).

## When this changes

- Cuando D-12 (design system) se implemente, los componentes extraídos refuerzan esta regla.
- Si stakeholders externos validan la UX con el Access como referencia, se documenta como feedback y se ajusta sin volver al skin.