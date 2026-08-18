# D-34 — Conventional Commits en inglés

## Decision

`tipo(scope): subject` en inglés, scope corto (`feat(auth)`, `fix(animals)`, `test(copy)`, `docs(roadmap)`, `chore(deps)`). Body que referencia la issue (`Closes #N` o `Refs #N`). PRs grandes: el cuerpo del commit incluye el run URL del CI que probó verde.

## Quick path

- `tipo(scope): subject` en inglés.
- Body referencia la issue (`Closes #N`).
- PRs grandes: cuerpo del commit con run URL de CI.

## Problem statement

Sin convención de commits, el `git log` se vuelve indescifrable: mensajes vagos ("cambios", "fix", "update") no permiten filtrar por tipo ni auditar cambios. Conventional Commits aporta formato machine-readable para changelogs automáticos y para que el mantenedor encuentre regresiones por tipo.

## Evidence and scope

- Regla histórica del proyecto.
- [`CONTRIBUTING.md`](../../CONTRIBUTING.md) detalla el formato.
- [`CHANGELOG.md`](../../CHANGELOG.md) se genera desde los commits.
- `git log --oneline` en `main` muestra el patrón vigente.

## Options considered

| Opción | Pros | Contras |
|---|---|---|
| Conventional Commits en inglés (aceptada) | Filtros y changelog automáticos; búsqueda simple. | Curva de aprendizaje para contribuidores nuevos. |
| Mensajes libres (rechazada) | Sin fricción. | Historial indescifrable; sin changelog automático. |
| Conventional Commits en castellano (rechazada) | Coherente con la UI. | Rompe herramientas que parsean en inglés; mezcla dominios. |

## Goals

- Cada commit es machine-parseable por tipo.
- El changelog se genera automáticamente desde `git log`.
- Las PRs grandes llevan run URL de CI como evidencia.

## Non-goals

- Forzar Conventional Commits en mensajes de PR (la PR es otra cosa).
- Internacionalizar los tipos a otros idiomas.
- Imponer un template de body fijo (solo el subject es obligatorio).

## Non-negotiable invariants

- **Regla D-37**: identificadores técnicos en inglés.
- **Regla D-33**: TDD estricto (cuerpo del commit incluye test path en issues cerradas).

## Consequences

- `git log --oneline` filtra por tipo con herramientas estándar.
- El script de release genera [`CHANGELOG.md`](../../CHANGELOG.md) a partir de los commits.
- Los scopes siguen los paquetes: `auth`, `animals`, `copy`, `roadmap`, `deps`, `migrations`, etc.

## When this changes

- Si el proyecto se internacionaliza, se evalúa bilingual commits (subject en inglés, body en castellano).
- Si se adopta otra convención (p. ej. Karma), se actualiza esta ADR.