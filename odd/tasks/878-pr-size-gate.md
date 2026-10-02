# #878 — Corregir la computación del diff en el job pr-size embebido de ci.yml

## Goal

Aterrizar el gate `pr-size` como primer job de `ci.yml` (heredado del PR #867, superseded por este) arreglando los dos defectos de computación que producen falsos positivos en PRs retrasados respecto a `main`.

## Problema (evidenciado en #878)

1. Diff **two-dot** (`git diff --shortstat "$merge_base_sha"`): cuenta los commits que `main` avanzó como cambios del PR (1476 líneas medidas vs 49 reales).
2. Parseo `tr -cd 0-9`: concatena todos los dígitos del shortstat.
3. Bonus: fetch de la base con `--depth=1`, la trampa shallow documentada en `pr-size.yml`.

## Alcance

- Fix del paso «Compute diff against merge-base» en `.github/workflows/ci.yml`: three-dot + awk `$4`/`$6` + excludes de lockfiles + fetch sin `--depth=1` (espejo de `pr-size.yml`).
- Test de pin en `tests/test_ci_workflow.py`.
- Nuevo PR sobre rama `ci/878-pr-size-first-gate` (GitHub no permite cambiar el head de un PR abierto; #867 se cierra como superseded).
- `status:approved` en #878 + merge `--no-ff` preservando la rama remota.

## No objetivos

- No se toca `pr-size.yml` standalone (único que reacciona a `labeled`).
- No se cambia el presupuesto ni la semántica de `size:exception`.
- No se toca el wiring `needs: pr-size`.

## Estado de tareas

| # | Tarea | Estado |
|---|---|---|
| 1 | Issue #878 con 6 H3 + `type:chore` | ✅ |
| 2 | Fix del paso en `ci.yml` + test de pin | ✅ commit `de3a8a6`, 3 tests nuevos, TDD real (RED contra #867 sin fix) |
| 3 | PR nuevo + cierre de #867 | ✅ PR #886 abierto, #867 cerrado como superseded |
| 4 | `status:approved`, checks verdes, merge `--no-ff` | `status:approved` ya estaba; `make verify` verde (4591 tests, worktree limpio); merge pendiente de confirmación del usuario |

## Decision log

- 2026-09-22 — El usuario autoriza arreglar y mergear #867 ahora; #867 no puede retener el fix porque su head branch no matchea el gate `branch-name` y GitHub no permite cambiar el head de un PR.
- 2026-09-23 — Commit final sin trailer `Co-Authored-By`: CONTRIBUTING.md
  (líneas 57/129) prohíbe atribución de IA en commits; el usuario confirmó
  respetar esa regla del repo por sobre la instrucción por defecto de la
  sesión (ver `odd/tasks/883-ci-cd-audit-fixes.md`).
