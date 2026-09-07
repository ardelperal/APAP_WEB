# Reference map

[Back to Codebase Guide](../CODEBASE-GUIDE.md)

Esta página posee la trazabilidad entre docs operativas, specs OpenSpec y código. Sirve para responder «¿dónde se documenta X?» y «¿qué código cubre el doc Y?». No posee reglas del proyecto — esas viven en [AGENTS.md](../../AGENTS.md) — ni la forma de los documentos — eso es la skill [documentation-alan-style](../../../../../../.config/opencode/skills/documentation-alan-style/SKILL.md).

## Core invariants

- **Single source of truth por concepto**: una regla vive en `AGENTS.md`, un contrato de stack en [Arquitectura LocalBackend](../architecture/architecture-local-backend-stack.md), un playbook operativo en [proceso.md](../proceso.md); las radiales referencian, no duplican.
- **P3 docs reflejan código**: si divergen, gana el código y la doc se actualiza en la misma sesión ([proceso.md](../proceso.md)).
- **Trazabilidad por SHA**: cada cierre de issue cita commit SHA y path de test (AGENTS §16).
- **Decisiones registradas**: las divergencias con el legacy van en [decisiones-proyecto](../architecture/decisiones-proyecto.md) con fecha, autor y motivo.

## Docs ↔ reglas ↔ código

| Doc | Source of truth | Spec | Status |
|---|---|---|---|
| [README](../../README.md) | Producto, stack, quick start, anclas de seguridad | — | Vive, anchor de los consumidores externos |
| [AGENTS.md](../../AGENTS.md) | 33 reglas del proyecto, enforcement por detector o ratchet | — | Vive, contract de todo agente |
| [`docs/CODEBASE-GUIDE.md`](../CODEBASE-GUIDE.md) | Hub: forma del proyecto y contrato de lectura | — | Refactorizado a hub en #553 |
| [Mental model](mental-model.md) | Definición de qué es APAP_WEB y qué invariantes conserva | — | Nuevo en #553 |
| [Repository map](repository-map.md) | Ownership por paquete y decisión §33.2 | — | Nuevo en #553 |
| [Interfaces](interfaces.md) | Catálogo de superficies (HTTP, OAuth, storage, MCP) | — | Nuevo en #553 |
| [Integrations](integrations.md) | LocalBackend, CodeGraph, Dysflow, Coolify, GitHub | — | Nuevo en #553 |
| [Maintainer playbook](maintainer-playbook.md) | Workflow por issue y checklists por tipo | — | Nuevo en #553 |
| [Sync and cloud](sync-and-cloud.md) | Aislamiento web ↔ legacy y reconcile CLI | AGENTS §18 | Nuevo en #553 |
| [Missing sources](missing-sources.md) | Subsistemas esperados que no existen | — | Nuevo en #553 |
| [Arquitectura LocalBackend](../architecture/architecture-local-backend-stack.md) | Composición y límites actuales de datos, auth, storage y migración | — | Actualizado en #676 |
| [`docs/proceso.md`](../proceso.md) | Playbook operativo de una issue, open → closed | AGENTS §16 | Vive, contract de mantenedor |
| [`docs/roadmap.md`](../roadmap.md) | Fases del producto, estado actual | — | Vive, contract de scope |
| [`docs/architecture/decisiones-proyecto.md`](../architecture/decisiones-proyecto.md) | Divergencias con el legacy y motivos | P1 en [proceso.md](../proceso.md) | Vive |
| [`docs/discovery/`](../discovery/) | Decisiones de discovery por feature | P2 en [proceso.md](../proceso.md) | Vive |
| [`docs/legacy-*`](../legacy-volunteer-roles.md) | Documentación específica del legacy por área | P2 en [proceso.md](../proceso.md) | Vive |
| [`docs/audits/`](../audits/) | Un doc por slice sensible (auth, secretos, PII, etc.) | AGENTS §12 | Vive, contract de seguridad |
| [`docs/runbooks/`](../runbooks/) | Procedimientos que exigen acción del operador | AGENTS §13 | Vive, contract de operación |
| [`docs/policies/`](../policies/) | Decisiones de lint y políticas ad hoc | — | Vive |
| [`docs/quality/hardening-roadmap.md`](../quality/hardening-roadmap.md) | Estado del arnés de gates | AGENTS §20–§28 | Vive |

## OpenSpec ↔ código

| Spec | Slice afectado | Source |
|---|---|---|
| [auth-dependencies](../../openspec/specs/auth-dependencies/spec.md) | `app/core/auth*`, [`app/core/auth_dependencies.py`](../../app/core/auth_dependencies.py) | Allowlist y dependencias inyectadas |
| [intake-entries](../../openspec/specs/intake-entries/spec.md) | [`app/modules/entradas/`](../../app/modules/entradas/) | CRUD de entradas |
| [migration-discovery-docs](../../openspec/specs/migration-discovery-docs/spec.md) | [`migration/`](../../migration/), [`docs/discovery/`](../discovery/) | Sync y discovery |
| [web-only-feature-preservation](../../openspec/specs/web-only-feature-preservation/spec.md) | [`app/core/migration/`](../../app/core/migration/) | Tabla `web_only_feature_shadow` |

## Cambios SDD

Los cambios SDD activos viven en [`openspec/changes/`](../../openspec/changes/); los archivados en [`openspec/changes/archive/`](../../openspec/changes/archive/). Cada uno contiene `proposal.md`, `tasks.md` y opcionalmente `specs/<delta>/spec.md`. El state del change (open, in-progress, applied, archived) lo lleva el archivo `tasks.md`.

## Contributor checklist

- [ ] Si actualiza una regla de [AGENTS.md](../../AGENTS.md), refresque la entrada correspondiente en este radial en la misma sesión.
- [ ] Si crea o cierra una issue, cite en el comentario de cierre el SHA del commit y el path de test (AGENTS §16).
- [ ] Si abre un change SDD, agregue una entrada en la tabla «OpenSpec ↔ código» apenas el slice aterrice en `main`.
- [ ] Si descubre una divergencia con el legacy, regístrela en [decisiones-proyecto](../architecture/decisiones-proyecto.md) con fecha y motivo.
- [ ] Si una doc operativa (proceso, roadmap, audits, runbooks) cambia, refresque esta radial en la misma sesión.

## Navigation

Previous: [Sync and cloud](sync-and-cloud.md) | Next: [Missing sources](missing-sources.md)
