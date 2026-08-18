# D-38 — `git config gentleai.stagingOnly` está unset en este repo

## Decision

El flag `gentleai.stagingOnly` se desactivó para APAP_WEB el 2026-07-03 (D-30, pre-MVP). El pre-push hook global sigue activo para otros proyectos. no re-armar en pre-MVP. Re-armar solo en el flip post-MVP per [`AGENTS.md`](../../AGENTS.md) §15.4.

## Quick path

- `gentleai.stagingOnly` está unset en APAP_WEB.
- Pre-push hook global sigue activo (otros proyectos).
- Re-armar solo con instrucción explícita del usuario.

## Problem statement

El hook pre-push global de OpenCode puede estar armado para que las pushes pasen por `staging` antes de llegar a `main`. En APAP_WEB pre-MVP eso es fricción inútil (D-30 fija single branch). El flag se desactiva localmente para no romper pushes directos a `main`.

## Evidence and scope

- Decisión del 2026-07-03, alineada con D-30.
- [`AGENTS.md`](../../AGENTS.md) §15.4 describe el flip post-MVP.
- La config vive en `.git/config` o `~/.gitconfig` global, no en el repo.

## Options considered

| Opción | Pros | Contras |
|---|---|---|
| Desactivar localmente (aceptada) | Push directo a `main` funciona. | Hay que recordar reactivar post-MVP. |
| Desactivar globalmente (rechazada) | Sin estado por repo. | Afecta a otros proyectos que sí quieren staging. |
| Mantener armado (rechazada) | Cero cambios. | Pushes directos fallan en pre-MVP. |

## Goals

- `git push` a `main` funciona sin pasos extra.
- El hook global sigue activo para otros proyectos del mantenedor.
- El flip a staging está documentado y solo se activa con OK del usuario.

## Non-goals

- Reescribir el hook pre-push.
- Internacionalizar la activación (es operativa, no copy).
- Forzar staging antes de MVP.

## Non-negotiable invariants

- **Regla D-30**: pre-MVP single branch.
- **Regla D-36**: mantenedor único autoriza el flip.

## Consequences

- El contribuidor debe verificar `git config --get gentleai.stagingOnly` antes de cada push.
- La doc del flip post-MVP vive en [`AGENTS.md`](../../AGENTS.md) §15.4.
- Los push de otros proyectos siguen pasando por staging per la config global.

## When this changes

- Cuando el usuario declare MVP, se reactiva el flag con instrucción explícita.
- Si el hook global cambia de comportamiento, se re-evalúa esta decisión.