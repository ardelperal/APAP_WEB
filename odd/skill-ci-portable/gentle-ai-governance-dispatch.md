# Cómo `Gentleman-Programming/gentle-ai` hace que su gobierno llegue al agente

> **Propósito.** Responder «no sé cómo gentle ai hace su gobierno» con el detalle que los informes previos no cubrieron: el **mecanismo de despacho** (cómo una regla escrita alcanza al agente en el momento correcto). Complementa `gentle-ai-ci-research-report{,2}.md`; no repite su contenido.
>
> **Corte:** 2026-10-02. HEAD de `gentle-ai` = `5140c5f5`. Clon en `/tmp/gentle-ai-research`, `git fetch` sobre el clon shallow existente. Lectura por `git show origin/main:<path>` (read-only, sin checkout ni escritura en el repo ajeno).
>
> **Convención:** castellano peninsular formal (usted), tercera persona del agente. Cada cita lleva `fichero:línea`. Se distingue **verificado leyendo** de **verificado ejecutando**; no hubo mutaciones.

---

## 1. `AGENTS.md` raíz

Tiene 28 líneas. Íntegro (`AGENTS.md:1-28`, verificado leyendo):

```
# Gentle AI™ — Agent Skills Index

When working on this project, load the relevant skill(s) BEFORE writing any code.

Naming convention: `gentle-ai-*` skills are repo-specific workflow skills. Unprefixed skills are portable writing or work-unit skills and intentionally keep their canonical names.

## How to Use

1. Check the trigger column to find skills that match your current task
2. Load the skill by reading the SKILL.md file at the listed path
3. Follow ALL patterns and rules from the loaded skill
4. Multiple skills can apply simultaneously

## Skills

| Skill | Trigger | Path |
|-------|---------|------|
| `issue-creation` | When creating a GitHub issue, reporting a bug, or requesting a feature. | [`internal/assets/skills/issue-creation/SKILL.md`](internal/assets/skills/issue-creation/SKILL.md) |
| `gentle-ai-branch-pr` | When creating a pull request, opening a PR, or preparing changes for review. | [`skills/branch-pr/SKILL.md`](skills/branch-pr/SKILL.md) |
| `gentle-ai-chained-pr` | When a change is too large for one review, or when creating chained/stacked pull requests. | [`skills/chained-pr/SKILL.md`](skills/chained-pr/SKILL.md) |
| `cognitive-doc-design` | When writing docs that must reduce cognitive load for readers or reviewers. | [`skills/cognitive-doc-design/SKILL.md`](skills/cognitive-doc-design/SKILL.md) |
| `comment-writer` | When drafting human comments, PR feedback, issue replies, or async updates. | [`skills/comment-writer/SKILL.md`](skills/comment-writer/SKILL.md) |
| `work-unit-commits` | When splitting implementation work into deliverable commits or chained PRs. | [`skills/work-unit-commits/SKILL.md`](skills/work-unit-commits/SKILL.md) |
| `rdd-defect-workflow` | When RDD defects involve receipts, authority, recovery, delivery gates, or kill switches. | [`skills/rdd-defect-workflow/SKILL.md`](skills/rdd-defect-workflow/SKILL.md) |
| `rdd-advisory-transport` | When changing reviewer transport, adapters, lens prompts/schemas, or transport capability policy. | [`skills/rdd-advisory-transport/SKILL.md`](skills/rdd-advisory-transport/SKILL.md) |
| `issue-root-resolution` | When auditing backlog roots, proposing cluster fixes, or closing resolved/outdated issues. | [`skills/issue-root-resolution/SKILL.md`](skills/issue-root-resolution/SKILL.md) |
| `systemic-issue-triage` | When triaging issues, bugs, backlogs, root causes, dead ends, or blocked users. | [`skills/systemic-issue-triage/SKILL.md`](skills/systemic-issue-triage/SKILL.md) |
| `gentle-ai-bench` | When touching `bench/`, journeys, driven mode, the journey corpus, or bench axes. | [`skills/gentle-ai-bench/SKILL.md`](skills/gentle-ai-bench/SKILL.md) |
```

**Línea a línea:** L1 título, declara que el fichero **es** un índice. L3 la única orden imperativa: *"load the relevant skill(s) BEFORE writing any code"* — regla de secuencia, no de contenido. L5 convención de nombres; orienta, no impone. L7-12 procedimiento de cuatro pasos: el paso 1 hace del **agente** el despachador (mira la columna Trigger, no una tabla externa); el paso 2 manda leer el `SKILL.md` de la ruta listada; el paso 4 admite varias skills. L16-28 tabla `Skill | Trigger | Path` con **11 filas**.

**¿Reglas duras o punteros?** Sólo punteros. Ni un `MUST`, ni una prohibición sustantiva, ni un gate. La dureza vive en (a) cada `SKILL.md` cargado, con sus propias *Hard Rules*, y (b) `AI_POLICY.md`. `AGENTS.md` despacha; no gobierna.

**Detalle no obvio (verificado leyendo):** el índice es una **selección curada**, no exhaustiva. `skills/` tiene 11 directorios e `internal/assets/skills/` 16 (15 skills + `_shared`); `AGENTS.md` lista 11 filas y **omite** `go-testing`, `judgment-day`, `skill-creator`, `skill-improver`, `hermes-ephemeral-delegation` y `gentle-ai-collab-perfect`. La exhaustividad no se le pide a `AGENTS.md`: se le pide al registro generado (§5).

---

## 2. `AI_POLICY.md`

Tiene 62 líneas. Se cita comprimiendo solo el espaciado; todas las frases normativas están (`AI_POLICY.md:1-62`, verificado leyendo):

```
# AI-Assisted Contribution Policy

AI-assisted contributions are permitted. The human contributor must understand, review, validate, and take full responsibility for everything they submit.

## Human Responsibility
The human contributor remains fully responsible for:
- The security, correctness, and ongoing maintenance of the complete submission.
- Reviewing and validating every change, claim, and test result.
- Ensuring appropriate licensing and confidence in the provenance of submitted material.
- Explaining and defending the design, implementation, and tradeoffs during review.
AI assistance does not transfer authorship, accountability, or legal responsibility away from the contributor.

## Disclosure
Disclose material AI assistance used to produce or substantively review any part of a contribution, including: code, tests, or documentation; designs, prompts, skills, schemas, or workflows; substantive review, investigation, or analysis.
For material assistance, the pull request declaration must state:
1. The tool or model, if known.
2. The material scope of the assistance.
3. The verification the contributor performed.
Raw prompts and private conversation logs are not required by default.
Trivial formatting, spelling corrections, minor autocomplete, search or navigation, and trivial, non-substantive mechanical transformations do not require disclosure.

## Review and Attribution
Maintainers may request an explanation, prompt summary, provenance information, supporting evidence, or additional tests. They may reject work that the contributor cannot explain, verify, or defend.
AI tools must not receive human attribution, including `Co-Authored-By`, `Reviewed-by`, `Tested-by`, `Signed-off-by`, approval, or equivalent credit. An optional `Assisted-by` trailer may be accepted, but the pull request declaration is sufficient.

## Advisory Review and RDD
Assistance used to produce a contribution is distinct from AI-assisted advisory review and receipt-driven development (RDD). ... Automated review or RDD receipts do not replace human authorship, provenance, consent, testing, or legal responsibility.

## Submission Quality
Review is based on observable submission quality, not on whether text or code appears to be AI-generated. Before proposing a fix, contributors should identify the underlying cause and the responsible invariant, then explain and defend why the change is proportionate. Prefer the smallest change that restores that invariant without adding duplicate authority, unnecessary abstractions, or unrelated complexity. This does not require broad or architectural work when a focused fix is sufficient.
Unacceptable behavior includes:
- Submitting output that the contributor has not reviewed.
- Making claims that cannot be verified or reporting results that did not occur.
- Inventing APIs, paths, behavior, evidence, or test results.
- Masking a symptom, shifting the failure elsewhere, or leaving the responsible invariant broken.
- Adding duplicate authority, unnecessary abstractions, or unrelated complexity that creates likely regressions.
- Including broad or unrelated changes outside the approved scope.
- Copying output without confidence in its provenance or license compatibility.
- Being unable to explain the change, its design, or its consequences.
- Delegating the work of understanding, validating, or repairing the submission back to maintainers.

## Enforcement
For now, maintainers enforce this policy through reviewer judgment and documented review decisions only. The project does not use automated AI detection or an automated disclosure gate.
```

**Lectura:**

- **A quién se dirige:** al **contribuyente humano**, no al agente. El agente no es sujeto de la política; lo es el humano que lo opera. Es diseño, no olvido: la responsabilidad no se delega (L14).
- **Reglas duras:** prohibición de atribución humana a la IA (L38); declaración obligatoria de tres campos en el PR (L24-28); lista de comportamiento inaceptable (L48-58), que es el catálogo de AI-slop: afirmar sin verificar, inventar APIs/rutas/evidencia, enmascarar el síntoma.
- **Enforcement (L60-62):** *"maintainers enforce this policy through reviewer judgment and documented review decisions only. The project does not use automated AI detection or an automated disclosure gate."* Honestidad sobre el límite: no hay gate automático, luego no se finge. El gate es humano.
- **¿Dice cómo comportarse el agente paso a paso?** No. Declara *qué no se tolera*, no *cómo proceder*. El procedimiento vive en el protocolo ODD inyectado (§5) y en las skills. Separación limpia: política = contrato humano; skill/protocolo = procedimiento del agente.

---

## 3. `.claude/` y otras configuraciones de agente

**Verificado leyendo** (`git ls-tree -r origin/main .claude`):

```
100644 blob fdd3e78a... .claude/scheduled_tasks.lock
```

Único fichero: un lock de sesión de 91 bytes, `{"sessionId":"19f52d59-...","pid":89965,"acquiredAt":1776005010875}`. No hay `.claude/settings.json`, ni hooks, ni allowlists, ni `.cursor/rules`, ni `GEMINI.md`, ni `opencode.json` comiteados. `.gitignore:34` contiene `.atl/`.

**Conclusión: nada en el repositorio fuerza mecánicamente la carga de una skill.** No hay "always apply" comiteado. El forzado mecánico vive **fuera** del repo, en la proyección que el instalador escribe en la config de cada agente del desarrollador:

- `internal/components/agentguidance/inject.go:27-30` define `ErrUnloadableGuidance`: *"fails closed when guidance would be written to a place the agent does not actually load. Silently installing unread guidance is the exact failure this component exists to prevent."*
- `internal/components/agenthooks/skill_registry.go:78-91` instala hooks de arranque: Codex `SessionStart`, Claude Code `UserPromptSubmit`, con `gentle-ai skill-registry refresh --quiet --no-gitignore --cwd …`.
- `internal/assets/opencode/plugins/skill-registry.ts:136` provee el equivalente para OpenCode al cargar el plugin.
- `internal/components/agentguidance/routing.go:24-144` renderiza el bloque `## Implementation Routing` inyectado en **todos** los adaptadores, con secciones `(MANDATORY)`.

La mecánica no es un hook comiteado: es una **proyección idempotente y fail-closed** del binario. En el repo solo queda el índice curado (`AGENTS.md`) que el harness carga por convención.

---

## 4. Convención de frontmatter

Cuatro frontmatters verbatim (verificado leyendo):

`skills/branch-pr/SKILL.md:1-8`:
```yaml
name: gentle-ai-branch-pr
description: "Create Gentle AI pull requests with issue-first checks. Trigger: creating, opening, or preparing PRs for review."
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "2.0"
```
`skills/chained-pr/SKILL.md:1-8`:
```yaml
name: gentle-ai-chained-pr
description: "Trigger: PRs over 400 lines, stacked PRs, review slices. Split oversized changes into chained PRs that protect review focus."
license: Apache-2.0
metadata: {author: gentleman-programming, version: "1.0"}
```
`skills/work-unit-commits/SKILL.md:1-8`:
```yaml
name: work-unit-commits
description: "Plan commits as reviewable work units. Trigger: implementation, commit splitting, chained PRs, or keeping tests and docs with code."
license: Apache-2.0
metadata: {author: gentleman-programming, version: "1.0"}
```
`skills/systemic-issue-triage/SKILL.md:1-8`:
```yaml
name: systemic-issue-triage
description: "Trigger: new issue, bug report, triage, backlog, issue flood, community report, root cause, dead-end, blocked user. Attack issues by root class, never one-by-one; fixes must shrink the system, not grow it."
license: Apache-2.0
metadata: {author: "Alan-TheGentleman", version: "1.0"}
```
(Las tres primeras líneas de cada fichero son `---`; se omiten por espacio.)

**Campos existentes, exactamente:** `name`, `description` (una sola línea, entrecomillada), `license`, `metadata.author`, `metadata.version`. **No existen** `auto_invoke`, `metadata.scope`, `metadata.tiers`, `last_verified` ni `based_on`. Verificado por grep: `git grep -Iln "auto_invoke" origin/main` no devuelve nada.

La convención de `description` es explícita (`docs/skill-style-guide.md:24-28`): una sola línea física, entrecomillada, `Trigger:` primero, ≤160 chars (máximo 250), sin sección `Keywords`. El prefijo `Trigger:` es la materia prima del despacho: el generador del registro solo lee `name` y `description` (`internal/skillregistry/registry.go:244-257`, `:330-370`) y los vuelca en la columna `Trigger / description`. Un lint mecánico exige el `Trigger:` y acota la longitud (`internal/assets/skills_frontmatter_test.go`, Informe 2 §D16).

**¿Despacho por descripciones listadas por el harness, o tabla explícita?** Las dos cosas, en dos capas:

1. **Agentes que trabajan en `gentle-ai`:** la tabla explícita es `AGENTS.md` (§1), que el harness carga por convención. No hay ruteo automático por descripción.
2. **Agentes de consumidores:** la tabla explícita es `.atl/skill-registry.md`, **generada** desde los frontmatters (§5), más un protocolo obligatorio inyectado que ordena leerla y pasar rutas.

No es "emergente" en el sentido de que el harness adivine: la descripción es el **dato de disparo**, pero hay **índice** y **protocolo** que obligan a consultarlo.

---

## 5. La tabla de disparo explícita: `.atl/skill-registry.md`

`internal/skillregistry/registry.go:18-21`:

```go
RegistryRelPath = ".atl/skill-registry.md"
CacheRelPath    = ".atl/.skill-registry.cache.json"
RegistrySchema  = 5
```

`RenderRegistry` (`registry.go:259-285`) produce `| Skill | Trigger / description | Scope | Path |` y un bloque **Loading protocol**:

```
1. Match task context and target files against the `Trigger / description` column.
2. Pass only the matching `Path` values to the subagent under `## Skills to load before work`.
3. Instruct the subagent to read those exact `SKILL.md` files before reading, writing, reviewing, testing, or creating artifacts.
4. If no matching skill exists, proceed without project skill injection and report `skill_resolution: none`.
```

`docs/skill-registry.md:16-33` documenta el flujo: *User task → Orchestrator reads .atl/skill-registry.md → Matches task + file context against full skill descriptions → Passes exact SKILL.md paths to subagent → Subagent reads full skills before work.* Y `:57` fija el contrato: *"The registry is an **index**, not a generated summary."* La razón (`:115-122`): los resúmenes compactos *"could distort skills"*.

**El protocolo es obligatorio en cada runtime.** `internal/assets/skills/_shared/odd-orchestrator-sections.md:183-201`:

```
1. Read `.atl/skill-registry.md` if present.
2. Match task context and target files against the `Trigger / description` column.
3. Pass only matching `Path` values to subagents under `## Skills to load before work`.
4. Tell subagents to read those exact `SKILL.md` files before reading, writing, reviewing, testing, or creating artifacts.
5. If the registry is absent, continue but mention that project-specific skill paths were unavailable.
```

y `:201`: *"If any subagent reports a fallback instead of `paths-injected`, treat it as an orchestration gap and correct future delegations by passing exact indexed paths directly."*

**El router son tres piezas coordinadas:**

| Pieza | Naturaleza | Fichero |
|---|---|---|
| Índice generado | Tabla `Skill / Trigger / Scope / Path` | `.atl/skill-registry.md` |
| Protocolo inyectado | Orden de consultar y pasar rutas | `_shared/odd-orchestrator-sections.md:183-201` |
| Intent hints | Tabla **no vinculante** de descubrimiento | `_shared/odd-orchestrator-sections.md:152-173` |

`docs/trigger-rules.md` **no** es el router de skills: rutea **rutas de implementación** (direct inline / delegated direct / SDD). Se cita para descartarlo.

---

## 6. `CONTRIBUTING.md` — división de deberes

`CONTRIBUTING.md:24-35`:

```
## Issue-First Workflow
**No PR without an issue. No exceptions.**
1. Open an issue using the appropriate template ...
2. Wait for approval — work may begin only when the issue has `status:approved` under the canonical issue-creation workflow contract. Without a current direct instruction and target-host capability granting the exact action, comment and wait.
3. Comment on the issue to let others know you're working on it
4. Open a PR referencing the approved issue
PRs that are not linked to an approved issue will be **automatically rejected** by CI.
```

`CONTRIBUTING.md:47-60` (checklist del contribuyente asistido por IA):

```
## AI-Assisted Contributions
**AI assistance is allowed, but you must understand and own the complete submission.** Before opening a PR:
- [ ] Confirm the change matches the approved issue scope.
- [ ] Inspect every changed line.
- [ ] Remove invented, unverifiable, or unrelated output.
- [ ] Identify the responsible cause or invariant; confirm the fix resolves it rather than masking or shifting the symptom.
- [ ] Remove duplicate authority, unnecessary abstractions, and unrelated complexity; keep the fix proportionate.
- [ ] Run applicable tests and report the actual outcomes.
- [ ] Be ready to explain the design and tradeoffs.
- [ ] Disclose material AI assistance in the PR.
For disclosure boundaries ... see the canonical [AI-Assisted Contribution Policy](AI_POLICY.md).
```

`CONTRIBUTING.md:346-356` y `:367-380` (definition of done y checks):

```
### Before Opening a PR
- [ ] There is a linked approved issue ...
- [ ] The PR is at or below 400 changed lines, or a maintainer approved `size:exception`
- [ ] Commits are organized by deliverable work unit
- [ ] All unit tests pass (`go test ./...`)
- [ ] E2E tests pass (`cd e2e && ./docker-test.sh`)
- [ ] Benchmark validation completed, or this change is not applicable ...
- [ ] Commits follow Conventional Commits format
- [ ] Code is self-reviewed
- [ ] I understand and take responsibility for the complete submission, and have disclosed any material AI assistance in the PR
...
**All checks must pass** before a PR can be merged.
```

**División de deberes:**

- **Contribuyente humano:** entiende, inspecciona, verifica, declara y defiende (`AI_POLICY.md:5-14`).
- **Maintainer:** aprueba la issue (`status:approved`, acto humano, Informe 2 §D24), pide explicaciones y **rechaza** lo inexplicable (`AI_POLICY.md:36`). Es el gate.
- **Agente:** no es sujeto de la política; es instrumento cuyo procedimiento vive en skills y protocolo ODD.

La frase "el revisor es el gate" está literalmente en `AI_POLICY.md:60-62`: *"maintainers enforce this policy through reviewer judgment and documented review decisions only."*

---

## 7. La convención `odd/tasks/*.md`

**Verificado leyendo:** `odd/tasks/` contiene 31 ficheros. `odd/tasks/ga-4882-telemetry-lock.md` íntegro (50 líneas; las líneas de cuerpo largo se abrevian con `...`):

```
# ga-4882: telemetry lock loses same-process updates on Windows

Claimed 2026-09-23 (issuecomment-5796980665). Branch fix/4882-telemetry-increment-syncs
(worktree ~/gentleman/gentle-ai-4882) from origin/main a773ccfb.

## Root-cause position (verified)
- Update (lock -> EnsureState -> mutate -> Save) is the only serialization point; Save is
  atomic (temp+rename) on telemetry.json; nothing deletes telemetry.json.lock.
- Defect: same-process LockFileEx intermittently fails to mutually exclude on Windows
  (17/20 observed on the lane; Linux flock never reproduces).
- Range landscape: ... this repo's reviewtransaction store lock uses exactly 1 byte at offset 0.

## Tasks
1. [done] RED: TestLockStateExcludesSameProcessCallers (contract) + ...
2. [done] Implement: 1-byte range at offset 0 (lock+unlock), path-keyed same-process mutex hybrid ...
3. [done] GREEN + full internal/telemetry suite + gofmt/vet (delegated): ...
4. [done] Commit 7ce9baa7 + push; PR #4914 opened (Closes #4882, type:bug requested from maintainer).
5. [done] Native review lineage review-d61a45dd63798350 (medium, 1 lens): approved + ...
## Evidence
- Task 1 (RED): stage 0 — build failure ...
- Task 2 (GREEN): state_lock.go (hybrid: path-keyed mutex map ...), ...
- 2026-09-23: worker RED `Counters.Syncs = 1, want 20` (broken-lock sabotage, Linux); ...
- CI 2026-09-23: Unit Tests red once on TestDocumentedInvocationsRunAsDocumented/executed/sync_# ...
```

**Secciones fijas:** `Claimed` (fecha + id de comentario + rama + worktree + SHA base), `## Root-cause position (verified)`, `## Tasks` (numeradas, marcador `[done]` **en la misma línea** que su evidencia: PR, linaje de review, severidad) y `## Evidence` (cronología append-only con resultado observable por comando). No hay validador automático del formato.

**No es opcional por buena voluntad: el protocolo lo crea.** `internal/components/agentguidance/routing.go:42` (ODD, paso 5):

```
5. **Track before the first write.** For substantial authorized implementation, create `odd/tasks/<feature-name>.md` and its Engram mirror `odd/<feature-name>/tasks` automatically, before the first source write, without asking permission for tasks or storage.
```

`routing.go:43` exige que cada tarea cierre con al menos un work-unit commit y que su identidad quede registrada como evidencia en el documento.

---

## 8. Lo que cierra el bucle

1. **Memoria persistente (Engram) obligatoria.** `internal/assets/engram/protocol.md:2-3`: *"This protocol is MANDATORY and ALWAYS ACTIVE — not something you activate on demand."* Define `mem_current_project` al inicio, guardado proactivo (`mem_save` tras decisión, fix o descubrimiento), la garantía de entrega (guardar no es responder) y el cierre de sesión. `routing.go:49` manda reanudar con `mem_context` → `mem_search` → `mem_get_observation` → el fichero de tarea.
2. **Cierre verificado por tarea.** `routing.go:45-47` (paso 7): reportar el resultado verificado, cada check fallido/omitido/pendiente y el siguiente paso.
3. **Checklists por tipo de cambio.** `docs/codebase/maintainer-playbook.md:40-92` y tabla de preguntas de review (`:92-102`).
4. **Plantillas de issue que enseñan la regla al abrirla.** `bug_report.yml:3` aplica `status:needs-review` y dice que solo el maintainer pone `status:approved` (Informe 2 §D24).

Bucle completo: **índice → skill cargada → protocolo ODD crea la tarea → memoria persistente la sobrevive → evidencia en el documento → checks humanos/CI cierran.**

---

## 9. Comparación con nuestro dispositivo

**Qué tenemos hoy**

- `/home/ubuntu/repos/apap-app/AGENTS.md`, 234 líneas. Tabla índice con **20 filas**; `## How to use` en L28-34; bloque propagado `<!-- personal-skills:slice:APAP_WEB @ v985a74e -->` en **L138-234**, con la resolución de skills en L227-234.
- `.atl/skill-registry.md` en `apap-app`, regenerado el 2026-10-02, **45 KB y 104 filas**. Contiene `ci-pattern` (L48) y `oracle-vps-github-runners` (L94), ambas scope `project` con ruta absoluta al `SKILL.md`.
- `/home/ubuntu/personal-skills/AGENTS.md`, 50 líneas: lectura obligatoria (L5-15), estructura (L17-31), workflow (L33-36), stack (L38-41), verificaciones (L43-51). L51 ordena regenerar el registro tras cambiar skills.
- `/home/ubuntu/personal-skills/README.md` menciona el registro en L66, L139, L246-247, L349, L369.

**Qué le falta estructuralmente**

1. **Nuestro AGENTS.md nunca menciona `.atl/skill-registry.md` ni manda leerlo.** Verificado: `grep -n "\.atl\|skill-registry" AGENTS.md` solo devuelve coincidencias incidentales (L152 `fleet/registry.json`, L233 `registry de gentle-pi`), ninguna es la orden de consultar el índice. El registro **existe**, pero el despachador que el agente lee primero no lo señala. Alan sí lo señala, como sección `(MANDATORY)` inyectada.
2. **Nuestro índice es incompleto y no lo declara.** Lista 20 filas frente a 104 del registro. `oracle-vps-github-runners` —cuya regla dura es *"Neither `status=online` nor the API's runner count is proof. Deregister and restart; cross-check every name to a container"*— **no aparece en AGENTS.md**. Verificado: `grep -n "oracle\|self-hosted\|runner" AGENTS.md` solo devuelve L172 (CI rojo por infra), no la skill. La regla estaba en papel (skill + registro) y era **invisible** para el agente que leyó AGENTS.md.
3. **No hay protocolo de despacho hacia subagentes.** Copiamos el artefacto (`.atl/`) pero no el contrato que lo usa: "el padre lee el registro, casa `Trigger / description`, pasa rutas exactas bajo `## Skills to load before work`, y si un subagente reporta fallback se trata como gap". Esa pieza convierte un índice en despacho; sin ella el registro es decorativo.
4. **Nuestra resolución "por nombre, nunca por ruta absoluta" (AGENTS.md:233) contradice el modelo de rutas exactas.** El propio índice usa rutas y el registro las provee; ordenar referenciar por nombre invita a que el subagente **redescubra**, el caso `fallback-registry` que Alan marca como degradado.
5. **Nuestro frontmatter tiene campos inertes para el despacho.** Declaramos `auto_invoke`, `metadata.scope`, `metadata.tiers`, `last_verified`. El registro solo lee `name` y `description`; luego `auto_invoke` **no dispara nada**. Confundir un campo declarativo con un mecanismo de carga es el espejismo que produjo el fallo.

**Dónde se rompe el despacho para la regla de la sesión**

```
Regla escrita      → skills/oracle-vps-github-runners/SKILL.md (HR-6/HR-11)   [existe]
Indexada           → .atl/skill-registry.md:94 (scope project, trigger)        [existe]
Despachador        → AGENTS.md: NO la lista; NO manda leer el registro         [ROTO]
Agente la carga    → nunca ocurre                                              [ROTO]
Regla se viola     → "verificar el tooling en el runner antes de migrar"       [fallo]
```

El punto de rotura no es la falta de regla ni la falta de índice: es que **ningún artefacto que el agente lee al arrancar dice "consulta el registro y casa el disparo"**. En Alan esa orden es una sección obligatoria del orquestador; en nosotros, no existe.

---

## 10. El mecanismo transferible

Alan hace llegar la regla al agente con cuatro capas acopladas: (1) un **índice curado** corto (`AGENTS.md`, 28 líneas) que el harness carga por convención y que ordena "cargar la skill antes de escribir"; (2) un **registro generado** (`.atl/skill-registry.md`), tabla explícita `Skill / Trigger / Scope / Path`, refrescado por **hooks de arranque** en cada runtime; (3) un **protocolo obligatorio inyectado** que ordena leer el registro, casar el disparo y **pasar rutas exactas** al subagente; (4) **reglas duras separadas** de los punteros (`AI_POLICY.md` para el contrato humano, hard rules dentro de cada `SKILL.md`) más un documento de tarea que sobrevive a la sesión.

**Adaptable:** el índice corto con columna de disparo; el registro como tabla explícita; el protocolo "lee el registro → casa → pasa rutas exactas"; el lint de frontmatter que exige `Trigger:`; la separación política/procedimiento; y el documento por tarea con `Claimed / Root-cause / Tasks / Evidence`.

**Harness-específico (no transfiere tal cual):** la inyección idempotente en la config de cada runtime y los hooks nativos (`SessionStart` de Codex, `UserPromptSubmit` de Claude Code, plugin de OpenCode) que refrescan el registro al arrancar. Nosotros dependemos de `gentle-pi`/`gentle-ai` para esa capa; si su hook no está activo, nuestro registro puede quedar obsoleto y nada lo detecta. Lo que sí transfiere de esa capa es su **invariante**, no su implementación: *un gobierno que no se puede demostrar cargado no se debe instalar*.

---

## Qué adoptar en nuestro dispatcher

1. **Convertir el registro en la primera parada obligatoria.** Añadir en `/home/ubuntu/repos/apap-app/AGENTS.md`, tras `## How to use` (L28-34), una sección `## Skill Registry Protocol (MANDATORY)` con los cinco pasos de `_shared/odd-orchestrator-sections.md:183-201`. **Habría evitado** el fallo de esta sesión: `oracle-vps-github-runners` habría entrado por el registro (fila 94) aunque no esté en la tabla del AGENTS.md.
2. **Cerrar la deriva índice/registro.** Añadir en la misma sección: "el AGENTS.md es la puerta del contribuyente; la verdad operativa es `.atl/skill-registry.md`; si una skill no aparece en este índice, búsquela en el registro". **Habría evitado** que la ausencia de `oracle-vps-github-runners` se interpretara como "no aplica".
3. **Corregir la regla de resolución por nombre.** Sustituir `AGENTS.md:233` ("Referencias por nombre, nunca por ruta absoluta") por la forma de Alan: nombre en prosa, **ruta exacta en la delegación** (`_shared/odd-orchestrator-sections.md:188`). **Habría evitado** el `fallback-registry` degradado.
4. **Añadir el registro al bloque propagado.** En `slices/partials/web.md` (materializado en `AGENTS.md:138-234`), cambiar la resolución (L227-234) para que su paso 0 sea "lea `.atl/skill-registry.md` y case el disparo". **Habría evitado** que el bloque propagado, que sí habla de skills, dejara fuera el único índice exhaustivo.
5. **Declarar el registro como artefacto verificado.** Añadir en `/home/ubuntu/personal-skills/AGENTS.md` (junto a L43-51): "si `.atl/skill-registry.md` tiene antigüedad > 1 cambio de `skills/`, es stale; refrésquelo antes de delegar". **Habría evitado** operar con un índice que nadie garantizó fresco (el hook de gentle-pi puede no estar activo).
6. **Alinear el frontmatter con lo que el registro lee.** Mantener `Trigger:` como primer texto de `description` (ya se cumple en `ci-pattern` y `oracle-vps-github-runners`) y documentar en `/home/ubuntu/personal-skills/AGENTS.md` que `auto_invoke`/`scope`/`tiers` son metadatos **inertes**; el disparo efectivo es la descripción. **Habría evitado** confundir "declarado en `auto_invoke`" con "se cargará".
7. **Añadir el lint de frontmatter a la verificación obligatoria.** Ya existe `testing/suites/frontmatter-validator/validate-frontmatter.sh` (personal-skills/AGENTS.md:45); extenderlo para exigir que `description` empiece por `Trigger:` y sea una sola línea física (`docs/skill-style-guide.md:24-25`). **Habría evitado** que una skill con `Trigger:` degradado quedara fuera del alcance del registro sin aviso.
8. **Adoptar el documento de tarea con evidencia en línea.** Para cada issue con posición de causa raíz, crear `odd/tasks/<n>-<slug>.md` con `Claimed`, `Root-cause position (verified)`, `Tasks` con `[done]` inline y `Evidence` append-only. **Habría evitado** que el contexto de esta sesión (qué se verificó en el runner y cuándo) dependiera de la memoria del agente en vez del recibo.
9. **Separar política de procedimiento.** Si vamos a tener reglas duras de orquestación, escribirlas en un `AI_POLICY` propio (contrato humano, enforcement declarado) y dejar los punteros en AGENTS.md/skills. **Habría evitado** que una regla dura de orquestación viviera enterrada en un bloque de índice que nadie está obligado a leer entero.
