# Mental model

[Back to Codebase Guide](../CODEBASE-GUIDE.md)

Esta página posee la definición de qué es APAP_WEB, qué no es y qué invariantes el proyecto no rompe. No posee reglas operativas — esas viven en [AGENTS.md](../../AGENTS.md) — ni el detalle de los paquetes — eso es [repository map](repository-map.md).

## What this project is

| It is | Evidence in this repo |
|---|---|
| Reescritura web server-rendered del Access/VBA legacy de APAP | [`README.md`](../../README.md), [Arquitectura InsForge](../architecture/architecture-insforge-stack.md) |
| App FastAPI + Jinja2 + HTMX con datos en InsForge (PostgreSQL) | [`app/main.py`](../../app/main.py), [`app/core/insforge.py`](../../app/core/insforge.py) |
| Proyecto hexagonal con vertical slices en migración | [`app/core/<layer>/<slice>/`](../../app/core/) para capacidades transversales; [`app/modules/<slice>/`](../../app/modules/) cuando la hexagonal vive en un módulo de negocio; [AGENTS.md](../../AGENTS.md) §33.2 |
| OpenSpec-driven: cada capacidad grande se describe antes de codear | [`openspec/specs/`](../../openspec/specs/), [`openspec/changes/`](../../openspec/changes/) |
| Arnés de gates automático (lint + typecheck + mutation) | [`scripts/check_*.py`](../../scripts/), [Quality roadmap](../quality/hardening-roadmap.md) |

## What this project is not

| It is not | Use this boundary |
|---|---|
| Un SDK publicable para terceros | El repo no expone paquete distribuible; `pyproject.toml` no declara `packages` ni entry points. |
| Un dashboard o panel de BI | No existe `dashboard/` ni framework de BI; las vistas son páginas por módulo de negocio. |
| Una API REST pura | El producto es server-rendered; las rutas devuelven HTML, no JSON excepto donde la UI lo requiere. |
| Un monolito por capas estable | El layout `app/modules/` está en transición hexagonal capa por capa in-place (dominio + puertos + aplicación + adapter dentro del propio módulo, no extracción a `app/core/`); ver [repository map](repository-map.md) §33. |
| Compatible con la versión legacy en simultáneo | §18 de AGENTS exige exclusividad runtime; ver [sync and cloud](sync-and-cloud.md). |

## Core invariants

- **P1 fidelidad al legacy**: cada capacidad del Access se conserva o se reemplaza por un equivalente documentado en [decisiones-proyecto](../architecture/decisiones-proyecto.md). Una brecha descubierta se abre como `type:bug gap:legacy`.
- **Capas no se cruzan**: una route nunca ejecuta SQL directamente (AGENTS §1); un adapter de slice no alcanza InsForge por debajo del `InsForgeClient` (§31, §33.4).
- **Hexagonal como target**: el layout bajo `app/core/` cumple el contrato de §33.3; los `service.py` planos en `app/modules/` son deuda en conversión, no patrón a imitar.
- **Pre-MVP single-branch**: todo va a `main` directamente (AGENTS §15.1–§15.3); staging se reactiva solo por declaración explícita del usuario (§15.4).
- **Docs reflejan código**: si divergen, gana el código y la doc se actualiza en la misma sesión (P3 en [proceso.md](../proceso.md)).

## Contributor checklist

- [ ] Antes de añadir una capacidad nueva, confirme que no rompe P1 — la capacidad existe en el Access o está en el roadmap como aditiva.
- [ ] Antes de saltarse una capa (route con SQL directo, application con `InsForgeClient`), cite la regla que lo prohíbe en el PR.
- [ ] Antes de mover código a `app/core/`, aplique el criterio de §33.2: dos o más consumidores y ninguna razón de negocio propia para cambiar.
- [ ] Antes de declarar una divergencia con el legacy, regístrela en [decisiones-proyecto](../architecture/decisiones-proyecto.md) en la misma sesión.

## Navigation

Previous: [Codebase Guide](../CODEBASE-GUIDE.md) | Next: [Repository map](repository-map.md)