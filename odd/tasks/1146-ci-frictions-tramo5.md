# #1146 — Fricciones de CI del Tramo 5: dispositions por ítem

## Goal

Aterrizar la checklist de 6 fricciones de la entrega 2026-09-29 (#1081/#1073)
respetando el presupuesto de 400 líneas por PR: lo pequeño y documental en un
PR (`chore/1146-ci-frictions-wave`), el target `e2e-local` como segundo tramo,
y lo que exige una decisión humana (coste/capacidad) como issue de seguimiento.

## Dispositions

| # | Fricción | Disposition | Dónde |
|---|---|---|---|
| 1 | Echo engañoso del preflight Docker (`ci.yml`, jobs `security` y `security-deep`) | **Implementado** | `.github/workflows/ci.yml` |
| 2 | `issue-spec` no se re-ejecuta al etiquetar | **Documentado** | `CONTRIBUTING.md` §PR encadenados |
| 3 | Hosted `ubuntu-24.04` (23×, 13 en `ci.yml`) vs flota self-hosted ociosa (4 runners; solo `deploy.yml:296` la usa) | **Follow-up issue** (decisión coste/capacidad del operador) | issue de seguimiento `type:chore` |
| 4 | Vulture BASELINE estático vs slices aditivos | **Documentado** (docs-only; el patrón `--update-baseline` de #1166/#1167 ya resolvió el flujo para ruff) | `scripts/check_vulture_guard.py` |
| 5 | `e2e` no reproducible en local (Makefile sin target, MinIO privado de GHCR) | **Implementado** (tramo 2: `make e2e-local`) | `Makefile` |
| 6 | Fakes de `SqlExecutor` sin validación de tipos | **Documentado + follow-up issue** | `tests/sql_executor_fake.py` |

## Design decisions

1. **Echo engañoso (#1130):** la causa de la cadena de misdiagnóstico fue que
   el runner ecoea el script completo del paso como cabecera de step, de modo
   que la frase literal `::error::Docker daemon is not answering...` aparece
   en el log aunque el preflight pase (grep la encuentra en la cabecera
   `[36;1m`, no como error emitido). El fix separa el mensaje de fallo en
   `env:` (jamás ecoeado como cabecera) y deja como único literal del script
   un `::notice::` informativo. El paso que falla sigue errorando con la
   razón real (`docker info` timeout/error, cap 30s).
2. **Reetiquetado (`chain:partial`):** documentado en `CONTRIBUTING.md` en vez
   de un workflow nuevo `types: [..., labeled]`: el caso es raro (funcionó en
   #1169 vía reopen), y el trigger dedicado pagaría una corrida completa de CI
   por etiqueta. La opción queda anotada en #1146 como seguimiento.
3. **Vulture (ítem 4):** docs-only honesto. Este guard NO tiene flag
   `--update-baseline` (solo lo tiene `check_ruff_ratchet.py`, #1120); lo
   documentado es el patrón equivalente amend-up/ratchet-back para cadenas
   apiladas: subir BASELINE en el commit del slice con rationale explícita y
   ratchetar hacia abajo en el commit consumidor. La fila del inventario de
   gates (`docs/quality/ci-gate-inventory.md`) queda fuera de la superficie
   autorizada de este tramo: pendiente para un tramo docs autorizado.
4. **Fakes sin tipos (ítem 6):** la validación genérica por columna no es
   viable en el fake (el contrato del handler no lleva esquema), así que el
   docstring documenta la limitación con el ejemplo real (`anadido_por`,
   QueryError vivido en #1138) y exige cobertura `tests/integration/` cuando
   la corrección dependa de tipos aplicados por la base.

## Progress log

- 2026-10-01: tramo 1 implementado (ítems 1, 2, 4, 6 + dispositions 3/6 en
  issues de seguimiento); validación local verde.
