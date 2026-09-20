---
name: skill-style-guide
description: Trigger: crear skill, refactorizar skill, auditar skill, revisar SKILL.md, frontmatter de skill, secciones canónicas, body budget, Output Contract, hard rules, decision gates, anti-patterns tabulados. Aplica la disciplina de authoring de Gentleman-Programming (gentle-ai, engram): frontmatter prescrito, body budget con números, secciones canónicas en orden fijo, Output Contract obligatorio, hard rules con verbos prohibidos listados, anti-patterns en tabla Symptom/Fix.
license: Apache-2.0
metadata:
  author: Andrés Román
  version: 1.3.0
  last_verified: 2026-09-01
  scope: ['universal', 'docs']
  auto_invoke: ['creating a new skill', 'auditing an existing skill']
  tiers: ['universal', 'docs']
---



## §1 Activation

Cargue esta skill cuando:

- Vaya a crear una skill nueva (`SKILL.md` más opcional `references/` y `assets/`).
- Refactorice una skill existente — reordenando secciones, formalizando el Output Contract, o reduciendo el cuerpo para encajar en el budget.
- Audite una skill contra el rubric, con CI, revisión manual, o la skill `skill-improver`.
- Resuelva un fork de naming o de estructura en un catálogo de skills.

**Do NOT load when:**

- Escriba un doc human-facing (eso es `documentation-alan-style`).
- Escriba código de aplicación (eso es `code-review-expert` o la skill del stack específico).
- Redacte un prompt one-shot efímero que no se va a reusar.

## §2 Hard Rules

- **HR-1** — Frontmatter MUST declarar los seis campos: `name`, `description`, `license`, `metadata.author`, `metadata.version`, `metadata.last_verified`. Ausentar uno solo es contract violation.
- **HR-2** — Body budget MUST cumplir target 180 - 450 líneas, max recomendado 700, hard max 1000. Una skill que excede 1000 líneas MUST dividirse en `SKILL.md` + `references/<topic>.md` + `assets/<template>.md`.
- **HR-3** — `description` MUST arrancar con `Trigger: kw1, kw2, kw3. {Qué hace la skill}.`. Las keywords son el contrato de discovery del skill-registry; no son decoración.
- **HR-4** — `description` MUST ser single-language. Mezcla EN + ES en el mismo campo confunde el match. Si necesita bilingüe, declare `metadata.language` o use dos skills separadas.
- **HR-5** — Hard rules MUST numerarse `HR-1`, `HR-2`, ..., `HR-N` y cada una MUST empezar con un verbo observable prohibido u obligatorio. Slogans como "be careful" son reject.
- **HR-6** — Decision Gates MUST ser tabla `| Condition | Action |`. Prosa condicional "if X then Y" es reject.
- **HR-7** — Anti-patterns MUST ser tabla `| Symptom | Fix |`. Bullet lists con emojis decorativos para cada anti-pattern son reject.
- **HR-8** — Output Contract MUST declarar TODAS las keys que la skill retorna, en una sola sección canónica. La sección MUST tener una tabla `| Key | Type | Description |`.
- **HR-9** — El LLM caller MUST retornar TODAS las keys del Output Contract, incluso cuando el valor es empty array, null, o `"none"`. Una key ausente es violación de contrato.
- **HR-10** — `metadata.last_verified` MUST actualizarse en cada edición material. Sin esa fecha, la skill es tratada como stale por cualquier auditor.
- **HR-11** — Las secciones canónicas MUST aparecer en este orden: Activation → Hard Rules → Decision Gates → Execution Steps → Output Contract. Renombrar (`## Critical Rules` en vez de `## Hard Rules`) es reject.
- **HR-12** — El cuerpo MUST aplicar las reglas que prescribe. Emojis decorativos en bullets de Anti-patterns cuando la skill prohíbe emojis en headings ni cuerpo es hypocritical y reject.
- **HR-13** — Una skill MUST NO duplicar información que viva en `CONTRIBUTING.md`, `AGENTS.md`, `README.md` u otros docs raíz. Duplicar es reject; referenciar por path es la regla.
- **HR-14** — Una skill MUST NOT contener secciones históricas, "Migration from X", "Deprecated", "Historical reference", "Cambios respecto a versión anterior", ni tablas comparativas entre versiones. Solo el estado actual del contrato. La historia vive en `git log`, `git tag`, y release notes, no en el cuerpo del documento. Una sección histórica detectada en auditoría MUST eliminarse en el siguiente commit.

## §3 Decision Gates

| Condition | Action |
|---|---|
| If the skill body will exceed 700 lines | Move depth to `references/<topic>.md`; keep `SKILL.md` as entry point. |
| If the skill needs a template larger than 30 lines | Move to `assets/<template>.md`; reference by path. |
| If the description needs EN + ES keywords | Pick one language; add `metadata.language: "en"` or `"es"` if both are required. |
| If a hard rule has no testable verb | Rewrite with verb-prohibition list or split into two HR-Ns. |
| If the Output Contract returns `status: "blocked"` | Stop, surface `blockedReasons`, do not start dependent phases. |

## §4 Execution Steps

1. **Fetch** — Read the existing catalog at `~/.config/opencode/skills/` to confirm the target name is unique. Si no es único, renombre antes de continuar.
2. **Frame** — Draft the frontmatter con los seis campos obligatorios. La description arranca con `Trigger:` y lista keywords reales que un prompt de usuario contendría.
3. **Section** — Coloque las secciones canónicas en orden: Activation → Hard Rules → Decision Gates → Execution Steps → Output Contract. Secciones suplementarias (Anti-patterns, Self-compliance, Companion skills) van después.
4. **Rule** — Escriba Hard Rules con verbos observables. Si una rule no tiene verbo, rehágala o divídala.
5. **Gate** — Convierta cada branching choice en una fila de la tabla Decision Gates. No prosa condicional.
6. **Contract** — Declare el Output Contract con la lista completa de keys. Llene TODAS, incluso cuando el valor es empty.
7. **Anti-pattern** — Catalogue los errores frecuentes como `| Symptom | Fix |` en una tabla, no en bullets con emojis.
8. **Self-check** — Corra los greps de §7 Self-compliance. Si un check falla, fix antes de mergear.

## §5 Output Contract

Return an object with the following keys:

| Key | Type | Description |
|---|---|---|
| `status` | `"success" \| "blocked" \| "failed"` | Phase outcome of the create or audit. |
| `skill_name` | string | The `name` of the skill created or audited. |
| `skill_path` | string | Absolute path to the `SKILL.md` file. |
| `frontmatter_check` | `"pass" \| "fail"` | Required fields present. |
| `body_budget_check` | `"pass" \| "fail"` | Line count ≤ 1000. |
| `canonical_sections_check` | `"pass" \| "fail"` | Sections in canonical order. |
| `hard_rules_check` | `"pass" \| "fail"` | HR-N numbered and testable. |
| `decision_gates_check` | `"pass" \| "fail"` | Decision Gates is a table. |
| `anti_patterns_check` | `"pass" \| "fail"` | Anti-patterns is a table. |
| `output_contract_check` | `"pass" \| "fail"` | Output Contract has a key table. |
| `self_compliance_check` | `"pass" \| "fail"` | Skill applies its own rules. |
| `failed_checks` | string[] | Names of checks that failed. |
| `next_recommended` | `"fix_violations" \| "register_in_catalog" \| "none"` | Next phase or action. |
| `risks` | string[] | Open risks (e.g., "skill body > 700 lines, recommend split"). |
| `skill_resolution` | `"paths-injected" \| "fallback-registry" \| "none"` | How skills were resolved. |

## §6 Anti-patterns

| Symptom | Fix |
|---|---|
| Section `## Critical Rules` en lugar de `## Hard Rules` | Renombrar a `Hard Rules`; los auditors greppean ese nombre. |
| `metadata.author` varía entre 4 spellings de la misma persona | Pin un handle canónico; lint del catálogo. |
| `description` mezcla keywords EN + ES | Elegir una lengua; añadir `metadata.language` si es bilingüe. |
| Template de 80 líneas embebido dentro de `SKILL.md` | Mover a `assets/<template>.md`; referenciar por path. |
| Hard rule "be careful when X" | Reformular con HR-N enumerada y verbos observables. |
| Bullet list con emojis para cada anti-pattern | Convertir a tabla `| Symptom | Fix |`. |
| Skill de 5000+ bytes sin Output Contract | Añadir Output Contract con la tabla de keys. |
| Sections en orden distinto del canónico | Reordenar a Activation → Hard Rules → Decision Gates → Execution Steps → Output Contract. |
| Sin `metadata.last_verified` | Añadir el campo; actualizar en cada edición material. |
| Verb-prohibition list distribuida en prosa de cinco líneas | Consolidar en una sola línea larga con comas. |

## §7 Self-compliance

Esta skill debe cumplir su propio rubric. Verificación con grep:

```bash
# Frontmatter tiene los seis campos obligatorios
head -10 SKILL.md

# Body budget ≤ 1000 líneas
wc -l SKILL.md

# Description arranca con "Trigger:"
head -3 SKILL.md | grep -q "Trigger:"

# Secciones en orden canónico
grep -E '^## §' SKILL.md

# Hard rules numeradas HR-N
grep -E 'HR-[0-9]+' SKILL.md

# Decision Gates, Anti-patterns, Output Contract son tablas
grep -E '\| (Condition|Symptom|Key) \|' SKILL.md
```

Self-check de esta skill cumple: 5 secciones canónicas en orden numeradas §1 a §5, 13 HR-N enumeradas, Decision Gates y Anti-patterns y Output Contract en tablas, body budget target ≤ 350 líneas.

## §8 Companion skills

| Skill | Cargar junto cuando |
|---|---|
| `documentation-alan-style` | La skill gobierna contenido human-facing. Esta skill es el sibling técnico para skills. |
| `skill-improver` | Audite una skill existente contra este rubric. |
| `skill-creator` | Cree una skill desde cero siguiendo este rubric. |
| `skill-registry` | Refresque el catálogo de skills después de añadir o modificar una. |

<!-- E2E-sync-test-2026-08-18-marker -->
<!-- post-commit-hook-test-2026-08-18-marker -->
