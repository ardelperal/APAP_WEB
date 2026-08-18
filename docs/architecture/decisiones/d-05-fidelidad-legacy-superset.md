# D-05 — Fidelidad al legacy = superset funcional (Premisa P1)

## Decision

El sistema nuevo debe poder sincronizarse con el Access/VBA legacy preservando el 100% de las intenciones y funcionalidades del legacy, más las funcionalidades nuevas acordadas en [`roadmap.md`](../roadmap.md) §3 (Fases 3-7 + transversales) y [`discovery/`](../discovery/). Ni una menos.

Trazabilidad por capacidad legacy: capability legacy → su representación en el modelo nuevo → cobertura de tests. Cualquier gap descubierto en el nuevo modelo es `type:bug` con label `gap:legacy`.

## Quick path

- Toda capacidad legacy se conserva o se reemplaza por un equivalente documentado.
- Una brecha abre `type:bug gap:legacy`.
- La fidelidad se verifica por capacidad, no por tabla.

## Problem statement

La promesa al refugio al migrar a APAP_WEB es que ninguna operativa existente se pierde. Sin un compromiso explícito de superset, el equipo tiende a "limpiar" capacidades legacy por conveniencia técnica, lo que genera rechazo del voluntariado y pérdida de valor operativo. La fidelidad debe ser regla auditable, no buena intención.

## Evidence and scope

- Reafirmado por el usuario el 2026-07-03.
- Codificado en [`proceso.md`](../proceso.md) §0 P1 y [`AGENTS.md`](../../AGENTS.md) §Premisas operativas P1.
- [`legacy-*.md`](../legacy-initial-dashboard.md) documenta cada capacidad legacy.
- [`migration/`](../../migration/) implementa la sincronización bidireccional web ↔ Access.
- [`app/core/migration/`](../../app/core/migration/) orquesta el reconcile.
- [`decisiones-proyecto.md`](../decisiones-proyecto.md) § "Decisiones heredadas del legacy" lista capacidades pendientes.

## Options considered

| Opción | Pros | Contras |
|---|---|---|
| Superset funcional verificable (aceptada) | Cierra brechas proactivamente; auditable. | Más trabajo upfront; discovery continuo. |
| Reemplazar legacy por modelo nuevo (rechazada) | Más libertad técnica. | Rompe operativa; rompe la promesa al refugio. |
| Convivencia sin contrato (rechazada) | Aparente flexibilidad. | Genera silencios que se llenan con bugs. |

## Goals

- 100% de las capacidades legacy tienen un equivalente en APAP_WEB, o un gap-of-fidelity documentado.
- El [`migration reconcile`](../../migration/cli.py) cierra el ciclo web ↔ Access sin pérdida de datos.
- Cada capacidad migrada tiene tests que cubren su paridad.

## Non-goals

- Reescribir el Access desde cero en esta release.
- Eliminar capacidades legacy obsoletas sin consulta al refugio.
- Convertir el sistema nuevo en un clon UX del Access (ver D-11).

## Non-negotiable invariants

- **Regla D-03**: pivote sobre Animal; si una capacidad legacy no pivota sobre Animal, se documenta como gap.
- **Regla D-04**: paridad de campos obligatorios.
- **Regla D-32**: si código y doc divergen, gana el código y la doc se actualiza en la misma sesión.

## Consequences

- El equipo abre `type:bug gap:legacy` cada vez que descubre una capacidad legacy sin equivalente.
- [`proceso.md`](../proceso.md) §6.3 obliga a trazabilidad (SHA + test path) en cada cierre.
- El [`migration reconcile`](../../migration/cli.py) es un gate de release.
- Las decisiones heredadas del legacy (`decisiones-proyecto.md` §6) migran a ADRs individuales cuando aterrizan.

## When this changes

- Si el refugio cierra una capacidad legacy (decisión explícita del refugio), esa capacidad se elimina del contrato de fidelidad y se documenta en [`roadmap.md`](../roadmap.md).
- Si APAP_WEB se vuelve la única fuente operativa (sin legacy), esta decisión se reemplaza por una nueva D-FIDELITY-02.