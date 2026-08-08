[← Back to README](../README.md)

# APAP_WEB Codebase Guide

**This guide is for maintainers and contributors who need to understand where APAP_WEB responsibilities live, which invariants are non-negotiable, and which file to open when something needs to change.**

APAP_WEB es la reescritura web del Access/VBA de APAP sobre FastAPI e InsForge. Esta guía cubre ownership, flujos y guardrails; no repite producto ni stack.

## 90-second mental model

El repositorio convive con dos formas de slice. Los módulos de dominio bajo `app/modules/` siguen el layout legacy `routes → service → queries`. Las capacidades transversales ya convertidas viven bajo `app/core/` con layout hexagonal, según [AGENTS.md](../AGENTS.md) §33.

```text
                    browser (HTML + Tailwind v4)
                              │  cookie firmada, SameSite=Strict
                              ▼
        FastAPI / Uvicorn  —  middlewares (UA, CSRF, auth)
                              │
              ┌───────────────┴────────────────┐
              ▼                                ▼
   LEGACY SLICE                       HEXAGONAL SLICE
   app/modules/<area>/                app/core/<layer>/<slice>/
              │                                │
   routes.py  │ HTTP only            routes / handlers │ HTTP only
        │     ▼                                │     ▼
   service.py  validación + dominio     application/  use case
        │     ▼                                │     ▼
   queries.py  construcción de SQL      ports/  Protocol (sin transporte)
        │                                      │     ▼
        │                              adapters/insforge/  adapter + queries
        └───────────────┬──────────────────────┘
                        ▼
              app/core/insforge.py  (InsForgeClient)
                        ▼
              InsForge  —  PostgreSQL · Auth · Storage
```

> **Todo request entra por una route delgada, cruza exactamente una capa de dominio y sale por un único cliente hacia InsForge; lo que rompe esa línea recta es lo que los gates rechazan.**

### Qué está convertido y qué no

La conversión avanza por capacidad, no por módulo. Hoy los slices hexagonales viven bajo `app/core/`; los módulos de negocio bajo `app/modules/` conservan el layout plano `routes.py`, `service.py`, `queries.py`.

| Ubicación | Slices | Layout |
|---|---|---|
| `app/core/` | `auth`, `oauth`, `catalogos`, `schema_bootstrap`, `admin` | `domain/`, `ports/`, `application/`, `adapters/insforge/`, `di/` |
| `app/modules/` | `animals`, `voluntarios`, `entradas`, `foster`, `acogidas`, `adopciones`, `sanidad`, `cesiones`, `materiales`, `salud`, `tasks` | `routes.py`, `service.py`, `queries.py` |

`app/core/application/admin/` es una excepción registrada a propósito en [AGENTS.md](../AGENTS.md) §33.5: aterrizó en `core` por orden de conversión, no por ser transversal. No la cite como precedente.

El orden de migración y la definición de hecho viven en la épica #420, no en esta guía.

## Recommended reading path

| Step | Page | Read this when... |
|---|---|---|
| 1 | [README](../README.md) | Necesita entender el producto en cinco minutos antes de abrir código. |
| 2 | Esta guía | Necesita ubicar responsabilidades y saber qué archivo abrir. |
| 3 | [Arquitectura InsForge](architecture-insforge-stack.md) | Necesita el contrato de stack, las reglas InsForge y el target de despliegue. |
| 4 | [AGENTS.md](../AGENTS.md) §1–§7 | Va a escribir una route o un service y necesita los límites de capa. |
| 5 | [AGENTS.md](../AGENTS.md) §33 | Va a crear una capacidad nueva y debe decidir `core` frente a `modules`. |
| 6 | [Proceso](proceso.md) | Va a tomar una issue y llevarla hasta el cierre con evidencia. |
| 7 | [Roadmap](roadmap.md) | Necesita saber qué fase está abierta y qué issue cubre su trabajo. |
| 8 | [Decisiones de proyecto](decisiones-proyecto.md) | Encuentra una divergencia con el legacy y necesita saber si fue deliberada. |

## Quick map inverso

| Si necesita... | Abra primero | Y luego consulte |
|---|---|---|
| Añadir una route a un módulo existente | `app/modules/<area>/routes.py` | [AGENTS.md](../AGENTS.md) §1, §28 (route ≤ 50 líneas) |
| Añadir lógica de dominio a un módulo legacy | `app/modules/<area>/service.py` | [AGENTS.md](../AGENTS.md) §5, §22 (seam de queries) |
| Añadir un use case en un slice hexagonal | `app/core/application/<slice>/` | [AGENTS.md](../AGENTS.md) §33.3, §31 (Protocol) |
| Añadir un adapter o su SQL | `app/core/adapters/insforge/` | [AGENTS.md](../AGENTS.md) §33.4, §22 |
| Cambiar un gate de CI | [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) | `tests/test_ci_workflow.py`, [AGENTS.md](../AGENTS.md) §20 |
| Cambiar un campo de settings | [`app/core/config.py`](../app/core/config.py) | [Runbook de config](runbooks/startup-config-validation.md), [AGENTS.md](../AGENTS.md) §32.P2 |
| Cambiar o añadir un detector de reglas | [`scripts/check_rules.py`](../scripts/check_rules.py) | `tests/test_check_rules.py`, [AGENTS.md](../AGENTS.md) §20 |
| Escribir un test de una feature de UI | `tests/e2e/` | [AGENTS.md](../AGENTS.md) §23 (QA a través de la UI) |
| Localizar un runbook de operador | [`docs/runbooks/`](runbooks/) | [AGENTS.md](../AGENTS.md) §13 |
| Localizar una auditoría de un slice sensible | [`docs/audits/`](audits/) | [AGENTS.md](../AGENTS.md) §12 |

## Ownership y guardrails

Las reglas de este repositorio no dependen de la buena voluntad del revisor. La mayoría tiene un detector AST o un ratchet shrink-only detrás, y el job `lint` de CI los ejecuta en cadena.

Los ratchets solo admiten decrecer. Una entrada de baseline puede encoger o desaparecer; nunca crecer, y nunca se añaden entradas nuevas.

- **§20 `check_rules.py`** — APAP001 (SQL en route) y APAP003 (logger crudo), más los detectores 2 a 12.
- **§21 tamaño de módulo** — 700 líneas por módulo bajo `app/` y `migration/`.
- **§24 mypy** — cero errores sobre `app/` y `migration/`; todo `# type: ignore` lleva su código.
- **§25 dedup de helpers** — watch-list de helpers que no pueden reaparecer copiados entre módulos.
- **§26 lazy-import** — todo import local bajo `app/` lleva el marcador `lazy-import:` con su motivo.
- **§27 imports cross-module** — desde `app/modules/<A>/` solo se importa la API pública de `app.modules.<B>`.
- **§28 tamaño de route** — 50 líneas por handler, con baseline de los 15 handlers heredados.

| Rule | File | Detector | What it bans |
|---|---|---|---|
| §20 | [`scripts/check_rules.py`](../scripts/check_rules.py) | APAP001, APAP003, Detectores 2–12 | SQL en routes, `logger.*` y `print(...)` en `app/`, auth que abre por defecto. |
| §21 | [`scripts/check_module_size.py`](../scripts/check_module_size.py) | Ratchet `BASELINE` | Módulos de producto por encima de 700 líneas. |
| §24 | `pyproject.toml` `[tool.mypy]` | Job `typecheck` | Errores de tipado y `# type: ignore` sin código de error. |
| §25 | [`scripts/check_rules.py`](../scripts/check_rules.py) | Detector 10 | Helpers de la watch-list definidos en un archivo adicional. |
| §26 | [`scripts/check_rules.py`](../scripts/check_rules.py) | Detector 11 | Imports dentro de una función sin el marcador `lazy-import:`. |
| §27 | [`scripts/check_rules.py`](../scripts/check_rules.py) | Detector 12 | Imports a submódulos ajenos o a nombres con prefijo `_`. |
| §28 | [`scripts/check_route_size.py`](../scripts/check_route_size.py) | Ratchet `BASELINE` | Handlers de route por encima de 50 líneas. |
| §33 | [`scripts/check_layers.py`](../scripts/check_layers.py) | Gate de capas y slices | Transporte filtrado a `domain/`, `ports/` o `application/`. |

### Los gates que ejecuta el job `lint`

El job `lint` de [`ci.yml`](../.github/workflows/ci.yml) encadena `ruff` con quince guardias propias. Cada una sale con código distinto de cero ante la primera violación, y retirar un paso es un cambio bloqueado.

Varias guardias no corresponden a una regla numerada de `AGENTS.md`: nacieron del arnés de calidad descrito en [`docs/quality/hardening-roadmap.md`](quality/hardening-roadmap.md).

| Script | Qué protege |
|---|---|
| [`check_rules.py`](../scripts/check_rules.py) | APAP001 y APAP003 más los detectores 2 a 12. |
| [`check_module_size.py`](../scripts/check_module_size.py) | Presupuesto de 700 líneas por módulo. |
| [`check_route_size.py`](../scripts/check_route_size.py) | Presupuesto de 50 líneas por handler. |
| [`check_layers.py`](../scripts/check_layers.py) | Capas hexagonales y vertical slices. |
| [`check_slice_completeness.py`](../scripts/check_slice_completeness.py) | Slices incompletos, sin puerto o sin adapter. |
| [`check_migration_boundaries.py`](../scripts/check_migration_boundaries.py) | Fronteras del paquete `migration/`. |
| [`check_docstring_coverage.py`](../scripts/check_docstring_coverage.py) | Ratchet de cobertura de docstrings. |
| [`check_complexity.py`](../scripts/check_complexity.py) | Ratchet de complejidad ciclomática. |
| [`check_ruff_ratchet.py`](../scripts/check_ruff_ratchet.py) | Reglas de ruff extendidas aún no exigibles en bloque. |
| [`check_vulture_guard.py`](../scripts/check_vulture_guard.py) | Código muerto. |
| [`check_jscpd.py`](../scripts/check_jscpd.py) | Ratchet de código duplicado. |
| [`check_mutation_sites.py`](../scripts/check_mutation_sites.py) | Recuento de sitios de mutación. |
| [`check_import_cycles.py`](../scripts/check_import_cycles.py) | Ciclos de importación. |

Fuera de `lint`, el job `test` añade [`check_crap.py`](../scripts/check_crap.py) y el job `mutation` aplica [`check_mutation.py`](../scripts/check_mutation.py) sobre la sesión de Cosmic Ray.

## Where to find X

| X | Archivo | Documentación asociada |
|---|---|---|
| Autorización por request y allowlist | [`app/core/auth.py`](../app/core/auth.py) | [Auditoría de re-validación](audits/auth-revalidation-2026-Q3.md) |
| Caché de autorización con TTL | [`app/core/auth_cache.py`](../app/core/auth_cache.py) | [Runbook multi-worker](runbooks/auth-cache-multi-worker.md) |
| Enforcement de roles en rutas de escritura | [`app/core/auth_dependencies.py`](../app/core/auth_dependencies.py) | [Auditoría RBAC](audits/rbac-enforcement-2026-Q3.md) |
| Middleware CSRF y tokens de sesión | [`app/core/csrf.py`](../app/core/csrf.py) | [AGENTS.md](../AGENTS.md) §10 |
| Cookie firmada y rotación del secreto | [`app/core/session.py`](../app/core/session.py) | [Runbook de rotación](runbooks/cookie-rotation.md) |
| Logging estructurado y redacción de PII | [`app/core/logging.py`](../app/core/logging.py) | [Auditoría de logging](audits/logging-audit-2026-Q3.md) |
| Escapado de plantillas y allowlist | `app/templates/` | [Auditoría XSS](audits/xss-audit-2026-Q2.md) |
| Cliente HTTP hacia InsForge | [`app/core/insforge.py`](../app/core/insforge.py) | [Arquitectura InsForge](architecture-insforge-stack.md) |
| Validación de secretos en arranque | [`app/core/config.py`](../app/core/config.py) | [Runbook de config](runbooks/startup-config-validation.md) |
| Recuperación ante bloqueo de administradores | [`app/core/admin_handlers.py`](../app/core/admin_handlers.py) | [Runbook de lockout](runbooks/admin-lockout-recovery.md) |

## Operación

### Cómo contribuyo

- Lea [`docs/proceso.md`](proceso.md) al inicio de cada sesión que vaya más allá de docs triviales.
- Trabaje en una rama corta desde `main` con el prefijo del tipo de cambio, según [AGENTS.md](../AGENTS.md) §15.2.
- Aplique TDD estricto en `type:bug`, `type:feature` y `type:refactor`; rojo, verde, refactor.
- Ejecute el gate local antes del push: `pytest`, `ruff check .`, `python scripts/check_rules.py .`.
- Abra el PR con Conventional Commits en inglés y exactamente una etiqueta `type:*`.
- Mantenga el diff bajo las 400 líneas de presupuesto de revisión, o justifique `size:exception`.

### Cómo despliego

- El job `deploy` de CI firma y envía el webhook de Coolify en cada push a `main`.
- Antes de tocar un secreto, consulte [`docs/runbooks/startup-config-validation.md`](runbooks/startup-config-validation.md).
- Para rotar `APAP_SESSION_SECRET`, siga [`docs/runbooks/cookie-rotation.md`](runbooks/cookie-rotation.md); la rotación fuerza un logout global.
- Antes de subir el número de workers o réplicas, aplique [`docs/runbooks/auth-cache-multi-worker.md`](runbooks/auth-cache-multi-worker.md).
- Si el panel de administración queda sin developers activos, use [`docs/runbooks/admin-lockout-recovery.md`](runbooks/admin-lockout-recovery.md).
- Todo cambio que exija una acción manual del operador requiere su propio runbook, según [AGENTS.md](../AGENTS.md) §13.

### Cómo audito

- Todo slice que toque auth, secretos, cookies, CSRF, XSS, idempotencia o PII exige un documento en [`docs/audits/`](audits/), según [AGENTS.md](../AGENTS.md) §12.
- La estructura obligatoria es Scope, Methodology, Findings con tabla de severidad, y Verdict.
- Use [`docs/audits/xss-audit-2026-Q2.md`](audits/xss-audit-2026-Q2.md) como plantilla de referencia.
- Lance `code-review-expert` sobre el diff de cada slice, según [AGENTS.md](../AGENTS.md) §17.2.
- Añada `judgment-day` cuando el diff toque auth, secretos, PII, migraciones o SQL cruda.
- [`scripts/check_audit_and_runbook.py`](../scripts/check_audit_and_runbook.py) señala los paths sensibles como ayuda al desarrollador.

## Skills y agentes

Las skills son el single source of truth de «cómo se hace X en este proyecto». Cárguelas antes de escribir, no después.

| Skill | Trigger | Path |
|---|---|---|
| `agents-md-pattern` | Cualquier cambio sobre `AGENTS.md`. | Gentleman-Programming |
| `branch-pr` | Cualquier commit, creación de PR o merge a `main`. | Gentleman-Programming |
| `code-review-expert` | Cualquier slice conducido por subagente que aterrice en `main`. | Gentleman-Programming |
| `judgment-day` | Diffs de alto riesgo: auth, secretos, CSRF, PII, migraciones, SQL cruda. | Gentleman-Programming |
| `documentation-alan-style` | Redacción o refactor de documentación; reemplaza a `documentation-patterns`. | Gentleman-Programming |
| `apap-architecture` | Routes, services, capa de queries o migración hacia slices hexagonales. | `skills/apap-architecture/SKILL.md` |
| `apap-security` | Auth, CSRF, secretos, `log_safe` o PII. | `skills/apap-security/SKILL.md` |
| `apap-testing` | `CRITICAL_HELPERS`, cobertura o configuración de pytest. | `skills/apap-testing/SKILL.md` |
| `apap-migration` | `app/core/migration/`, sync bidireccional o `python -m migration reconcile`. | `skills/apap-migration/SKILL.md` |
| `codegraph-usage` | Uso del MCP o la CLI de CodeGraph, según §14. | Gentleman-Programming |

## Cross-references

- [README](../README.md) — producto, stack, quick start y configuración.
- [AGENTS.md](../AGENTS.md) — las 33 reglas del repositorio y su enforcement.
- [Arquitectura InsForge](architecture-insforge-stack.md) — contrato de stack y reglas del backend.
- [Proceso](proceso.md) — playbook operativo de una issue, de `open` a `closed`.
- [Roadmap](roadmap.md) — fases, slices en `main` y backlog alineado.
- [Decisiones de proyecto](decisiones-proyecto.md) — registro formal de decisiones.
- [Hoja de ruta de calidad](quality/hardening-roadmap.md) — estado del arnés de gates.
- [Política de lint TRY003 y PLR2004](policies/lint-policy-try003-plr2004.md) — decisión y guardia.
- [Auditorías](audits/) — un documento por slice sensible.
- [Runbooks](runbooks/) — procedimientos que exigen acción del operador.

## What this is / is not

| Es | No es |
|---|---|
| Un mapa de ownership: qué archivo es dueño de cada responsabilidad. | Un tutorial de instalación; eso vive en el README. |
| Un índice de los guardrails automáticos y de sus detectores. | La definición de las reglas; esa es `AGENTS.md`. |
| Un punto de entrada para orientarse en treinta segundos. | Una referencia de arquitectura; esa es `architecture-insforge-stack.md`. |
| Un índice hacia auditorías y runbooks existentes. | Un sustituto de leerlos cuando toque un path sensible. |
| Una guía para mantenedores y contribuidores. | Documentación de API ni contrato de endpoints. |

## Verification checklist

- [ ] Un único `H1`; secciones en `H2` y subsecciones en `H3`, sin `H4`.
- [ ] Castellano peninsular formal, tratamiento de usted, sin regionalismos.
- [ ] Ningún párrafo supera los doscientos caracteres.
- [ ] Diagrama del mental model en bloque `text`, por debajo de treinta líneas.
- [ ] Sin emojis decorativos y sin marketing fluff.
- [ ] Cada cross-reference resuelve a un archivo existente del repositorio.
- [ ] Sin duplicación de contenido que ya vive en `README.md` o en `architecture-insforge-stack.md`.

---

[Next: Architecture →](architecture-insforge-stack.md)
