# D-42 — Rollout del linter de anti-patrones documentation-alan-style

## Decision

El linter [`scripts/check_alantyle.py`](../../../scripts/check_alantyle.py) (issue #559) entra en el job `lint` de CI con `continue-on-error: true` durante el rollout inicial. La bandera se retire en un PR de seguimiento una vez que los autores de los documentos preexistentes limpien sus archivos.

Detalle de uso y semántica de cada código en [`scripts/check_alantyle.README.md`](../../../scripts/check_alantyle.README.md).

## Quick path

- El step de CI vive en [`.github/workflows/ci.yml`](../../../.github/workflows/ci.yml) tras el step `check_rules.py`.
- Emite los códigos `ALAN001`-`ALAN009` documentados en §10 de la skill `documentation-alan-style`.
- El primer PR de rollout no bloquea la luz roja de CI por hallazgos preexistentes.
- Para silenciar una línea se añade al final `<!-- alantyle-ignore -->` o `<!-- alantyle-ignore:ALANxxx -->`.

## Problem statement

La skill `documentation-alan-style` §10 prohíbe diez formas recurrentes (frontmatter incompleto, emojis decorativos, secuencias en mayúsculas fuera de acrónimos whitelisted, lenguaje ambiguo, marketing fluff, exceso de enlaces, párrafos sin punto y aparte, tabla de contenidos auto-generada, sección de instalación al final, duplicación entre docs raíz). Sin detector automático, la verificación depende de revisión humana y los nuevos PRs degradan la calidad documental sin que el job `lint` lo detecte.

El repositorio tiene documentos preexistentes con anti-patrones acumulados por la migración desde el estilo no-gateado previo. Activar el linter como gate bloqueante en el primer día convierte cada PR abierta en una lista enorme de hallazgos preexistentes no relacionados con el cambio, lo que mata la productividad del equipo y erosiona la confianza en el resto de gates.

## Evidence and scope

- Issue #559 — propuesta y tracking del linter.
- Skill `documentation-alan-style` §10 — contrato del detector.
- Repositorio absorbe la skill desde 2026-08-08; la mayoría de docs migrados (`README.md`, `AGENTS.md`, `DOCS.md`, `CODEBASE-GUIDE.md`) ya cumplen §10 tras las auditorías de los PRs #564, #565, #566, #567.
- `docs/decisiones-proyecto.md` y otros docs operativos pre-alan-style aún contienen anti-patrones que no deben bloquear el rollout.

## Options considered

| Opción | Pros | Contras |
|---|---|---|
| Gate bloqueante desde el primer commit (rechazada) | Pureza absoluta desde el día uno. | Convierte cada PR en un backlog no relacionado con el cambio; erosiona confianza en el resto de gates. |
| `continue-on-error: true` más ADR de rollout más ventana de limpieza (aceptada) | Señala hallazgos sin bloquear; los autores limpian por archivo o por PR. | Requiere un PR de seguimiento para retirar la bandera; los autores deben priorizar la limpieza. |
| Ignorar todo el árbol en CI y aplicar el linter solo en pre-commit (rechazada) | Cero impacto en PRs. | Pierde la señalización visible en la revisión; `--no-verify` salta pre-commit (AGENTS.md §32.P7). |

## Goals

- Detector activo en CI desde el primer PR de rollout.
- Cada PR nueva que introduzca un anti-patrón queda marcada con un hallazgo accionable.
- Los autores de docs preexistentes tienen margen para limpiar sin bloqueo de merge.
- La bandera `continue-on-error` se retire cuando la cuenta de hallazgos baja a cero o a un valor que el equipo acepta mantener.

## Non-goals

- Reescribir el linter para que se ejecute dentro de `check_rules.py` (responsabilidad separada: AST vs texto plano).
- Sustituir la revisión humana por el linter (el detector cubre nueve de diez formas; duplicación entre docs raíz requiere revisión).
- Forzar la limpieza de los docs preexistentes en este PR.

## Non-negotiable invariants

- **Regla D-30**: pre-MVP single branch. El rollout entra por un PR directo a `main` tras pasar el resto de gates.
- **Skill §10**: el detector no relaja ninguna de las diez prohibiciones; la bandera solo cambia la severidad de CI.
- **Tono castellano peninsular formal** (regla D-37): los mensajes del linter están en `usted` y párrafos cortos.

## Consequences

- El step aparece en rojo en el primer PR cuando hay hallazgos, pero el job pasa. La luz verde se recupera sola cuando no hay nuevos hallazgos.
- Los autores reciben los hallazgos como ruido informativo en cada PR hasta que limpien sus archivos. Se acepta como coste transitorio del rollout.
- Un PR de seguimiento retira `continue-on-error: true` cuando el contador agregado cae a cero. El script ya expone el contador en la línea final `check_alantyle` con un mensaje por archivo.
- El ADR documenta la fecha del rollout y el contrato de retirada para que un revisor externo entienda por qué el linter no falla hoy.

## When this changes

- Si la skill `documentation-alan-style` §10 evoluciona (nuevos anti-patrones), se actualiza el script y se versiona este ADR con el delta.
- Si el equipo decide retirar la bandera antes de que el contador llegue a cero, se abre un PR que documenta el residual aceptado como baseline shrink-only (mismo contrato que las otras ratchets del repo, AGENTS.md §19).
- Si el linter resulta tener falsos positivos estructurales (no por contenido preexistente), se documenta aquí y se abre issue para corregirlos antes de retirar la bandera.