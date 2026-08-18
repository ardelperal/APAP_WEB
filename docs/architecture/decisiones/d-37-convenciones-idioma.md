# D-37 — Convenciones de idioma

## Decision

| Ámbito | Idioma |
|---|---|
| Issues y PRs | Castellano (España) |
| Documentación de producto, arquitectura y SDD | Castellano (España) |
| Artefactos técnicos (código, comentarios, docstrings, nombres) | Inglés por defecto |
| UI labels / mensajes visibles al usuario | Castellano de España (ver D-10) |
| Memoria interna / commit subjects | Inglés |

## Quick path

- Castellano: issues, PRs, doc de producto, UI.
- Inglés: código, comentarios, docstrings, nombres, commits.
- Memoria interna: inglés.

## Problem statement

Sin una tabla de idioma explícita, los contribuidores mezclan idiomas según conveniencia: docstrings en castellano, issues en inglés, comentarios en spanglish. Esto genera fricción de búsqueda, traducciones redundantes y copy desalineado. El contrato fija qué ámbito va en qué idioma para que cada artefacto sea consistente por sí mismo.

## Evidence and scope

- Regla histórica, decisión del 2026-06-17.
- [`AGENTS.md`](../../AGENTS.md) §Premisas operativas referencia las convenciones.
- [`decisiones-proyecto.md` § D-10](decisiones-proyecto.md) refuerza la UI en castellano.
- [`decisiones-proyecto.md` § D-34](decisiones-proyecto.md) refuerza los commits en inglés.
- [`CONTRIBUTING.md`](../../CONTRIBUTING.md) operacionaliza la tabla.

## Options considered

| Opción | Pros | Contras |
|---|---|---|
| Tabla de idioma por ámbito (aceptada) | Consistencia local por artefacto. | Requiere disciplina. |
| Todo en castellano (rechazada) | Coherencia absoluta. | Identificadores técnicos ilegibles para herramientas en inglés. |
| Todo en inglés (rechazada) | Compatible con herramientas. | UI y doc desalineadas con la audiencia. |

## Goals

- Cada artefacto es coherente por sí mismo (un docstring en inglés dentro de código en inglés, no spanglish).
- Las issues y PRs son leíbles por el voluntariado hispanohablante.
- El código y los identificadores son compatibles con herramientas estándar.

## Non-goals

- Internacionalizar la UI (cubierto por D-10; no hay plan actual).
- Traducir código histórico (cuesta más que el valor que aporta).
- Forzar a contribuidores externos a escribir en castellano (se acepta inglés en issues de externos).

## Non-negotiable invariants

- **Regla D-10**: UI en castellano de España.
- **Regla D-34**: commits en inglés.

## Consequences

- El linter puede validar que las cadenas de UI contienen tildes esperadas (futuro).
- Los mensajes de error se redactan en castellano aunque el código esté en inglés.
- La doc interna (memory, capturas) se queda en inglés.

## When this changes

- Si se internacionaliza la UI, se amplía la tabla con los idiomas destino.
- Si el refugio incorpora personal no hispanohablante, se evalúa bilingüismo por sección.