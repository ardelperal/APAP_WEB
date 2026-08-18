[← Back to Codebase Guide](../CODEBASE-GUIDE.md)

# Process

Esta página posee la regla §16 de AGENTS: el playbook operativo de issue a merge a close vive en [`docs/proceso.md`](../proceso.md), y AGENTS solo enuncia las cuatro premisas no negociables que lo atraviesan.

## What this page is

| Es | No es |
|---|---|
| Una nota corta que enlaza al playbook | Una copia de `docs/proceso.md` |
| El recordatorio de las cuatro premisas (P1-P4) | Una guía de uso de GitHub |

## Premisas no negociables

- **P1 — Fidelidad al legacy Access/VBA.** Toda capacidad del legacy se conserva o se reemplaza por un equivalente documentado en [`decisiones-proyecto.md`](../architecture/decisiones-proyecto.md). Una brecha descubierta abre un issue `type:bug gap:legacy`.
- **P2 — Escalera de duda de dominio.** Discovery doc → decisiones-proyecto → legacy-* → Dysflow MCP sobre el binario Access. Solo `vba-access` y `access-vba-tdd` están permitidos para trabajo Access en APAP_WEB; el resto del skill set queda excluido.
- **P3 — Los documentos reflejan el código.** Si divergen, gana el código y la doc se actualiza en la misma sesión.
- **P4 — Pre-MVP single-branch.** Todo el trabajo aterriza en `main` directamente; `staging` se reactiva solo por declaración explícita del usuario (ver [merge-workflow.md](merge-workflow.md) §15.4).

## Regla 16 — Issue work follows `docs/proceso.md`

El playbook de extremo a extremo para llevar un issue de GitHub de `open` a `merged and closed with evidence` vive en **[`docs/proceso.md`](../proceso.md)**. Codifica las cuatro premisas (P1 fidelidad al legacy Access/VBA como superconjunto funcional, P2 escalera de resolución de dudas de dominio con Dysflow al fondo, P3 docs reflejan código, P4 pre-MVP single-branch) más un workflow concreto (pre-flight → triage → SDD o directo → TDD → validación local → merge → close-with-trazability → sincronización de roadmap en la misma zancada).

**Reglas para el agente**:

1. **Lea `docs/proceso.md` al inicio de toda sesión que toque trabajo más allá de docs triviales.** El playbook cubre cómo clasificar un issue, cuándo lanzar SDD, cómo seguir TDD estricto, cómo validar localmente, cómo pushear y cerrar un issue con la trazabilidad que la regla global `github-issue-closure-traceability` exige, y cómo mantener `docs/roadmap.md` en sincronía. Si una pregunta tiene respuesta allí, no la reinvente.
2. **La premisa P1 es no negociable.** Antes de añadir o cambiar un campo o capacidad que refleje el legacy, confirme que el código nuevo preserva la intención del legacy (workflow, validación, cálculo, transición de estado, permiso). Si descubre una brecha, abra un issue `type:bug` con label `gap:legacy` — no la ignore en silencio. La cadena de trazabilidad por capacidad legacy es: capacidad legacy → su representación en el modelo nuevo → su cobertura de tests.
3. **En duda sobre el dominio**, siga la escalera P2: discovery doc → decisiones-proyecto → legacy-* → Dysflow MCP sobre el binario Access. Solo `vba-access` y `access-vba-tdd` están permitidos para trabajo Access en APAP_WEB; el resto del skill set queda excluido.
4. **El playbook documenta proceso, no reglas nuevas.** Si `docs/proceso.md` y la regla 16 de AGENTS divergen, AGENTS gana para todo lo de la columna "rules" (logging, CSRF, CRITICAL_HELPERS, audit, runbook, codegraph, merge workflow). El playbook es autoritativo para el orden de operaciones, la disciplina SDD/TDD y la plantilla de trazabilidad de cierre.
5. **Regla de refresco.** Cuando la política global de workflow cambie (nueva skill disponible, nueva regla de GitHub, nueva realidad operativa pre-MVP), actualice `docs/proceso.md` en el mismo PR o commit. El playbook no debe quedar atrás de AGENTS §15.

**Aplicación**: a nivel de PR. Si un PR mergeado viola P1 retroactivamente (tira o rompe una capacidad legacy sin entrada explícita en `decisiones-proyecto.md`), abra inmediatamente un issue `bug` de seguimiento. La revisión debe verificar que el comentario de cierre cita tanto un SHA de commit como una ruta de test antes de aprobar.

## Contributor checklist

- [ ] Al iniciar una sesión que toca código o specs, leyó `docs/proceso.md` y entendió las cuatro premisas.
- [ ] Cualquier divergencia con el legacy queda registrada en [`decisiones-proyecto.md`](../architecture/decisiones-proyecto.md) antes de cerrar el PR.
- [ ] El cierre del issue cita el SHA del commit y la ruta del test que prueba la capacidad.
- [ ] `docs/roadmap.md` se actualiza en la misma zancada que el merge, no después.

## Navigation

Previous: [Codebase Guide](../CODEBASE-GUIDE.md) | Next: [Merge workflow](merge-workflow.md)
