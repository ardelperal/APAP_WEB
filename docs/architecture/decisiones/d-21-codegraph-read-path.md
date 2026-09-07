# D-21 — CodeGraph es el read path principal

## Decision

CodeGraph (`@aroman22/codegraph-vba` CLI + MCP `codegraph_explore` + `codegraph node`) es la herramienta canónica de lectura de código. `Read` / `Grep` / `Glob` solo cuando CodeGraph no llega. El daemon auto-sync cubre el crecimiento del codebase con ~1s de lag; las sesiones nuevas empiezan con `codegraph status .` + `codegraph daemons` para confirmar salud.

Detalle completo en [`AGENTS.md`](../../AGENTS.md) §14 y [`proceso.md`](../proceso.md) §1.

## Quick path

- Antes de abrir código: `codegraph status .` + `codegraph daemons`.
- Para entender X: `codegraph_explore` con X como query.
- `Read` / `Grep` / `Glob` solo como fallback cuando CodeGraph no resuelve.

## Problem statement

Sin CodeGraph, una IA que aterriza en el repo necesita docenas de `Read` + `Grep` para ubicar el código relevante, con riesgo de quedarse con versiones obsoletas y de perder el call path entre símbolos. Para un repo en transición con slices hexagonales y legacy, ese coste se vuelve prohibitivo y la IA produce trabajo a ciegas.

## Evidence and scope

- Establecido 2026-07-03.
- [`AGENTS.md`](../../AGENTS.md) §14 fija CodeGraph como read path principal.
- [`proceso.md`](../proceso.md) §1 incluye CodeGraph en el flujo de inicio de sesión.
- [`docs/codebase/codegraph-conventions.md`](../codebase/codegraph-conventions.md) describe el uso operacional.
- `.codegraph/` existe en la raíz del repo como índice persistente.

## Options considered

| Opción | Pros | Contras |
|---|---|---|
| CodeGraph como read path principal (aceptada) | Un solo round-trip con call path; índice persistente. | Requiere daemon vivo; sincronización tras checkout. |
| Read + Grep + Glob puro (rechazada) | Sin dependencias externas. | Coste de tokens alto; riesgo de versiones obsoletas. |
| Híbrido sin prioridad (rechazada) | Flexibilidad aparente. | Sin guía, los contribuidores caen en el modo lento. |

## Goals

- Cualquier sesión arranca con CodeGraph vivo y consultado.
- El call path entre símbolos es visible antes de editar.
- Los archivos no cambian sin que CodeGraph se entere (auto-sync).

## Non-goals

- Reemplazar CodeGraph con un LSP o servidor de lenguaje.
- Indexar archivos fuera del repo (el índice es local).
- Garantizar latencia cero (1s de lag es aceptable).

## Non-negotiable invariants

- **Regla D-20**: stack FastAPI + HTMX + LocalBackend.
- **Regla D-30**: pre-MVP single branch.

## Consequences

- `.codegraph/` está en el repo como directorio del índice.
- Las sesiones nuevas ejecutan `codegraph status .` antes de empezar (ver [`proceso.md`](../proceso.md) §1).
- Los archivos modificados se sincronizan vía watcher; si el watcher está caído, se ejecuta `codegraph sync` manualmente.

## When this changes

- Si CodeGraph deja de mantenerse, se evalúa un reemplazo con contrato equivalente (índice local + call path + auto-sync).
- Si el repo crece por encima de un tamaño que CodeGraph no maneja bien, se segmenta el índice por slices.