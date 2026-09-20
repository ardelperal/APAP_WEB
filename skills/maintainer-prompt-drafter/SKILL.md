---
name: maintainer-prompt-drafter
description: Trigger: maintainer prompt, upstream escalation. Generates structured, verifiable prompts for the maintainer AI of any tool. Use when you detect a bug or gap in a tool you use and want to escalate to the maintainer with TDD discipline. Produces ready-to-forward prompts with reproducibility evidence, "what NOT to touch" guardrails, and acceptance outputs.
metadata:
  author: Andrés Román
  version: 1.0
  last_verified: 2026-09-05
  scope: ['universal']
  auto_invoke: ['drafting a maintainer prompt']
  tiers: ['universal']
license: Apache-2.0
---



# maintainer-prompt-drafter

> **Redirect.** This skill was consolidated into `tool-incident-reporter` per Engram #27852 (2026-09-15) and the executive-phase decision recorded in `docs/audits/team-skills-common-project.md`. The maintainer-prompt structure (modes, variants, 7-step flow) lives there now. This source is kept for backward reference with existing prompts already archived under `docs/prompts/`. For NEW tool-incident work — detecting friction, drafting a maintainer prompt, filing an upstream issue — load `tool-incident-reporter` instead.

Genera prompts estructurados y verificables para la IA mantenedora de la herramienta afectada. Pensado para que un orquestrador consumidor (vos) produzca prompts consistentes y que el mantenedor los arranque sin pedir contexto extra.

## Disparador

Has detectado un bug o gap en una herramienta que usás (MCP, CLI, librería, framework, etc.) y querés escalar al mantenedor. NO escribas el prompt desde cero cada vez — este skill lo estructura por vos.

## Inputs esperados (lo que necesitás antes de arrancar)

- **El gap verificado:** síntoma, evidencia de repro (logs, código, comandos), versión del tool, contexto del consumer.
- **Engram del tool:** políticas, baselines, instrucciones previas del maintainer, releases cerradas. `mem_search(query: "<tool-name> round <N>" project: "<your-project>")`.
- **Si es round > 1:** las últimas respuestas del maintainer. Sirven para NO repetir huecos cerrados y mantener el SCOPE continuo.

Si te falta alguno, no improvises — entregá igual con lo que tengas y marcalo explícitamente como "necesita tu confirmación".

## Flujo (7 pasos)

### Paso 0 — Decision tree: ¿Producir o preguntar primero?

| Situación | Acción |
|---|---|
| User da contexto rico + pide prompt directo ("dame un buen prompt para X") | **Producir directamente.** No preguntar. |
| User dice "detectá gaps" o "buscá fallas" sin detalle | **Preguntar 1 vez** qué huecos priorizar. Tras respuesta, producir. |
| User da gap específico con detalle | **Producir directamente.** No preguntar. |
| User manifiesta ambigüedad ("no estoy seguro") | **Pedir aclaración** con 1 pregunta cerrada (no abierta). |

**Default: producir.** Solo preguntar si hay ambigüedad genuina.

### Paso 1 — Engram

`mem_search(query: "<tool-name> round <N>")`. Si encontrás rounds previos:

- **NO repetir huecos cerrados** (citá el round anterior que ya los cubrió).
- **Mantener SCOPE continuo** (1-2 frases mencionando qué rounds anteriores siguen abiertos).

### Paso 2 — Elegir el MODE

| Mode | Cuándo usarlo |
|---|---|
| `bug-hunt` | Lista de bugs no relacionados encontrados por el consumer |
| `regression` | Bug recurrente que sigue volviendo tras fix |
| `new-feature` | Feature pedida por el consumer con spec definida |
| `hygiene` | Refactor cosmético, sin cambio de comportamiento |
| `release-prep` | El maintainer prepara un release (tag, changelog, gates) |

Para `bug-hunt` y `release-prep` hay templates concretos en `assets/templates/`. Para los otros tres, adaptá el más cercano.

### Paso 3 — Elegir la VARIANT

| Variant | Cuándo | Longitud aprox. |
|---|---|---|
| **Short** | 1 gap trivial, single root cause, sin tests pesados | 800-1500 chars |
| **Medium** | Default. 1 gap con TDD discipline o 2-3 bugs chicos | 3000-6000 chars |
| **Long** | Release-prep con gates predefinidos, changelog, version bump, ≥5 gaps | 6000-12000 chars |

**Regla práctica:** si tenés UN gap con TDD discipline, usá Medium. Short solo si el gap es trivial.

### Paso 4 — Componer el prompt

Seguí el esqueleto del modo elegido (`assets/templates/<mode>.md`). Cada sección tiene un rol concreto — la descripción está al lado de la sección en cada template.

Reglas duras:

- **NO asumir el repo path del maintainer.** El maintainer conoce su repo. Usá `<repo path>` o `<your repo>` como placeholder.
- **NO asumir la branch.** Sugerí una convention (`fix/<gap-summary>`) y dejá que el maintainer la confirme.
- **Las "evidencias de repro" son críticas.** Pegá los logs/errores literales, no resúmenes.
- **NO uses "I think", "maybe", "probably".** Solo hechos verificados o marcá explícitamente como "preliminar / no verificado".
- **NO incluyas secretos inline** (passwords, tokens). El maintainer usa env vars.

### Paso 5 — Validación (pre-entrega)

Checklist obligatorio antes de entregar. Si cualquier ítem falla, revisalo antes de postear:

- [ ] Síntoma verificado y reproducible (no "creo que falla").
- [ ] Evidencias de repro pegadas literales (no parafraseadas).
- [ ] Versión del tool declarada explícitamente.
- [ ] "Lo que YA funciona" listada (para que el maintainer no rompa nada).
- [ ] Disciplina (TDD, commits, constraints) declarada.
- [ ] Tests RED sugeridos (al menos 1 por gap).
- [ ] Acceptance output claro y medible (qué PR, qué changelog, qué version bump).
- [ ] Quick start con comandos ejecutables.
- [ ] Longitud total ≤ 12k chars (si excede, considera split).
- [ ] Cross-session safe: si round>1, menciona brevemente rounds anteriores.
- [ ] Sin secretos inline.

### Paso 6 — Archivar (decision tree)

**Path:** `docs/prompts/prompt-ia-mantenedora-<tool>-<round>-<YYYY-MM-DD>.md` en el repo del consumer.

| Situación | Acción |
|---|---|
| El consumer es colaborativo o tiene CI | `mkdir -p docs/prompts/` y archivá. Avisale al user. |
| El consumer es personal / un solo dev | Entregá solo en chat; archivá solo si el user lo pide. |
| `docs/prompts/` ya existe | Archivá directamente. |

**Default:** archivá. Salvo que el user pida explícitamente "no archivar".

### Paso 7 — Entregar al user

**Inline, completo, en el chat.** El prompt es el deliverable; no resumir. Después del prompt, un bloque JSON con metadata:

```json
{
  "tool": "<tool-name>",
  "mode": "<mode>",
  "round": "round-<N>",
  "variant": "short|medium|long",
  "prompt_path": "docs/prompts/prompt-ia-mantenedora-<tool>-<round>-<YYYY-MM-DD>.md",
  "prompt_bytes": <size>,
  "verification_queries": ["<exact commands the user can run>"],
  "cross_session_safe": true
}
```

## Lo que el skill NO hace

- NO abre PRs ni issues (eso es del orquestrador tras revisar el prompt).
- NO commitea nada al repo del tool (es del maintainer).
- NO envía el prompt al maintainer directamente.
- NO especula sobre la implementación interna del tool (lo lee en el repo cuando hace falta, o lo consulta al user).
- NO incluye secretos inline — el maintainer usa env vars.

## Anti-patterns (a evitar en el prompt generado)

- ❌ Síntoma sin log literal — el maintainer no puede reproducir.
- ❌ "Lo que YA funciona" ausente — el maintainer rompe cosas.
- ❌ "I think", "maybe", "probably" — solo hechos verificados.
- ❌ Pedir al maintainer cosas que NO podés verificar (calidad de su código, su CI).
- ❌ Redactar el prompt sin haber corrido `mem_search` primero.
- ❌ Entregar el prompt en chat sin archivarlo (salvo decisión explícita).
- ❌ Asumir repo path del maintainer — siempre placeholder.
- ❌ Olvidar el version bump o el changelog en el acceptance output.
- ❌ Tests RED sin valor (un test verde por luck-of-data no es RED valioso).

## Acceptance scenarios

- ✅ Prompt round-3 dysflow: el maintainer lo entiende sin contexto extra, empieza por TDD RED sobre el gap.
- ✅ Prompt para un fork cualquiera (codegraph-vba, herramienta X): el maintainer arranca en `fix/<gap>` con tests RED primero.
- ✅ El prompt incluye queries exactas de verificación que el orquestrador puede repetir después.
- ✅ El archivo archiva en `docs/prompts/` con naming consistente.
- ✅ Decision tree de Paso 0 evita preguntar cuando el contexto ya está claro.

## Ver también

- `assets/templates/bug-hunt.md` — esqueleto concreto con anotaciones sección por sección.
- `assets/templates/release-prep.md` — esqueleto concreto para release-prep.
- `assets/examples/prompt-ia-mantenedora-dysflow-round-3-2026-07-08.md` — ejemplo completo real (vba_inline_execution gap, esta sesión).
