[← Back to roadmap hub](../roadmap.md)

# Fase 1 — Esqueleto de la aplicación web

Esta página posee el estado de la Fase 1: `app/` mínimo con FastAPI + Jinja2 + Tailwind compilando, sin reglas de negocio todavía. Fase cerrada.

## Estado

cerrado — Issue **#17** mergeada en `main` como `d0b1ed1`. Desbloquea Fase 2 (#16) y Fase 3.

## Slices

| Slice | Estado | Issue | SHA |
|---|---|---|---|
| Esqueleto FastAPI + Jinja2 + Tailwind | cerrado | #17 | `d0b1ed1` |

## Decisiones relacionadas

- [d-20-stack-fastapi-htmx-local_backend.md](../architecture/decisiones/d-20-stack-fastapi-htmx-local_backend.md) — stack base.
- [d-30-pre-mvp-single-branch.md](../architecture/decisiones/d-30-pre-mvp-single-branch.md) — flujo pre-MVP.
- [d-33-tdd-estricto.md](../architecture/decisiones/d-33-tdd-estricto.md) — tests antes de código.

## Documentación de referencia

- [docs/architecture/capas-y-slices.md](../architecture/capas-y-slices.md) — reglas de capas y slices.
- [docs/codebase/architecture.md](../codebase/architecture.md) — modo exclusivo web/legacy y hexagonal.

## Core invariants

- **`app/` arranca mínimo**: FastAPI + middlewares (UA, CSRF, auth) + Jinja2 + Tailwind. Sin reglas de negocio ni entidades de dominio en esta fase.
- **Desbloquea Fase 2 y Fase 3**: nada de auth ni modelo de dominio se cierra hasta que el esqueleto compile.

## Contributor checklist

- [ ] Si reabre la Fase 1 para rehacer el esqueleto, cite el motivo en el PR y abra un ADR si la decisión afecta al stack.
- [ ] Si añade una dependencia al esqueleto, valídela con `context7` antes de pinear (D-8).
- [ ] No mueva lógica de Fase 2 (auth) o Fase 3 (modelo) a esta página: cada fase vive en su radial.

## Navigation

Previous: [fase-0-infra-cicd.md](fase-0-infra-cicd.md) | Next: [fase-2-auth-allowlist.md](fase-2-auth-allowlist.md)
