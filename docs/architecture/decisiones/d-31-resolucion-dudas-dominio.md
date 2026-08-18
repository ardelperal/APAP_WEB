# D-31 — Resolución de dudas del dominio en orden fijo (Premisa P2)

## Decision

Cuando algo no queda claro (modelo de datos, regla de negocio, comportamiento esperado, edge case), la escalera de duda es:

1. [`docs/discovery/feature-XX-*.md`](../discovery/) (versión revisada).
2. [`docs/architecture/decisiones-proyecto.md`](decisiones-proyecto.md) (este registro).
3. [`docs/legacy-<área>.md`](../legacy-initial-dashboard.md) (legacy documentado).
4. **El Access directamente vía Dysflow MCP** (`projectId: apap`) — `dysflow_list_tables`, `dysflow_get_schema`, `dysflow_get_relationships`, `dysflow_query_sql` (read), `dysflow_count_rows`.

Solo `vba-access` y `access-vba-tdd` están permitidos como skills para Access. Los demás skills de Access (`access-vba-sync`, `access-query`, `access-form-creation`, `access-sandbox`) están excluidos del workflow de APAP_WEB.

Si tras las 4 capas la duda persiste: **preguntar al usuario**, no asumir.

## Quick path

- Discovery → decisiones → legacy → Dysflow MCP sobre Access.
- Solo `vba-access` y `access-vba-tdd` permitidos.
- Si la duda persiste, preguntar al usuario.

## Problem statement

Sin una escalera de duda explícita, una IA puede caer en:
- Asumir equivalencias nuevas ↔ legacy sin documentar.
- Saltar al binario Access directamente, perdiendo el contexto de las decisiones vigentes.
- Usar skills de Access no permitidos en APAP_WEB, contaminando el flujo.

La escalera ordena el coste cognitivo de menor a mayor, preservando las decisiones formales antes de tocar el binario.

## Evidence and scope

- [`proceso.md`](../proceso.md) P2 codifica la regla.
- [`roadmap.md`](../roadmap.md) §7 referencia la escalera.
- [`discovery/`](../discovery/) contiene los docs consolidados por capacidad.
- [`legacy-*.md`](../legacy-initial-dashboard.md) documenta capacidades legacy.
- Dysflow MCP (`projectId: apap`) opera sobre el binario Access.

## Options considered

| Opción | Pros | Contras |
|---|---|---|
| Escalera 4 capas (aceptada) | Orden explícito; preserva decisiones. | Requiere disciplina del contribuidor. |
| Ir directo al binario (rechazada) | Más rápido en casos puntuales. | Pierde decisiones vigentes; riesgo de malinterpretar reglas. |
| Sin escalera (rechazada) | Libertad total. | Genera decisiones implícitas y drift. |

## Goals

- Cualquier duda de dominio se resuelve en orden, de menor a mayor coste.
- Las decisiones vigentes (este registro) son input antes del binario.
- Las skills excluidas (`access-vba-sync`, etc.) no contaminan el flujo.

## Non-goals

- Reescribir las skills excluidas.
- Eliminar el acceso directo al binario (sigue siendo la última capa).
- Internacionalizar la escalera a otros idiomas.

## Non-negotiable invariants

- **Regla D-05**: fidelidad al legacy (el binario es la fuente).
- **Regla D-32**: si código y doc divergen, gana el código.
- **Regla D-37**: idioma UI en castellano de España.

## Consequences

- Las issues de tipo "duda de dominio" citan explícitamente en qué capa se resolvió.
- Las skills excluidas están listadas; el contribuidor sabe qué no usar.
- El binario Access se consulta con Dysflow, no con `mdbtools` ni scripts ad-hoc.

## When this changes

- Si el legacy se desconecta (se cierra el `.accdb`), la capa 4 se desactiva y la escalera queda en 3.
- Si se aprueba una skill de Access adicional, se actualiza esta ADR.