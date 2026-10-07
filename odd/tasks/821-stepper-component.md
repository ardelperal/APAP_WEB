# Feature: #821 — Reusable stepper component (vanilla-JS + Tailwind)

Issue: https://github.com/ardelperal/APAP_WEB/issues/821 (epic #817, wizard chain 821→822→823→824).
Branch: `feat/821-stepper-component` in worktree `/home/ubuntu/repos/apap-app-worktrees/821-stepper-component`.

## Scope

Component + preview page ONLY. No production form is converted (that is #823/#824).

## Work units

- [x] WU-1 Explore: routes registry, Settings flag pattern, Tailwind v4 build (`make css`), e2e test conventions (done 2026-09-24).
- [x] WU-2 TDD writer: e2e tests RED → implementation GREEN (delegado a gentle-ai-worker; 2 rondas: feature + fixes de gates).
- [x] WU-3 Gates: `make verify` completo verde (lint, typecheck, check-rules, complexity, ruff-ratchet, slice-completeness, layers, import-cycles, jscpd, alantyle, workflows, issue-specs, docstring-*, vulture, mutation-sites, check-crap/test-ci 4612 passed). E2E en vivo: 5 passed (postgres efímero + uvicorn :8210).
- [x] WU-4 Work-unit commits (en feat/821-stepper-component):
  - 5bfe170 feat(devtools): developer-only stepper preview page (229+)
  - 68e33d5 feat(ui): reusable vanilla-JS form stepper component (252+/1-)
  - 0d73561 test(e2e): stepper component browser coverage (201+)

## Budget note

Total diff 682 líneas > presupuesto 400. Escape order aplicado: 3 work-unit commits separables en chained PRs (229 / 252 / 201). Pendiente: decisión del usuario sobre push + PRs encadenadas.

## Gate fixes (ronda 2)

- create_app CC=2>1 → helper module-level `_include_devtools_router`.
- ARG001 ratchet → parámetro `request` sin uso eliminado del POST handler.
- check-slice-completeness → router movido de app/modules/devtools a app/core/devtools (infrastructure, sin ceremonia hexagonal; precedente magic_link).
- test_template_migration (extends literal) + test_xss_audit (TEMPLATE_SPECS) → template usa `{% extends base_template %}` y se registró en el audit.
