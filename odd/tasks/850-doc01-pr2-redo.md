# #850 — DOC-01 PR 2 redo: PDF generator + storage adapter

## Goal

Rework desde cero del DOC-01 PR 2 (el PR #795/#849 falló CI: API keys
reales en tests, uv.lock desactualizado, 1734 líneas de diff). Slice
hexagonal en 4 chained PRs ≤400 líneas cada uno, según el plan del issue.

## Scope (chained PRs)

| CP | Contenido | Branch | Estado |
|---|---|---|---|
| 1 | Ports (`ContratosPdfPort`, `ContratosStoragePort`) + VO `ContratoPdf` + tests | `feat/850-doc01-cp1-ports` | 🔄 en vuelo |
| 2 | Use case `render_to_pdf.py` + tests | (siguiente) | ⏳ |
| 3 | PDF LocalBackend adapter (reportlab) + tests | (siguiente) | ⏳ |
| 4 | Storage LocalBackend adapter (S3-compatible) + tests gitleaks-safe | (siguiente) | ⏳ |

## Constraints

- Fixtures gitleaks-safe (`"test-key-fixture"`, `"x" * 40` — nunca keys
  con forma de credencial). Validar con `gitleaks dir . --no-banner`.
- Pin arquitectónico §33.4: domain/ports libres de psycopg, SqlExecutor,
  LocalBackend, reportlab.
- `uv.lock` regenerado con reportlab==4.5.1 + types-reportlab.
- Cada PR ≤400 líneas; merge secuencial (el writer no pushea — el
  orquestador secuencia push/PR/merge y continua el writer por unidad).
- Out of scope: DOC-02/03/04, route handler (PR 3), E2E (PR 4).
- La otra IA activa en su ola — superficies disjuntas (app/modules/contratos/).

## Progress log

- 2026-09-28 — Carril tomado (nadie lo trabajaba); worktree
  850-doc01-pr2 creado desde ab66117; writer CP1 delegado.
