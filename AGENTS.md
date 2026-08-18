---
description: Agent instructions and code-quality rules for APAP_WEB (FastAPI + HTMX + InsForge backend)
globs: *
alwaysApply: true
---

# APAP_WEB — Agent Skills Index

APAP_WEB es una aplicación web FastAPI + HTMX + Jinja2 (Python `>=3.11`) con arquitectura por capas estricta en transición a hexagonal con slices verticales (ver [docs/codebase/architecture.md](docs/codebase/architecture.md)). Cuando trabaje en este proyecto, cargue las skills relevantes ANTES de escribir código o docs.

## How to use

1. Revise la columna "trigger" para identificar las skills que matchean la tarea actual.
2. Cargue la skill leyendo el `SKILL.md` indicado en la columna "path".
3. Siga TODOS los patrones y reglas de la skill cargada.
4. Varias skills pueden aplicar simultáneamente; cargue cada una por su SKILL.md.
5. En duda, prefiera la skill más específica (por ejemplo, `apap-merge-workflow` sobre `branch-pr` para política de merge).

## Mandatory skills

| Skill | Cuándo cargarla |
|---|---|
| **`documentation-alan-style`** | Cualquier documento escrito o revisado — `README`, este `AGENTS.md`, `DOCS`, `CODEBASE-GUIDE`, `CONTRIBUTING`, `CHANGELOG`, epics, walkthroughs. |
| **`branch-pr`** | Cualquier commit, apertura de PR o merge a `main`. Merge con `--no-ff`, nunca con `--delete-branch` (ver [docs/codebase/merge-workflow.md](docs/codebase/merge-workflow.md)). |
| **`code-review-expert`** | Cualquier slice dirigido por subagent que aterrice en `main` (lente de revisión obligatoria, §17.2). |
| **`judgment-day`** | Cualquier diff high-stakes (auth, secrets, CSRF, PII, migraciones, SQL crudo). |

## Project-context skills (este repo)

| Skill | Trigger | Path |
|---|---|---|
| `apap-architecture` | Routes, services, queries layer, límites de capa, validación, migración a slices hexagonales (§33). | [`skills/apap-architecture/SKILL.md`](skills/apap-architecture/SKILL.md) |
| `apap-security` | Auth (§6, §29), CSRF (§10), secrets (§8), log_safe (§9), PII. | [`skills/apap-security/SKILL.md`](skills/apap-security/SKILL.md) |
| `apap-testing` | CRITICAL_HELPERS (§11), cobertura (§19), configuración pytest. | [`skills/apap-testing/SKILL.md`](skills/apap-testing/SKILL.md) |
| `apap-migration` | `app/core/migration/`, sync bidireccional, `python -m migration reconcile`. | [`skills/apap-migration/SKILL.md`](skills/apap-migration/SKILL.md) |
| `apap-merge-workflow` | Política pre-MVP single-branch (§15), ciclo de vida de rama, autorización standing de merge. | [`skills/apap-merge-workflow/SKILL.md`](skills/apap-merge-workflow/SKILL.md) |
| `apap-orchestrator-discipline` | Coordinación de subagents (§17), patrones de delegación, lentes de revisión. | [`skills/apap-orchestrator-discipline/SKILL.md`](skills/apap-orchestrator-discipline/SKILL.md) |

> Las skills viven físicamente en `~/.config/opencode/skills/` y están linkeadas en opencode. Si necesitás editar las skills, editá el original. Si una skill listada no existe físicamente, créala primero siguiendo `skill-creator` o `skill-improver`.

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
| `cognitive-doc-design` | Reducing cognitive load in a doc. | Gentleman-Programming |
| `branch-pr` | Any PR creation or merge. | Gentleman-Programming |
| `skill-creator` | Creating new skills following the pattern. | Gentleman-Programming |

## Backend: InsForge (accessed from Python)

El backend de datos es **InsForge** (PostgreSQL + auth + storage). Este proyecto NO usa `@insforge/sdk` de TypeScript — no hay `package.json` ni frontend Node. Todo acceso al backend pasa por el cliente Python en [`app/core/insforge.py`](app/core/insforge.py). Trate InsForge como un BaaS Postgres-backed alcanzado sobre HTTP desde Python.

- **Lógica de aplicación** (auth, CRUD, storage) — llame al `InsForgeClient` Python en `app/core/insforge.py`. Nunca recurra al TS SDK ni a `npm`.
- **Infraestructura** (schema, buckets, functions, deploy) — use las herramientas MCP de InsForge: `run-raw-sql`, `get-table-schema`, `create-bucket`, `create-function`, `get-backend-metadata`.
- **Docs** — cuando necesite comportamiento actual de la API InsForge, obténgalo con `fetch-sdk-docs` (idioma `rest-api` o `typescript` para referencia de forma); no confíe en la memoria.

## Operational premises

El proyecto descansa sobre cuatro premisas no negociables. El detalle vive en los docs enlazados; esta sección enuncia el bullet para que la regla sea difícil de pasar por alto.

- **P1 — Fidelidad al legacy Access/VBA.** Toda capacidad legacy se conserva o se reemplaza por un equivalente documentado en [`docs/decisiones-proyecto.md`](docs/decisiones-proyecto.md). Una brecha descubierta abre un issue `type:bug gap:legacy`.
- **P2 — Escalera de duda de dominio.** Discovery doc → decisiones-proyecto → legacy-* → Dysflow MCP sobre el binario Access. Solo `vba-access` y `access-vba-tdd` están permitidos para trabajo Access en APAP_WEB.
- **P3 — Los documentos reflejan el código.** Cuando código y doc diverjan, gana el código y la doc se actualiza en la misma sesión.
- **P4 — Pre-MVP single-branch.** Todo el trabajo aterriza en `main` directamente; `staging` se reactiva solo por declaración explícita del usuario (ver [docs/codebase/merge-workflow.md](docs/codebase/merge-workflow.md) §15.4).

## Reinforcement

Si una IA está escribiendo código o docs en este repo sin cargar las skills relevantes, está trabajando a ciegas. Las skills son la single source of truth para "cómo se hace X en este proyecto". **Cargá primero, escribí después**. Si una IA escribe una doc sin haber cargado `documentation-alan-style`, la doc será rechazada en review — el formato no cumplirá con el patrón del repo. Las 33 reglas operacionales del proyecto ya NO viven en este archivo; viven en `docs/codebase/`, según la tabla de Quick Navigation abajo.

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
| Decisiones de proyecto | [`docs/decisiones-proyecto.md`](docs/decisiones-proyecto.md) | Divergencias formales con el legacy. |
| Auditorías | [`docs/audits/`](docs/audits/) | Un documento por slice sensible. |
| Runbooks | [`docs/runbooks/`](docs/runbooks/) | Procedimientos que exigen acción del operador. |
| Hardening del arnés de calidad | [`docs/quality/hardening-roadmap.md`](docs/quality/hardening-roadmap.md) | Estado de los gates automáticos. |
