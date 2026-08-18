# D-40 — Virginia como validadora UAT (post-MVP)

## Decision

Cuando llegue el MVP, Virginia corre la validación UAT sobre `staging` usando la skill `feature-acceptance-uat` ([`docs/uat/uat-staging-<YYYY-MM-DD>.html`](../uat/)). El usuario revisa el sign-off y explícitamente instruye "merge to main". El agente NO preemptivamente flipea la fase — espera el OK explícito.

## Quick path

- Post-MVP: Virginia valida UAT en `staging`.
- Skill: `feature-acceptance-uat`.
- El agente NO mergea sin OK explícito del usuario.

## Problem statement

El refugio tiene una persona de referencia (Virginia) que conoce la operativa del día a día y puede validar que APAP_WEB cubre las necesidades reales. Sin un rol formal de validación, los merges post-MVP pueden pasar sin contraste operativo y aparecer bugs en producción que un usuario real habría detectado.

## Evidence and scope

- Mencionado por el usuario el 2026-07-03.
- Regla global `staging-acceptance-contract`.
- [`proceso.md`](../proceso.md) describe el flujo de validación.
- `feature-acceptance-uat` skill disponible en OpenCode.

## Options considered

| Opción | Pros | Contras |
|---|---|---|
| Virginia valida UAT (aceptada) | Representante del usuario real; contraste operativo. | Latencia de feedback; depende de su disponibilidad. |
| Auto-validación por mantenedor (rechazada) | Sin latencia. | Falta el contraste del usuario real. |
| Validación por panel多人 (rechazada) | Múltiples perspectivas. | Inviabilidad operativa en pre-MVP. |

## Goals

- Cada release post-MVP pasa por validación UAT antes de `main`.
- El sign-off incluye criterios de aceptación y casos de prueba ejecutables.
- El agente espera OK explícito; no preemptivamente flipea.

## Non-goals

- Hacer UAT pre-MVP (no aplica hasta release).
- Reemplazar a Virginia con otro validador.
- Internacionalizar el flujo de UAT.

## Non-negotiable invariants

- **Regla D-30**: pre-MVP single branch (UAT post-MVP es futuro).
- **Regla D-36**: mantenedor único autoriza el flip.

## Consequences

- El workflow post-MVP introduce un nuevo gate (UAT) entre `staging` y `main`.
- La skill `feature-acceptance-uat` produce HTML navegables por capacidad.
- Las decisiones de scope post-MVP las toma el usuario, no el agente.

## When this changes

- Cuando Virginia no esté disponible, se designa un validador sustituto con el mismo rol.
- Si se automatiza la UAT con IA, se documenta como D-UAT-02 con los límites.