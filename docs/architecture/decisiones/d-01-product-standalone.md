# D-01 — APAP_WEB es un producto profesional standalone

## Decision

APAP_WEB no es una migración de UI del Access legacy. Es una aplicación profesional, server-rendered (FastAPI + HTMX + Jinja2), usable y presentable a stakeholders, voluntarios, adoptantes y al público general. El Access legacy es la fuente de reglas, datos y workflows pero no la fuente de UX.

## Quick path

- Producto profesional = standalone, no es una skin del Access.
- UX moderna, server-rendered, components reutilizables.
- Datos y reglas vienen del Access vía migración; la presentación no.

## Problem statement

El equipo arrastraba el sesgo de tratar APAP_WEB como un clon del Access/VBA, lo que producía UX heredada, fricción con voluntarios y poco contraste con productos comparables. Se necesitaba un corte explícito: el sistema nuevo se diseña como un producto profesional, no como un reflejo del legacy.

## Evidence and scope

- Issue #130 (docs(product), abierta 2026-06-28) donde se formaliza la separación.
- [`README.md`](../../README.md) § "Qué es APAP_WEB" describe el target como producto profesional.
- [`roadmap.md`](../roadmap.md) § "Fases del producto" referencia este producto como entregable.
- [`legacy-initial-dashboard.md`](../legacy-initial-dashboard.md) y [`legacy-health-ui-workflow.md`](../legacy-health-ui-workflow.md) son referencias de QUÉ hace el legacy, no de CÓMO se presenta.

## Options considered

| Opción | Pros | Contras |
|---|---|---|
| Producto standalone (aceptada) | UX presentable; desacopla del legado; permite audiencias externas. | Requiere doble modelo mental (legacy vs nuevo) durante la transición. |
| Skin del Access (rechazada) | Familiar para Virginia; menos cambio cultural. | UX heredada; fricción con adoptantes; arrastra decisiones de los 2000. |
| Reescritura total en una sola release | Corte limpio. | Inviabilidad operativa: la operativa diaria no se puede parar. |

## Goals

- APAP_WEB se presenta como producto terminado a stakeholders externos.
- Voluntarios y adoptantes pueden usar la app sin conocer el Access.
- Las reglas del legacy se conservan (Premisa P1) sin arrastrar la UX.

## Non-goals

- Reescribir el legacy Access completo en un único release.
- Reemplazar la base de datos legacy en este producto (la convivencia web ↔ legacy se mantiene vía [`migration/`](../../migration/)).
- Cambiar las reglas de negocio del refugio.

## Non-negotiable invariants

- **Regla D-05**: fidelidad al legacy como superset funcional (ninguna capacidad se pierde).
- **Regla D-11**: la UX del legacy no se replica tal cual.
- **Regla D-37**: idioma de UI en castellano de España; identificadores técnicos en inglés.

## Consequences

- El equipo diseña con audiencias externas en mente desde el día uno.
- La migración del legacy es por capacidad, no por tabla (ver [`proceso.md`](../proceso.md) §6).
- Toda capacidad migrada se documenta con su ADR equivalente (ver D-04 y siguientes).
- Los usuarios del legacy deben poder usar APAP_WEB sin formación específica.

## When this changes

- Si el refugio abandona el Access como fuente de reglas y migra 100% al modelo nuevo, esta decisión se reemplaza por "APAP_WEB es la única fuente operativa".
- Si stakeholders externos demandan una API pública distinta a la webapp, se abre una nueva ADR (no se modifica esta).