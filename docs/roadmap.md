[← Back to Codebase Guide](CODEBASE-GUIDE.md)

# Hoja de ruta viva — APAP_WEB

Esta página es el hub del roadmap. Codifica las fases del producto (Fase 0 a Fase 7) y las capacidades transversales; cada fase y cada transversal vive en una página radial propia. Se mantiene viva en cada ciclo de entrega (no es una tarea aparte).

## What is the roadmap

Es el índice navegable de las fases de APAP_WEB y de las capacidades transversales (migración en vivo, UX/UI, motor de tareas, observabilidad, dev workflow). El roadmap refleja el código: si diverge, gana el código y este índice se actualiza en la misma sesión ([proceso.md](proceso.md) §0 P3).

## How to read it

Estructura hub-and-spoke. Esta página es el hub; las páginas radiales viven en [`docs/roadmap/fase-*.md`](roadmap/) y en [`docs/roadmap/transversales.md`](roadmap/transversales.md). Para cada fase: abra su página, lea el estado y las issues, siga las decisiones enlazadas antes de tocar código. El orden numérico no es temporal estricto: las sub-fases 5a–5d, 6a–6c y 7a–7c se ejecutan en paralelo cuando no hay dependencias.

## Roadmap at a glance

| Phase | Status | Lead | Page |
|---|---|---|---|
| Fase 0 — Infraestructura y CI/CD | cerrado | aroman | [fase-0-infra-cicd.md](roadmap/fase-0-infra-cicd.md) |
| Fase 1 — Esqueleto de la aplicación web | cerrado (#17) | aroman | [fase-1-esqueleto.md](roadmap/fase-1-esqueleto.md) |
| Fase 2 — Autenticación y autorización | cerrado (#16) | aroman | [fase-2-auth-allowlist.md](roadmap/fase-2-auth-allowlist.md) |
| Fase 3 — Modelo de dominio limpio | cerrado | aroman | [fase-3-modelo-dominio.md](roadmap/fase-3-modelo-dominio.md) |
| Fase 4 — Entidad Animal (Feature 01) | cerrado | aroman | [fase-4-animal-crud.md](roadmap/fase-4-animal-crud.md) |
| Fase 5 — Voluntarios + Entradas + Acogidas + Adopciones (Feature 02) | cerrado | aroman | [fase-5-flujos-operativos.md](roadmap/fase-5-flujos-operativos.md) |
| Fase 6 — Salud, Terapias e Inventario de Material (Feature 03) | pendiente | aroman | [fase-6-salud-terapias-material.md](roadmap/fase-6-salud-terapias-material.md) |
| Fase 7 — Documentos, Contratos, Informes y Consultas (Feature 04) | pendiente | aroman | [fase-7-documentos-contratos-informes.md](roadmap/fase-7-documentos-contratos-informes.md) |

## Cross-cutting concerns

Las capacidades que cruzan varias fases viven en [`transversales.md`](roadmap/transversales.md) bajo cuatro ejes.

| Concern | Page section |
|---|---|
| Seguridad, CSRF, RBAC, redacción de PII | [transversales.md § Seguridad](roadmap/transversales.md) |
| Logging estructurado, traza canónica, panel de control | [transversales.md § Observabilidad](roadmap/transversales.md) |
| Cobertura, linter, mypy, E2E, ratchets | [transversales.md § Calidad](roadmap/transversales.md) |
| Migración en vivo, UX/UI, motor de tareas, idioma y docs | [transversales.md § Dev workflow](roadmap/transversales.md) |

## Recent activity

Últimos cinco merges a `main`. El comando `git log --oneline -10` es autoritativo.

| SHA | Title | PR |
|---|---|---|
| 57b2d18 | test(e2e): Fase 6 E2E battery batch 1 (21 tests) | #629 |
| 031e4a6 | feat(cesiones): hexagonal migration + E2E battery (12 tests) | #628 |
| af04f4b | docs(roadmap): update recent activity after PR #628 | — |
| 6bee0ab | docs(roadmap): close Fase 4 (hexagonal animals completed) | — |
| f529b8f | docs(roadmap): close Fase 3 and Fase 5; update recent activity after PR #627 | — |

## Cuándo ir al legacy directamente

Regla de uso de la documentación generada frente al Access (P2, [proceso.md](proceso.md) §0):

1. Si [`docs/discovery/feature-XX-*.md`](discovery/) cubre la pregunta, lea primero el discovery. Es la versión revisada y consolidada.
2. Si el discovery no entra en detalle suficiente y existe un `docs/legacy-<área>.md` específico, lea el legacy documentado.
3. Solo vaya al Access directamente (vía Dysflow MCP, `projectId: apap`) si la pregunta no está cubierta en discovery ni en `legacy-*`, si hay que validar un dato concreto del schema o si aparece una incoherencia que requiere inspección de los formularios VBA.
4. Cualquier descubrimiento nuevo del Access se documenta como `docs/legacy-<área>.md` antes de cerrar la tarea, no como nota efímera.

Solo se permiten los skills `dysflow`, `vba-access` y `access-vba-tdd`; los demás skills de Access están excluidos ([d-31-resolucion-dudas-dominio.md](architecture/decisiones/d-31-resolucion-dudas-dominio.md)).

## Convenciones del proyecto

| Tema | Convención |
|---|---|
| Idioma de issues, PRs y docs de producto | Castellano (España), usted. |
| Idioma de artefactos técnicos | Inglés por defecto (código, comentarios, docstrings). |
| Mantenedor | aroman (autoaprueba issues y PRs). |
| Rama objetivo | pre-MVP single-branch — todo a `main` ([d-30-pre-mvp-single-branch.md](architecture/decisiones/d-30-pre-mvp-single-branch.md)). |
| Convención de commits | Conventional Commits ([d-34-conventional-commits.md](architecture/decisiones/d-34-conventional-commits.md)). |
| Labels de PR | Uno de `type:bug` / `type:feature` / `type:docs` / `type:refactor` / `type:chore` / `type:breaking-change`. |
| TDD | Estricto: tests antes de código ([d-33-tdd-estricto.md](architecture/decisiones/d-33-tdd-estricto.md)). |
| Skill frontend | `frontend-design` en cualquier issue de UI/UX. |
| Presupuesto de revisión | 400 líneas por PR ([d-35-presupuesto-400-lineas-pr.md](architecture/decisiones/d-35-presupuesto-400-lineas-pr.md)). |
| Cadena de PRs | `force-chained`; base `main` (pre-MVP). |
| Fidelidad al legacy | [d-05-fidelidad-legacy-superset.md](architecture/decisiones/d-05-fidelidad-legacy-superset.md) (P1): superset funcional del Access; gap = `type:bug gap:legacy`. |

## Cómo mantener este documento

Regla base: este roadmap se actualiza como efecto directo de cualquier acción que afecte a su contenido. No es una tarea aparte, se hace en el mismo flujo. Si abre o cierra una issue, cambie el estado de una fase, o añada documentación, actualice la página radial correspondiente en la misma sesión.

## Contributor checklist

- [ ] Si abre una issue, añada fila a la fase correspondiente y retire de "pendientes de crear" si estaba.
- [ ] Si cierra una issue, actualice la página radial con SHA + PR.
- [ ] Si cambia el estado de una fase (pendiente → en curso → cerrado), refleje el cambio aquí y en su página radial.
- [ ] Si descubre una referencia rota en una página radial, márquela como **ROTA** y abra issue `type:docs`.
- [ ] No duplique contenido entre esta página y las páginas radiales: esta solo enlaza y resume, las radiales contienen.

## Navigation

Back: [Codebase Guide](CODEBASE-GUIDE.md) | Next: [fase-0-infra-cicd.md](roadmap/fase-0-infra-cicd.md)
