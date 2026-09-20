---
name: apap-web-agents
description: Agent instructions and code-quality rules for APAP_WEB (FastAPI + HTMX + LocalBackend backend)
license: Proprietary
metadata:
  author: APAP_WEB maintainers
  version: 1.0.0
globs: *
alwaysApply: true
---

# APAP_WEB — Agent Skills Index

APAP_WEB es una aplicación web FastAPI + HTMX + Jinja2 (Python `>=3.11`) con arquitectura por capas estricta en transición a hexagonal con slices verticales (ver [docs/codebase/architecture.md](docs/codebase/architecture.md)). Cuando trabaje en este proyecto, cargue las skills relevantes antes de escribir código o docs.

## How to use

1. Revise la columna "trigger" para identificar las skills que matchean la tarea actual.
2. Cargue la skill leyendo el `SKILL.md` indicado en la columna "path".
3. Siga todos los patrones y reglas de la skill cargada.
4. Varias skills pueden aplicar simultáneamente; cargue cada una por su SKILL.md.
5. En duda, prefiera la skill más específica (por ejemplo, `apap-merge-workflow` sobre `branch-pr` para política de merge).

## Mandatory skills

| Skill | Cuándo cargarla |
|---|---|
| **`documentation-alan-style`** | Cualquier documento escrito o revisado — `README`, este `AGENTS.md`, `DOCS`, `CODEBASE-GUIDE`, `CONTRIBUTING`, `CHANGELOG`, epics, walkthroughs. |
| **`repository-delivery-governance`** | Cualquier auditoría o cambio de CI/CD, política de issues o PRs, labels, branch protection, rulesets, permisos de merge, artefactos, despliegue o rollback. La política específica del repo prevalece sobre su baseline portable. |
| **`branch-pr`** | Cualquier commit, apertura de PR o merge a `main`. Merge con `--no-ff`, nunca con `--delete-branch` (ver [docs/codebase/merge-workflow.md](docs/codebase/merge-workflow.md)). |
| **`code-review-expert`** | Cualquier slice dirigido por subagent que aterrice en `main` (lente de revisión obligatoria, §17.2). |
| **`judgment-day`** | Cualquier diff high-stakes (auth, secrets, CSRF, PII, migraciones, SQL crudo). |
| **`gentle-ai-ai-slop-discipline`** | Cualquier implementación asistida por IA (código, docs, tests, planes). Antes de commitear, ejecutar el self-check de las 4 preguntas y detectar las 3 firmas de AI slop (prosa paralela, claims sin contrato testeable, tests que verifican ejemplos inventados). Aplica a todo el código que produce este agente sin excepción. |

## Project-context skills (este repo)

| Skill | Trigger | Path |
|---|---|---|
| `apap-architecture` | Routes, services, queries layer, límites de capa, validación, migración a slices hexagonales (§33). | [`skills/apap-architecture/SKILL.md`](skills/apap-architecture/SKILL.md) |
| `apap-security` | Auth (§6, §29), CSRF (§10), secrets (§8), log_safe (§9), PII. | [`skills/apap-security/SKILL.md`](skills/apap-security/SKILL.md) |
| `apap-testing` | CRITICAL_HELPERS (§11), cobertura (§19), configuración pytest. | [`skills/apap-testing/SKILL.md`](skills/apap-testing/SKILL.md) |
| `apap-testing-strategy` | Decidir tipo de test (unit / integration / e2e / migration), auditar gaps de cobertura real vs mock, refactorizar mocks a integration con Postgres real cuando aplique. Basada en [docs/quality/test-audit.md](../docs/quality/test-audit.md). Complementaria a `apap-testing` (gates y cobertura). | [`skills/apap-testing-strategy/SKILL.md`](skills/apap-testing-strategy/SKILL.md) |
| `apap-migration` | `app/core/migration/`, sync bidireccional, `python -m migration reconcile`. | [`skills/apap-migration/SKILL.md`](skills/apap-migration/SKILL.md) |
| `apap-merge-workflow` | Política pre-MVP single-branch (§15), ciclo de vida de rama, autorización standing de merge. | [`skills/apap-merge-workflow/SKILL.md`](skills/apap-merge-workflow/SKILL.md) |
| `apap-orchestrator-discipline` | Coordinación de subagents (§17), patrones de delegación, lentes de revisión. | [`skills/apap-orchestrator-discipline/SKILL.md`](skills/apap-orchestrator-discipline/SKILL.md) |

> Las skills del proyecto viven en [`skills/`](skills/README.md) versionadas con el código (fuente canónica). Las skills con prefijo `apap-` en `~/.config/opencode/skills/` de una máquina local son fallback legacy. Si necesitás editar una skill versionada, editá la copia en `skills/`. Si una skill listada no existe en `skills/`, créala primero siguiendo `skill-creator` o `skill-improver`.

## Cross-cutting skills (de otros repos)

| Skill | Trigger | Origen |
|---|---|---|
| `telefonica-brand-design` | Cualquier UI Mistica (design tokens, brand, layout). | Gentleman-Programming/mistica |
| `frontend-design` | Diseño UI distintivo (no AI defaults). | Gentleman-Programming |
| `dysflow-usage` / `dysflow-arnes` | Cualquier uso de dysflow MCP. | Gentleman-Programming |
| `codegraph-usage` | Working with codegraph MCP/CLI (§14). | Gentleman-Programming |
| `code-review-expert` | Every subagent-driven slice (mandatory review lens). | Gentleman-Programming |
| `judgment-day` | High-stakes diffs (auth, secrets, migrations). | Gentleman-Programming |
| `documentation-alan-style` | Writing or refactoring any document. | DysTelefonica/team-skills |
| `repository-delivery-governance` | Auditing or changing CI/CD, issue/PR/label governance, branch protection, merge permissions, artifacts, deployment, or rollback. | DysTelefonica/team-skills |
| `cognitive-doc-design` | Reducing cognitive load in a doc. | Gentleman-Programming |
| `branch-pr` | Any PR creation or merge. | Gentleman-Programming |
| `gentle-ai-ai-slop-discipline` | Any AI-assisted implementation in this repo (writing or reviewing PRs, planning fixes, drafting issues, amending code/prose/tests). Enforces pre-submission self-review against the 4 questions + 3 signatures of AI slop. | Gentleman-Programming |
| `skill-creator` | Creating new skills following the pattern. | Gentleman-Programming |

## Backend: PostgreSQL local

El backend de datos activo es PostgreSQL. `app/main.py` construye `LocalPostgresExecutor` desde `APAP_LOCAL_DB_URL` y lo entrega a la aplicación mediante el contrato `SqlExecutor`.

- **Lógica de aplicación** — dependa de `SqlExecutor` o del port específico del slice; no acople dominio o application a `psycopg`.
- **Composición** — construya el ejecutor en `app/main.py` o en el composition root del proceso de migración.
- **API separada** — `app/core/local_backend/app.py` conserva contratos de compatibilidad para pruebas y verificadores; no está montada en `app.main`.
- **Docs** — consulte [`docs/architecture/architecture-local-backend-stack.md`](docs/architecture/architecture-local-backend-stack.md) antes de cambiar datos, auth, storage o migración.

## Operational premises

El proyecto descansa sobre cuatro premisas no negociables. El detalle vive en los docs enlazados; esta sección enuncia el bullet para que la regla sea difícil de pasar por alto.

- **P1 — Fidelidad al legacy Access/VBA.** Toda capacidad legacy se conserva o se reemplaza por un equivalente documentado en [`docs/architecture/decisiones-proyecto.md`](docs/architecture/decisiones-proyecto.md). Una brecha descubierta abre un issue `type:bug gap:legacy`.
- **P2 — Escalera de duda de dominio.** Discovery doc → decisiones-proyecto → legacy-* → Dysflow MCP sobre el binario Access. Solo `vba-access` y `access-vba-tdd` están permitidos para trabajo Access en APAP_WEB.
- **P3 — Los documentos reflejan el código.** Cuando código y doc diverjan, gana el código y la doc se actualiza en la misma sesión.
- **P4 — Pre-MVP single-branch.** Todo el trabajo aterriza en `main` directamente; `staging` se reactiva solo por declaración explícita del usuario (ver [docs/codebase/merge-workflow.md](docs/codebase/merge-workflow.md) §15.4).

## Reinforcement

Si una IA está escribiendo código o docs en este repo sin cargar las skills relevantes, está trabajando a ciegas. Las skills son la single source of truth para "cómo se hace X en este proyecto". **Cargá primero, escribí después**. Si una IA escribe una doc sin haber cargado `documentation-alan-style`, la doc será rechazada en review — el formato no cumplirá con el patrón del repo. Las 33 reglas operacionales del proyecto ya no viven en este archivo; viven en `docs/codebase/`, según la tabla de Quick Navigation abajo.

## Quick navigation — reglas operacionales en `docs/codebase/`

Las 33 reglas de AGENTS (numeradas §1-§33) viven ahora en `docs/codebase/`. Esta tabla enumera cada bloque y enlaza el archivo que la contiene.

| Reglas | Página | Tema |
|---|---|---|
| §1-§7 | [layer-boundaries.md](docs/codebase/layer-boundaries.md) | Límites de capa, yield de dependencias, `Settings` cached, default-deny, redirects |
| §8 | [code-quality-rules.md](docs/codebase/code-quality-rules.md) | Sin librerías deprecadas; validar con context7 antes de pinear |
| §9 | [logging-conventions.md](docs/codebase/logging-conventions.md) | `log_safe` único en `app/`; redacción de doce campos |
| §10 | [csrf-defense.md](docs/codebase/csrf-defense.md) | `CsrfMiddleware` + token en cada form post + `SameSite=Strict` |
| §11, §6, §29 | [security.md](docs/codebase/security.md) | `CRITICAL_HELPERS` 100%, default-deny en flags, auth cache in-process |
| §12, §13, §22, §30 | [code-quality-rules.md](docs/codebase/code-quality-rules.md) | Audit doc, runbook, seam de query, docstrings sincronizados |
| §14 | [codegraph-conventions.md](docs/codebase/codegraph-conventions.md) | Índice CodeGraph persistente, daemon vivo, sync tras checkout |
| §15 | [merge-workflow.md](docs/codebase/merge-workflow.md) | Pre-MVP gate, ciclo de vida de rama, post-MVP revert, standing auth |
| §16 | [process.md](docs/codebase/process.md) | Issue lifecycle con P1-P4; opera con `docs/proceso.md` |
| §17 | [orchestrator-discipline.md](docs/codebase/orchestrator-discipline.md) | Coordinar, delegar, lentes de revisión, AGENTS.md vía PR |
| §18, §31, §33 | [architecture.md](docs/codebase/architecture.md) | Modo exclusivo web↔legacy, Protocol, ubicación de slice hexagonal |
| §19, §20, §23, §24 | [quality-gates.md](docs/codebase/quality-gates.md) | Cobertura 80%, linter APAP, E2E net, mypy zero errores |
| §21, §28 | [module-size-budgets.md](docs/codebase/module-size-budgets.md) | 700 líneas módulo / 50 líneas handler con BASELINE shrink-only |
| §25, §26, §27 | [import-hygiene.md](docs/codebase/import-hygiene.md) | Helpers sin duplicar, lazy-imports justificados, API pública cross-módulo |
| §32 | [anti-patterns.md](docs/codebase/anti-patterns.md) | P1-P8 formas recurrentes (auditoría 2026-07-25) |

## Existing references

| Referencia | Path | Propósito |
|---|---|---|
| Hub navegable del repo | [`docs/CODEBASE-GUIDE.md`](docs/CODEBASE-GUIDE.md) | Primera parada para quien aterriza; índice radial. |
| Mental model del proyecto | [`docs/codebase/mental-model.md`](docs/codebase/mental-model.md) | Qué es APAP_WEB, qué no es, invariantes. |
| Mapa de ownership por paquete | [`docs/codebase/repository-map.md`](docs/codebase/repository-map.md) | Qué paquete posee qué; dónde va código nuevo. |
| Playbook operativo por issue | [`docs/proceso.md`](docs/proceso.md) | Workflow de open a closed con evidencia (P1-P4). |
| Roadmap | [`docs/roadmap.md`](docs/roadmap.md) | Fases del producto y estado actual. |
| Decisiones de proyecto | [`docs/architecture/decisiones-proyecto.md`](docs/architecture/decisiones-proyecto.md) | Divergencias formales con el legacy. |
| Auditorías | [`docs/audits/`](docs/audits/) | Un documento por slice sensible. |
| Runbooks | [`docs/runbooks/`](docs/runbooks/) | Procedimientos que exigen acción del operador. |
| Hardening del arnés de calidad | [`docs/quality/hardening-roadmap.md`](docs/quality/hardening-roadmap.md) | Estado de los gates automáticos. |

<!-- personal-skills:slice:APAP_WEB @ v3f69990 -->
# slices/partials/web.md

## Manera de trabajar en proyectos web

> Aplica a todo `primary_type: web` del catálogo. Las invariantes de ciclo de vida de PR aquí enunciadas se complementan con las skills universalmente activas — véase `personal-skills/AGENTS.md` raíz para el sistema de propagación, `propagate-team-skills.ps1` para la mecánica de distribución, y el bloque de partials específicos del consumer para las convenciones del proyecto concreto.
>
> Este partial enuncia invariantes. Los procedimientos asociados viven en sus skills respectivas — no se duplican aquí.

### Forma del ciclo

- Toda issue es **atómica**: la cambia una persona, la cierra un PR (o varias si encadenadas vía `chained-pr` cuando la diff supera el presupuesto).
- Toda issue aprobada tiene una **rama propia** con el nombre `<tipo>/<nº issue>-<kebab-slug>`, validado por `scripts/check_branch_name.py` del consumer o equivalente.
- Toda rama se desarrolla en un **worktree dedicado** bajo el layout canónico de `worktree-reorg-per-project` v2.0 (sibling-container `<project>-worktrees/<wt-name>/`).
- Toda PR apunta a la `active_branch` declarada en `fleet/registry.json` para el ciclo activo. Pre-MVP single-branch implica `main` por defecto; el flip a `staging` post-MVP sigue la llave de vocabulario documentada en `intake-roadmap-loop` HR-4/HR-8.

### Presupuesto de revisión

- Toda PR se mantiene bajo el **presupuesto de revisión de 400 líneas** (`additions + deletions`), comprobado por `scripts/check_pr_size.py` o equivalente.
- 400 líneas es **techo de revisión, no techo de tamaño**: a partir de esa cifra la revisión pasa de atenta a vistazo. La justificación completa vive en el `CONTRIBUTING.md` de cada consumer; este partial la enuncia sin duplicar.
- La excepción `size:exception` requiere, **obligatoriamente**, en el cuerpo del PR: `size-exception-reason: <por qué>` más un enlace a la evidencia que justifique la superación. La etiqueta `size:exception` queda como mecanismo opcional por consumer (útil para detección CI automática; no es regla invariante).
- Cuando la diff supera el presupuesto, el orden de escape es: (1) partir por unidad de trabajo, (2) encadenar PRs vía `chained-pr`, (3) `size:exception` como último recurso. Si la excepción se vuelve habitual, el problema está en el troceado del issue, no en el presupuesto.

### Worktree y rama remota

- El **worktree local** se elimina tras el merge, vía `git worktree remove <path>` + `git worktree prune`. Mecánica detallada en `worktree-reorg-per-project` Phase 3.
- La **rama remota** se conserva tras el merge. Nunca `git push origin --delete <rama>`. La granularidad por unidad de trabajo se preserva precisamente porque las ramas quedan referenciables desde el historial de PRs.
- La estrategia de merge (`--squash` o `--no-ff`) es decisión del consumer; ambas son válidas. La **invariante** es que la rama remota sobreviva al merge, no la forma concreta del commit en `main`.

### Disciplina de revisión

- El CI debe estar **verde contra la base actual** antes de pedir revisión. Si la rama base avanzó durante la vida del PR, **rebase + rerun del CI** antes de declarar mergeable. El verde contra una base obsoleta es stale-green y corrompe el merge.
- **Rojo en CI pisa todo el merge.** Regla humana: el revisor no debe pulsar merge con ningún check rojo, ni siquiera si el rojo parece trivial. Complemento técnico: `repository-delivery-governance` HR-7 + `deterministic-quality-harness` HR-1 fail-loud atajan el escenario cuando hay branch protection automatizada.
- Donde GitHub Team no está disponible, el consumer replica la barrera con un job `merge-ready` signal-only (ver `access2web-blueprint/ci.yml` como referencia portable) que exit-non-zero si `gh pr view mergeable != true` o `reviewDecision != APPROVED`.
- Cuando el CI rojo es por **infra** (runner colgado, red, secret rotado), abrir issue bloqueante de CI y enlazarla desde el PR; no embutir la fix infra en el PR del feature salvo que sea ≤30 LOC y se cierre en el día.

### Anti-slop y atribución

- Anti-slop y anti-sobreingeniería de IA se delegan a la skill T1 upstream `gentle-ai-ai-slop-discipline` (4 preguntas, 3 firmas, scope boundary guard para subagentes). El partial no redefine las firmas — el consumer que adopte la skill las aplica automáticamente al revisar PRs.
- **Sin atribución de IA en commits**: no se añade `Co-Authored-By: ... <AI>` ni equivalente. Esta regla vive también en `personal-skills/AGENTS.md` raíz de la flota; el partial la refleja para que sea visible en el slice de web.
- Mensajes de commit en conventional commits. Castellano peninsular formal (usted) en artefactos documentales raíz; inglés en código, comentarios, mensajes de commit y PR bodies.

### CodeGraph preflight (cuando aplique)

- Si el consumer tiene índice CodeGraph (`.codegraph/` presente), el workflow sigue `engineering-workflow` líneas 64-71: `codegraph init` antes del primer edit, `codegraph_explore` antes de cualquier grep/read/glob amplio. No se reinventa aquí.
- Si el consumer no soporta CodeGraph, el preflight se omite sin romper invariante — la regla es "usar CodeGraph cuando esté disponible", no "requerir CodeGraph siempre".

### Divergencias documentadas (no son invariantes)

Estas decisiones quedan a la flota / consumer; el partial las registra para que las revisiones no las traten como incumplimientos.

- **Merge strategy.** `--squash` o `--no-ff`, ambos válidos. Invariante compartida: la rama remota se preserva en cualquier caso.
- **Etiqueta `size:exception`.** Opcional por consumer. Invariante compartida: el `size-exception-reason:` en el cuerpo del PR es obligatorio.
- **Pre-MVP vs post-MVP base branch.** Mientras no haya flip explícito del usuario con la llave de vocabulario documentada en `intake-roadmap-loop` HR-4/HR-8, todo aterriza en `main`.
- **Convención multi-app.** Si el consumer migra varias apps, el prefijo de issue/commit es decisión propia; el commit debe identificar el scope de cualquier manera.

### Procedencia (skills que alimentan este partial)

Cada invariante de este partial se ancla a una skill específica del catálogo o upstream. Si la skill referenciada cambia su HR, este partial requiere reauditoría.

- Issue-first atómica → `intake-roadmap-loop` HR-1, HR-14; upstream `engineering-workflow` Step 2.
- Rama `<tipo>/<nº>-<slug>` → `repository-delivery-governance` HR-4 (documentado/CI-enforced).
- Un worktree por issue → `worktree-reorg-per-project` v2.0 (layout + Phase 3 cleanup).
- Base pre-MVP = main → upstream `engineering-workflow` líneas 46-51; flip post-MVP vía `intake-roadmap-loop` HR-4/HR-8.
- 400 líneas + `size:exception` → `deterministic-quality-harness` Decision Gate línea 56; upstream `chained-pr` HR-1 línea 16.
- Rojo en CI pisa todo → `repository-delivery-governance` HR-7; upstream `engineering-workflow` línea 79.
- Rama remota preservada, WT local delete post-merge → `worktree-reorg-per-project` Phase 3.
- Anti-slop → upstream `gentle-ai-ai-slop-discipline` (T1 universal).
- CodeGraph preflight → upstream `engineering-workflow` líneas 64-71; `codegraph-usage` HR-1, HR-2.
- Conventional commits + castellano peninsular en artefactos + sin atribución IA → `personal-skills/AGENTS.md` raíz de flota.

### Cómo auditar este partial usted mismo

Procedimiento de validación periódica (mensual o por release de skill fuente):

- Confirmar que las HRs citadas en §Procedencia siguen existiendo con la misma numeración y redacción en el cuerpo actual de cada skill. Si una skill referenciada cambia su HR, este partial requiere reauditoría.
- Confirmar que no se haya añadido regla con cuerpo procedural en este partial — los procedimientos viven en skills, no aquí.
- Confirmar que la sección §Divergencias documentadas sigue reflejando las variantes reales de los consumers actuales.

### Antipatrones

- "Esperar a que CI esté verde para mergear" sin rebasear contra la base actual — el verde contra base obsoleta es stale-green.
- "Borrar la rama remota post-merge porque ya está mergeada" — destruye la granularidad por unidad de trabajo que el flujo pretende crear.
- "PR con 600 líneas porque el feature lo requiere" — partir primero, encadenar después; `size:exception` es el último recurso, no la primera opción.
- "Mergear con CI rojo aunque el rojo parezca trivial" — la trivialidad la decide el revisor, no el autor.
- "Esperar a que el reviewer apruebe manualmente aunque todos los checks estén verdes" en proyectos con auto-merge standing explícito — revisar la sección de revocación de `merge-workflow.md §15.6` antes de saltarse el gate.
<!-- /personal-skills:slice:APAP_WEB -->
