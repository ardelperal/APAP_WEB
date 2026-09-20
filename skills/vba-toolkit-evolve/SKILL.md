---
name: vba-toolkit-evolve
description: Trigger: detecta fricciones en dysflow y codegraph-vba cuando el usuario audita, escanea, o nota drift. Redacta un issue auto-aprobado por sesión. NO verifica post-fix (eso es responsabilidad de la maintainer AI), NO modifica código de los toolkits. La parte de detect + redactar es el alcance de esta skill; el resto lo cubren `dysflow-codegraph-update` (post-release alignment) y `maintainer-prompt-drafter` (post-fix verification).
license: Apache-2.0
metadata:
  author: Andrés Román
  version: 2.0
  last_verified: 2026-08-31
  scope: ['vba', 'runtime']
  auto_invoke: ['evolving the VBA toolkit repo']
  tiers: ['vba', 'runtime']
---



# vba-toolkit-evolve

> **Redirect.** This skill was consolidated into `tool-incident-reporter` per Engram #27852 (2026-09-15) and the executive-phase decision recorded in `docs/audits/team-skills-common-project.md`. The detect + file loop, with target routing and incident preservation, lives there now. This source is kept for backward reference. For NEW tool-incident work — detecting friction in Dysflow/CodeGraph-VBA or any other tool the consumer uses, drafting a maintainer prompt, filing an upstream issue — load `tool-incident-reporter` instead.

> **Alcance (Phase 1 only).** Esta skill detecta fricciones y redacta issues; **no** verifica post-fix, **no** modifica toolkits. La re-alineación post-release del catálogo la conduce `dysflow-codegraph-update`; la verificación post-fix la conduce `maintainer-prompt-drafter`. La consolidación de los tres roles en un reportero único de incidentes está aprobada para estudio (ver `docs/audits/team-skills-common-project.md`).

Detecta fricciones en `DysTelefonica/dysflow` y `ardelperal/codegraph-vba` durante el trabajo VBA/Access, y redacta un issue por sesión con la fricción observada y la evidencia mínima reproducible. No verifica después de la implementación; eso es responsabilidad de la maintainer AI (vía `maintainer-prompt-drafter`) y de `dysflow-codegraph-update` tras un release.

## Mission

Mantener `dysflow` y `codegraph-vba` como herramientas usables y sin fricción para proyectos VBA/Access. La fricción observada durante el trabajo es la entrada; la salida es un issue con cuerpo reproducible, no la fix.

## Activation Contract

Cargue esta skill cuando se cumpla **al menos uno** de:

- El usuario pide auditar, escanear, o "ver issues" en cualquiera de los dos toolkits.
- Aparece un workaround durante una sesión de trabajo VBA/Access (un tool que misbehavió, una salida inesperada, un smoke pass que falló).
- El usuario nombra explícitamente la skill.

**No la cargue** para:

- Cambios internos a un solo módulo/form VBA → use `sdd-apply` o `vba-binary-sync`.
- Cambios en una sola skill del catálogo que no tocan runtime → use `skill-improver`.
- Verificar o adaptar tooling tras un fix del maintainer → use `maintainer-prompt-drafter` (con `vba-toolkit-evolve` solo como entrada de fricciones previas).
- Re-alinear tooling tras un release → use `dysflow-codegraph-update` (que ya cubre la fase de mantenimiento; esta skill NO la duplica).

## Hard Rules

- **No inferir versiones de los toolkits a partir de paths locales ni de docs.** El runtime expone `bootstrap.projectConfig` y `schema({view:"index"})`; usar esas superficies. Si necesita conocer la versión del toolkit, consumir la capability view, no leer paths rígidos.
- **Un issue por sesión de detección.** Acumular varias fricciones en un solo issue diluye la triage. Si la sesión encuentra dos fricciones independientes, redactar dos issues separados.
- **El issue debe llevar cuerpo reproducible**: qué se intentó, qué se obtuvo, qué se esperaba, y el snippet mínimo que lo reproduce. Sin cuerpo reproducible, el maintainer no puede priorizar.
- **Aplicar la etiqueta `status:approved` del repo destino** (o equivalente) cuando exista. Si la etiqueta no existe, redactar sin ella y avisar al usuario que debe crearla primero.
- **No modificar los toolkits.** Los clones locales de `dysflow` y `codegraph-vba` son superficies de inteligencia, no superficies de cambio. El fix es propiedad del maintainer; esta skill es estrictamente de detección.
- **No invocar `dysflow-codegraph-update` ni `dysflow-pointer-rollout` aquí.** Esas son skills del maintainer. Aquí solo se redacta el issue que motive esa intervención futura.
- **Después de redactar el issue, reportar al usuario** con: número del issue, fricción reportada, y siguiente paso esperado del maintainer. No auto-disparar nada.

## Decision Gates

| Trigger | Acción |
|---|---|
| El usuario pide auditar los toolkits | Recorrer las superficies runtime (bootstrap, schema) en busca de: dead ends, outputs inesperados, errores de contrato, lag visible entre docs y código. Redactar un issue por fricción encontrada. |
| Un workaround aparece mid-session | Redactar un issue que capture el workaround y la fricción que tapa. No resolver el workaround en la sesión; solo documentarlo. |
| El usuario dice "ya está", "acabó", "aplica tu protocolo" | **NO** es activación de esta skill. Es activación de `maintainer-prompt-drafter`. Si el usuario llega aquí por error, redirigir sin más. |

## Output Contract

| Key | Type | Description |
|---|---|---|
| `phase` | `"detect" \| "none"` | Siempre `detect` cuando esta skill corre. |
| `tools_scanned` | `string[]` | `["dysflow", "codegraph-vba"]` o subconjunto. |
| `issues_filed` | array | Cada item: `{repo, number, title, body_excerpt, friction_category, evidence_path}`. |
| `no_friction_found` | boolean | `true` si la sesión no encontró fricción nueva. |
| `next_recommended` | `"wait_maintainer" \| "none"` | `wait_maintainer` si se redactó al menos un issue; `none` si no. |
| `risks` | `string[]` | Issues abiertos previos del usuario en estos toolkits que pueden indicar trabajo relacionado. |

## Anti-patterns

| Symptom | Fix |
|---|---|
| Recomendar "actualizar el toolkit" sin haber redactado issue | Esta skill redacta issues; la actualización la conduce el maintainer. |
| Incluir la versión del toolkit en el cuerpo del issue | Dejar que la etiqueta `status:approved` y el triage del maintainer determinen la urgencia. La versión se ve en el release notes del repo. |
| Acumular varias fricciones en un solo issue | Una fricción, un issue. |
| Asumir paths locales rígidos (`C:\Proyectos\dysflow`, `C:\00repos\codigo\codegraph-vba`) | El runtime expone las superficies; usarlas. |
| Re-alinear el catálogo de skills propio aquí | Eso es `skill-propagation-sync`, no esta skill. |
| Polling automático en cada sesión VBA | El polling consume tokens sin valor. Esta skill se carga solo cuando el usuario pide o cuando aparece un workaround evidente. |

## References

- `dysflow-usage` — superficie runtime de Dysflow (bootstrap, schema, capabilities).
- `codegraph-usage` — superficie de CodeGraph (init, status, explore).
- `dysflow-codegraph-update` — re-alineación post-release del catálogo. No se invoca desde esta skill; la mainterer la invoca tras implementar.
- `maintainer-prompt-drafter` — protocolo de verificación post-fix. Esta skill redacta; `maintainer-prompt-drafter` verifica.
- `skill-propagation-sync` — re-alineación de skills del catálogo propio. No se invoca desde esta skill.
- `intake-roadmap-loop` — si una fricción recurrente escala a problema con cliente, archivarla como item del roadmap del ciclo. No es alcance de esta skill.
