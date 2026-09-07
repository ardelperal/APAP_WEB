[← Back to README](../README.md)

# APAP_WEB Codebase Guide

**Este hub es la primera parada para quien aterriza en el repositorio. Posee la forma del proyecto, el contrato de lectura y los enlaces a las páginas radiales. No repite reglas operativas — esas viven en [AGENTS.md](../AGENTS.md) — ni el detalle de los paquetes — eso es [repository map](codebase/repository-map.md).**

## Who this is for

| Reader | Use this guide to |
|---|---|
| Mantenedor que va a abrir un PR | Localizar el paquete que posee el comportamiento que va a tocar y verificar qué guardarraíles se aplican. |
| Revisor que valida un slice | Confirmar el contrato de capas, el ratchet de tamaño y el lineage antes de aprobar. |
| IAgente que arranca una sesión | Cargar el contexto del eje que va a tocar antes de leer código o specs. |
| Onboarding de un contribuidor nuevo | Entender en treinta segundos qué es APAP_WEB y dónde vive cada responsabilidad. |

## 90-second mental model

```text
                    browser (HTML + Tailwind v4)
                              │  cookie firmada, SameSite=Strict
                              ▼
        FastAPI / Uvicorn  —  middlewares (UA, CSRF, auth)
                              │
              ┌───────────────┴────────────────┐
              ▼                                ▼
    LEGACY SLICE                       HEXAGONAL SLICE
    app/modules/<area>/                §33.2 — dos rutas posibles:
              │                        ┌────────────────────────┐
    routes.py  │ HTTP only            │                        │
         │     ▼                  app/core/<layer>/<slice>/   app/modules/<slice>/
    service.py  validación + dominio │   (transversal)       │   (negocio con razón propia)
         │     ▼                    │                        │
    queries.py  construcción de SQL   │   routes / handlers   │   routes.py
              │                       │   application/         │   domain/
              │                       │   ports/  Protocol     │   ports/
              │                       │   adapters/local-backend/   │   application/
              │                       │                        │   adapters/local-backend/
              │                       └────────────────────────┘
              │                                │
              └───────────────┬────────────────┘
                              ▼
              app/core/local_backend.py  (LocalBackendClient)
                              ▼
              LocalBackend  —  PostgreSQL · Auth · Storage
```

> **Todo request entra por una route delgada, cruza exactamente una capa de dominio y sale por un único cliente hacia LocalBackend; lo que rompe esa línea recta es lo que los gates rechazan.**
>
> La hexagonal puede vivir dentro del propio módulo (`app/modules/animals/`, regla §33.2) cuando el slice tiene razón de negocio propia; sólo se promueve a `app/core/<layer>/<slice>/` cuando dos o más consumidores lo comparten. La transición actual es in-place capa por capa, no extracción masiva.

## Guide pages

| Page | Job |
|---|---|
| [Mental model](codebase/mental-model.md) | Qué es APAP_WEB, qué no es y qué invariantes conserva. |
| [Repository map](codebase/repository-map.md) | Qué paquete posee cada responsabilidad y dónde colocar código nuevo. |
| [Interfaces](codebase/interfaces.md) | Qué superficies expone el sistema (HTTP, OAuth, storage) y por dónde fluye cada una. |
| [Integrations](codebase/integrations.md) | Adaptadores externos (LocalBackend, CodeGraph, Dysflow, Coolify, GitHub) y sus límites de configuración. |
| [Maintainer playbook](codebase/maintainer-playbook.md) | Workflow operativo de mantenedor y checklists por tipo de cambio. |
| [Sync and cloud](codebase/sync-and-cloud.md) | Web ↔ legacy, mode toggle y CLI de reconciliación. |
| [Reference map](codebase/reference-map.md) | Trazabilidad entre docs, specs y código. |
| [Missing sources](codebase/missing-sources.md) | Subsistemas que el lector podría esperar y no existen. | <!-- alantyle-ignore:ALAN004 -->

## Recommended reading path

1. [Mental model](codebase/mental-model.md) — primero.
2. [Repository map](codebase/repository-map.md) — antes de crear o mover código.
3. [Interfaces](codebase/interfaces.md) — antes de añadir una ruta o endpoint.
4. [Maintainer playbook](codebase/maintainer-playbook.md) — antes de abrir un PR.
5. [Reference map](codebase/reference-map.md) — para trazabilidad cuando una decisión toca varias docs.

## Quick map inverso

| Si necesita... | Abra primero | Y luego consulte |
|---|---|---|
| Entender el producto y el target | [README](../README.md) | [Mental model](codebase/mental-model.md), [Arquitectura LocalBackend](architecture/architecture-local-backend-stack.md) |
| Decidir dónde va código nuevo | [Repository map](codebase/repository-map.md) | [AGENTS.md](../AGENTS.md) §33 |
| Añadir o cambiar una ruta o endpoint | [Interfaces](codebase/interfaces.md) | El `routes.py` del módulo afectado, [AGENTS.md](../AGENTS.md) §28 |
| Localizar un guardarraíl o un detector | [Repository map](codebase/repository-map.md) | [AGENTS.md](../AGENTS.md) §20–§28, [Quality roadmap](quality/hardening-roadmap.md) |
| Tomar una issue de `open` a `closed` | [Maintainer playbook](codebase/maintainer-playbook.md) | [`docs/proceso.md`](proceso.md), [AGENTS.md](../AGENTS.md) §16 |
| Mover datos entre web y legacy | [Sync and cloud](codebase/sync-and-cloud.md) | [AGENTS.md](../AGENTS.md) §18, [`migration/cli.py`](../../migration/cli.py) |
| Localizar un runbook de operador | [`docs/runbooks/`](runbooks/) | [AGENTS.md](../AGENTS.md) §13 |
| Localizar una auditoría de un slice sensible | [`docs/audits/`](audits/) | [AGENTS.md](../AGENTS.md) §12 |

## Existing references

| Reference | Path | Purpose |
|---|---|---|
| Producto, stack, quick start | [`README.md`](../README.md) | Punto de entrada para quien abre el repo. |
| Reglas y guardarraíles del proyecto | [`AGENTS.md`](../AGENTS.md) | Las 33 reglas y sus detectores. |
| Contrato de stack LocalBackend | [`docs/architecture/architecture-local-backend-stack.md`](architecture/architecture-local-backend-stack.md) | Decisiones de stack, reglas LocalBackend, target de despliegue. |
| Playbook operativo por issue | [`docs/proceso.md`](proceso.md) | De `open` a `closed` con evidencia, según §16 de AGENTS. |
| Roadmap de fases | [`docs/roadmap.md`](roadmap.md) | Fases del producto y estado actual. |
| Decisiones de proyecto | [`docs/architecture/decisiones-proyecto.md`](architecture/decisiones-proyecto.md) | Registro formal de divergencias con el legacy. |
| Auditorías | [`docs/audits/`](audits/) | Un documento por slice sensible. |
| Runbooks | [`docs/runbooks/`](runbooks/) | Procedimientos que exigen acción del operador. |
| Hardening del arnés de calidad | [`docs/quality/hardening-roadmap.md`](quality/hardening-roadmap.md) | Estado de los gates automáticos. |
| Especificaciones delta | [`openspec/specs/`](../openspec/specs/) | Specs formales por capacidad. |
| Cambios en curso | [`openspec/changes/`](../openspec/changes/) | Propuestas SDD activas y archivadas. |

## Next step

Continúe con [Mental model](codebase/mental-model.md).

---

## Contributor checklist

- [ ] Castellano peninsular formal, usted, sin regionalismos.
- [ ] Un único H1; secciones en H2 y subsecciones en H3, sin H4.
- [ ] Diagrama del mental model en bloque `text`, por debajo de treinta líneas.
- [ ] Ningún párrafo supera los doscientos caracteres.
- [ ] Sin emojis decorativos ni marketing fluff.
- [ ] Cada cross-reference resuelve a un archivo existente del repositorio.
- [ ] Sin duplicación de contenido que ya vive en `README.md`, `architecture/architecture-local-backend-stack.md` o `AGENTS.md`.

## Navigation

Back: [README](../README.md) | Next: [Mental model](codebase/mental-model.md)