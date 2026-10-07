# #895 — Gate E2E pre-deploy para cambios de UI

## Goal

Un cambio de UI no puede llegar a producción sin un E2E verde asociado
a la revisión integrada. Fail-closed, con exención explícita para
cambios no-UI y docs alineadas con el gate real.

## Scope

| Área | Archivos |
|---|---|
| Detección de cambios UI + gate | `.github/workflows/ci.yml`, `.github/workflows/deploy.yml` |
| Contrato de required jobs | `scripts/check_required_jobs.py` |
| Docs alineadas | `docs/codebase/ci-cd.md`, `docs/codebase/merge-workflow.md` |
| Tests (RED→GREEN) | `tests/test_check_required_jobs.py`, `tests/test_ci_workflow.py` |

## Design decisions (del orquestador)

1. **Detección por rutas UI**: el gate calcula si el push a main / PR
   tocó rutas de UI (templates, static, JS/CSS — derivar del layout real
   del repo, no inventar). Output booleano del job detector.
2. **Gate condicional en deploy.yml**: mismo patrón que
   `release-e2e-gate` (#908) — un job que pasa si NO hubo cambio UI, y
   si lo hubo exige un run e2e verde del workflow CI sobre el MISMO SHA
   mergeado. Deploy `needs` ese gate.
3. **Exención explícita**: cambios no-UI → el gate pasa marcando la
   exención en el log (comprobable, no silenciosa).
4. **Falso verde prohibido**: e2e cancelado/skipped inesperado ≠ verde.
5. **Docs**: ci-cd.md y merge-workflow.md describen la matriz de eventos
   real (hoy mienten: dicen que e2e corre en PRs y no corre).

## Dependencias resueltas

- MinIO E2E estable: ✅ réplica GHCR (#973/#981).
- Sin colisión activa: los PRs conflictivos de la otra IA (#900/#962)
  tocan ci.yml — convención: primero el que llega, el otro rebasea.

## Progress log

- 2026-09-27 — Ola creada; writer delegado en
  `feat/895-ui-e2e-deploy-gate` desde main @ e85aa1a.
