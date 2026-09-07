# D-02 — Home = dashboard con tarjetas de pendientes operativos

## Decision

La página principal (`/`) muestra tarjetas con pendientes operativos: entradas recientes, voluntarios, animales, próximos seguimientos. Sigue el patrón descrito en [`legacy-initial-dashboard.md`](../legacy-initial-dashboard.md), modernizado a un patrón "bandeja de pendientes" con realtime en una segunda iteración.

## Quick path

- `/` es una bandeja operativa, no un welcome estático.
- Tarjetas por dominio (animales, voluntarios, entradas, seguimientos).
- Realtime vía LocalBackend Realtime queda diferido a una segunda iteración.

## Problem statement

El Access legacy mostraba al entrar una "bandeja de pendientes" con lo que el voluntario tenía que atender ese día. APAP_WEB debía decidir si la home era welcome (estilo marketing) o bandeja operativa. La segunda opción preserva el valor de uso del primer pantallazo y reduce el coste cognitivo de entrada.

## Evidence and scope

- Issue #130 (producto standalone) fija el target.
- Issue #127 (home con tarjetas, cerrada) formaliza el patrón bandeja.
- Issue #131 (labels castellanos) alinea idioma con D-10.
- [`legacy-initial-dashboard.md`](../legacy-initial-dashboard.md) documenta el patrón legacy como referencia de QUÉ.

## Options considered

| Opción | Pros | Contras |
|---|---|---|
| Bandeja operativa (aceptada) | Reduce coste cognitivo; alinea con la operativa real del refugio. | Requiere queries agregadas rápidas; algo más de trabajo en Fase 2. |
| Welcome estático (rechazada) | Más rápido de implementar; visualmente "amable". | Desperdicia el primer pantallazo; voluntarios deben navegar para saber qué hacer. |
| Dashboard analítico (rechazada) | Encaja con Mentalidad data-driven. | Desalineado con la operativa diaria; más útil para management que para voluntarios. |

## Goals

- El voluntario ve lo urgente en menos de tres segundos tras abrir la app.
- Las tarjetas siguen el orden de prioridad operativa (entradas recientes > seguimientos próximos > animales pendientes).
- El patrón es extensible: añadir una nueva tarjeta no debe tocar la home.

## Non-goals

- Realtime en la primera iteración (diferido a Fase posterior).
- Personalización por rol del voluntario (todos ven la misma bandeja inicialmente).
- Métricas o KPIs de management.

## Non-negotiable invariants

- **Regla D-01**: APAP_WEB se presenta como producto, no como skin.
- **Regla D-10**: idioma UI castellano de España.
- **Regla D-11**: no se replica visualmente el dashboard del Access.

## Consequences

- La home depende de queries agregadas por dominio — son el primer consumidor del `queries/` layer.
- Las tarjetas son componentes reutilizables (ver D-12 design system pendiente).
- Los conteos deben ser tolerantes a LocalBackend caído (degradación a estado "sin datos" con `aria-live=polite`).
- Cuando se active realtime, las tarjetas son el primer consumidor de [`local_backend_realtime`](../../app/core/local_backend.py).

## When this changes

- Si el refugio cambia la operativa diaria y la home ya no es el punto de entrada, se abre D-HOME-02 con la nueva disposición.
- Cuando se implemente D-12 design system, los componentes de tarjeta se extraen a la librería compartida.