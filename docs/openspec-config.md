# OpenSpec config for SDD

[Back to Codebase Guide](CODEBASE-GUIDE.md)

`openspec/config.yaml` es la convención documentada a nivel de proyecto para SDD en este repositorio. Centraliza el contexto que cada fase SDD consume y las reglas específicas por fase (proposal, specs, design, tasks, apply, verify, archive). Esta página registra qué significa ese contrato en la práctica y qué partes están hoy dirigidas por prompt en lugar de por un validador.

La página NO duplica el archivo YAML: lo resume y lo enlaza. El YAML vive en [`openspec/config.yaml`](../openspec/config.yaml) y es la fuente única de verdad.

## What support means today

En el repositorio actual, el respeto a `openspec/config.yaml` es mayormente dirigido por prompt:

- Las skills SDD y los prompts del orquestador indican a los agentes que lean o escriban este archivo.
- `sdd-init` y los ejemplos de convención compartida muestran la forma del archivo que se espera que los agentes creen.
- Las fases posteriores reutilizan valores como `context`, `strict_tdd`, `rules` y `testing`.

Lo que NO es cierto hoy:

- No hay parser ni validador en Python que enforce un schema canónico.
- No hay contrato de compatibilidad que garantice el consumo uniforme de todos los campos en todas las fases.
- La forma exacta del archivo es convención vigente, no especificación pública versionada.

> El patrón proviene de [`Gentleman-Programming/gentle-ai`](https://github.com/Gentleman-Programming/gentle-ai/blob/main/docs/openspec-config.md) (skill v2.1 §11). No se inventa localmente: se adapta.

## What this file can customize

`openspec/config.yaml` permite customizar el comportamiento SDD según las convenciones del proyecto:

| Sección | Propósito |
|---|---|
| `schema` | Identifica el archivo como configuración SDD; valor vigente: `spec-driven`. |
| `context` | Bloque multilínea con stack, backend, frontend, BaaS, deployment, auth, legacy y estado actual. Es el contexto cacheado que reutilizan las fases posteriores. |
| `rules.proposal` | Exigencias del proyecto para la propuesta (scope, plan de migración ante cambios de modelo de datos, referencia a discovery). |
| `rules.specs` | Convenciones de redacción de specs (Given/When/Then, RFC 2119, idioma Castellano peninsular formal). |
| `rules.design` | Restricciones arquitectónicas (FastAPI + HTMX, server-rendered sobre SPA, reglas de negocio en FastAPI). |
| `rules.tasks` | Granularidad de tareas (agrupación por dominio, una sesión, testeable de forma independiente). |
| `rules.apply` | Notas operativas para implementación (`tdd`, `test_command`, `build_command`). |
| `rules.verify` | Comandos exactos que CI ejecuta (`test_command`, `e2e_command`, `lint_command`, `build_command`, `coverage_threshold`). |
| `rules.archive` | Verificaciones antes de archivar un cambio. |
| `testing` | Capacidades de testing cacheadas: `has_test_runner`, `strict_tdd`, `test_framework`, `test_layers`, `e2e`, `coverage_tool`, `linter`, `type_checker`, `formatter`, `rationale`. |

## Which phases reference it

Las fases SDD que este proyecto ejecuta y cómo leen el config:

| Fase | Lee o escribe de `openspec/config.yaml` |
|---|---|
| `sdd-init` | Escribe `context`, `rules` y `testing` al crear el archivo. |
| `sdd-explore` | Lee `context` como parte del descubrimiento de proyecto. |
| `sdd-propose` | Aplica `rules.proposal` si está presente. |
| `sdd-spec` | Aplica `rules.specs` si está presente. |
| `sdd-design` | Aplica `rules.design` si está presente. |
| `sdd-tasks` | Aplica `rules.tasks` si está presente. |
| `sdd-apply` | Lee `strict_tdd`, `testing` y `rules.apply` si están presentes. |
| `sdd-verify` | Lee `strict_tdd`, `testing` y `rules.verify` si están presentes. |
| `sdd-archive` | Aplica `rules.archive` si está presente. |

Las fases de cambio (`sdd-propose`, `sdd-spec`, `sdd-design`, `sdd-tasks`, `sdd-apply`, `sdd-verify`, `sdd-archive`) son las que `docs/proceso.md` describe como camino operativo para tomar una issue de `open` a `closed`.

## Synthesized convention example

Contenido actual de [`openspec/config.yaml`](../openspec/config.yaml), verbatim, como ejemplo concreto de la convención sintetizada en este repositorio:

```yaml
schema: spec-driven

context: |
  Project: APAP — Registro de Protectoras de Animales de Alcalá (web migration)
  Backend: FastAPI 0.136.3, Jinja2 3.1.x, Pydantic 2.13.4, HTTPX 0.28.1, Uvicorn 0.49.0
  Frontend: HTMX 2.0.4 + Tailwind CSS 4.3.1 (CSS-first, Node.js CLI)
  BaaS: InsForge (PostgreSQL + PostgREST, Auth via Google OAuth, Storage, Functions)
  Deployment: Coolify on project VPS
  Auth model: Google OAuth (InsForge) + allowlist authorization in FastAPI middleware
  Legacy: APAP_ACTUAL (Access/VBA) — reference only, not runtime target
  Current state: FastAPI application code exists under app/ with pytest coverage under tests/; active SDD change intake-entradas-crud is in progress

rules:
  proposal:
    - Scope web app features, not Access mechanics
    - Include migration/adaptation plan for each breaking data model change
    - Reference business discovery docs in docs/discovery/
  specs:
    - Use Given/When/Then for scenarios
    - Use RFC 2119 keywords (MUST, SHALL, SHOULD, MAY)
    - Use professional Spanish (Spain) for all SDD artifacts
  design:
    - Follow FastAPI + HTMX architecture in docs/architecture/architecture-insforge-stack.md
    - Prefer server-rendered pages over SPA
    - Keep business rules in FastAPI, not HTMX snippets
  tasks:
    - Group by feature domain (animal lifecycle, intake, health, documents, volunteers)
    - Keep tasks completable in one session
    - Each task must be independently testable
  apply:
    notes:
      - Follow existing code patterns once implementation starts
      - Use the repository virtualenv Python on Windows: C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe
    tdd: true
    test_command: "C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m pytest"
    build_command: "C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m build"
  verify:
    test_command: "C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m pytest"
    e2e_command: "C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m pytest tests/e2e/"
    lint_command: "C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m ruff check ."
    build_command: "C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m build"
    coverage_threshold: 80
  archive:
    - Validate completeness before archiving

testing:
  has_test_runner: true
  strict_tdd: true
  test_framework: pytest
  test_layers: [unit, integration]
  e2e: playwright
  coverage_tool: pytest-cov
  linter: ruff
  type_checker: none
  formatter: none
  rationale: "Pytest/ruff/build are declared for the CI/CD foundation; install dev extras before running local verification."
```

## Cross-references

- Skill v2.1 §11 (caso verificado: `Gentleman-Programming/gentle-ai`).
- [`AGENTS.md`](../AGENTS.md) §16 — workflow por issue (P1-P4).
- [`docs/proceso.md`](proceso.md) — playbook operativo de `open` a `closed`.
- [`openspec/config.yaml`](../openspec/config.yaml) — el archivo en sí, fuente única de verdad.

## Core invariants

- **Config-real-over-spec**: este doc refleja el contenido actual de `openspec/config.yaml`. Si el YAML cambia, este doc se actualiza en la misma sesión.
- **Skill-caso-verificado**: el patrón proviene de `Gentleman-Programming/gentle-ai`. No se inventa localmente.
- **Single-source-of-truth**: este doc resume el YAML, no lo duplica. La excepción es la sección "Synthesized Convention Example", que es verbatim.
- **Castellano-peninsular**: la prosa va en Castellano peninsular formal (usted). El bloque YAML se mantiene intacto en inglés.
- **Path-references**: las rutas que aparecen en el YAML (por ejemplo, `docs/architecture/architecture-insforge-stack.md`) son rutas lógicas del proyecto. Si alguna no resuelve, prima el código y se abre un issue `type:bug gap:docs`.

## Contributor checklist

- [ ] El doc conserva las cuatro secciones del caso de `Gentleman-Programming/gentle-ai` (`What support means today`, `What this file can customize`, `Which phases reference it`, `Synthesized convention example`).
- [ ] La tabla "Which phases reference it" coincide con las fases que el workflow de `docs/proceso.md` ejecuta.
- [ ] La sección "Synthesized convention example" es verbatim con `openspec/config.yaml` actual.
- [ ] Castellano peninsular formal en prosa; YAML intacto en inglés.
- [ ] Sin emojis decorativos ni marketing fluff.
- [ ] Cada cross-reference resuelve a un archivo existente en el repositorio.

## Navigation

Back: [AGENTS.md](../AGENTS.md) | Next: [CODEBASE-GUIDE.md](CODEBASE-GUIDE.md)