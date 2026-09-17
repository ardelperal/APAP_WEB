# DOC-01 #56 — Contratos PDF (Fase 7a)

## Goal

Generación de PDF de contratos desde plantilla, con sustitución de placeholders y condicionales, sobre `LocalPostgresExecutor`. Cubre los ocho tipos de contrato del legacy (`Entrada`, `Acogida`, `Acogida Judicial`, `Adopcion`, `PreAdopcion`, `Cesion`, `Reserva`, `Entrega`).

Issue viva: #56.
Sub-issue futuras: DOC-02 #57 (signed-upload), DOC-03 #58 (anexos polimórficos), DOC-04 #59 (object storage).

## Scope (este slice = PR 1)

- `app/modules/contratos/domain/` — `Plantilla`, `TipoContrato` (los 8 tipos), `SolicitudContrato`, validación de gramática.
- `app/modules/contratos/application/` — use case `render_contrato` puro (texto plano, sin PDF).
- `app/modules/contratos/ports/` — `PlantillaRepository` Protocol (PR 2 lo llenará).
- Tests: `test_contratos_template_engine.py`, `test_contratos_template_engine_extras.py`, `test_slice_contratos_architecture.py`.
- Pin arquitectónico (rule §33.4): domain y ports libres de `psycopg`, `SqlExecutor`, `LocalBackend`, `weasyprint`, `reportlab`.

## Out of scope (PR 2 / 3)

- PR 2: storage adapter (`adapters/local_backend/`) para el draft PDF en object storage + `PlantillaRepository` adapter concreto.
- PR 3: route handler + form post + DI wiring.
- PR 4: integración E2E con Playwright.

## Work-unit commits planeados

| WU | Descripción | Estado |
|---|---|---|
| WU-1 | Template engine puro (este slice) | en curso |
| WU-2 | Storage adapter + object storage | pendiente |
| WU-3 | Route handler + DI wiring | pendiente |
| WU-4 | Batería E2E (`test_contratos_pdf.py`, `test_contratos_auth.py`) | pendiente |

## Gates (CI required check, pre-MVP single-branch)

- pytest verde en el slice (681 líneas de tests).
- ruff clean.
- mypy zero errores.
- check_import_cycles verde (no introducir ciclos vía `app/modules/contratos/`).
- check_module_size verde (cada archivo ≤ 700 líneas, cada handler ≤ 50 líneas).
- check_route_size verde.
- Pin arquitectónico verde (test_slice_contratos_architecture.py).

## Legacy fidelity (P1)

`docs/legacy-signed-contract-flow.md` reglas no negociables:

1. Conservar borrador en `ParaFirma` como referencia.
2. PDF obligatorio, Word opcional.
3. Un único contrato por tipo por entidad (`TbContratosAnexos` §5).
4. Reemplazo con confirmación.
5. Eliminación solo de `Firmados`, nunca de `ParaFirma`.

El template engine cubre la fase 1 (generación) del legacy. PR 2 cubre la fase 2 (anexado / subida de firmado).

## Estrategia de implementación

Retomar el wip serio preexistente en `feat-56-contratos-template-engine-remote` (commit `434848a`). Cherry-pick a main desde un worktree limpio, validar gates, RDD review, merge fast-forward. Branch de revert (`revert/contratos-template-engine`) se borra por housekeeping.

## Riesgos identificados

1. **Pin arquitectónico desactualizado**: la lista `DISALLOWED_IN_DOMAIN_AND_PORTS` puede no cubrir el corte post-InsForge (`LocalPostgresExecutor`, `SqlExecutor`). Auditar antes del merge.
2. **CRAP-grade A**: el wip ya tiene `render_tokenize` y `render_condition` separados. El refactor CRAP-grade está aplicado en `434848a`. La historia `revert/contratos-template-engine` con 5 alternados Reapply/Revert es ruido sin substance.
3. **Sin Co-Authored-By**: el commit `434848a` mantiene la convención (verificado en el header). Mantener en commits de ajuste.

## Criterios de cierre del slice

- [ ] Cherry-pick `434848a` mergeado a main con SHA fresco (sin Co-Authored-By).
- [ ] RDD review aprobado (acknowledge-approved burned).
- [ ] Gates verdes en CI.
- [ ] `docs/roadmap/fase-7-documentos-contratos-informes.md` actualizado con SHA + PR.
- [ ] Worktree + branches wip cerradas.
- [ ] Memoria de sesión guardada.