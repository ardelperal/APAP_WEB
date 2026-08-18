# D-30 — Pre-MVP single-branch workflow

## Decision

Hasta que se alcance MVP, todo va a `main` directamente. Una sola rama al final de cada ciclo. No se crea ni se persiste `staging` en pre-MVP. Las issues cerradas se cierran con trazabilidad obligatoria (SHA + test path).

La reversión post-MVP está documentada en [`AGENTS.md`](../../AGENTS.md) §15.4 y se activa solo con instrucción explícita del usuario ("ya tenemos MVC" / equivalente).

## Quick path

- Pre-MVP: una sola rama (`main`).
- PRs mergean con `--no-ff`, nunca con `--delete-branch` (ver [`codebase/merge-workflow.md`](../codebase/merge-workflow.md)).
- Issues cerradas con SHA + test path (D-41).

## Problem statement

El equipo es de un mantenedor único. Un split `main` + `staging` añade fricción sin valor antes de MVP: ralentiza PRs, complica merges y exige mantener dos deploys. La simplicidad de una rama es correcta hasta que el producto esté validado por usuarios externos.

## Evidence and scope

- Establecido por el usuario el 2026-07-03.
- Codificado en [`AGENTS.md`](../../AGENTS.md) §15 y [`proceso.md`](../proceso.md) P4.
- [`codebase/merge-workflow.md`](../codebase/merge-workflow.md) documenta la política.
- [`architecture-insforge-stack.md`](../architecture-insforge-stack.md) § "Branch and deployment policy" describe el deploy desde `main`.

## Options considered

| Opción | Pros | Contras |
|---|---|---|
| Single branch pre-MVP (aceptada) | Cero fricción; velocidad de entrega. | Post-MVP requiere reorganizar. |
| main + staging desde el día uno (rechazada) | Más cerca del flujo post-MVP. | Fricción sin valor en pre-MVP. |
| Trunk-based sin PRs (rechazada) | Más velocidad aún. | Pierde trazabilidad y revisión. |

## Goals

- Un PR abierto contra `main` representa una unidad de trabajo cohesiva.
- `main` está siempre deployable.
- Cero ramas activas al final de cada ciclo de trabajo.

## Non-goals

- Activar `staging` antes de MVP.
- Reemplazar la revisión humana por auto-merge.
- Múltiples versiones en producción.

## Non-negotiable invariants

- **Regla D-36**: mantenedor único aprueba issues y PRs.
- **Regla D-38**: `gentleai.stagingOnly` está unset en este repo.
- **Regla D-41**: trazabilidad obligatoria al cerrar issues.

## Consequences

- El hook pre-push global puede estar armado para otros proyectos; en APAP_WEB está desactivado.
- Cada PR mergea con `--no-ff` (preserva la rama del feature en el historial).
- No se usa `--delete-branch` al mergear (las ramas viven hasta limpieza manual).
- Coolify deploya `apap-web` desde `ardelperal/APAP_WEB:main`.

## When this changes

- Cuando el usuario declare "ya tenemos MVP / MVC", se reactiva `staging` per [`AGENTS.md`](../../AGENTS.md) §15.4.
- Si el equipo crece, la política se evalúa; sigue siendo decisión del mantenedor único.