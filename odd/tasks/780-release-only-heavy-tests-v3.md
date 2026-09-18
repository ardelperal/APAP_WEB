# #780 — Release-only heavy tests (Fase transversal, CI gate)

## Goal

Eliminar el trigger `schedule` (cron semanal) de `.github/workflows/ci.yml`. Los jobs `mutation`, `security-deep` y `e2e` quedan reservados a `workflow_dispatch` (escape manual) y push de tag `v*` (release). La cadencia semanal automática se retira; la filosofía fail-closed del resto del pipeline exige que un fallo de mutación o de E2E no conviva con `main` más allá de un release.

Issue viva: #780 (estado actual: **OPEN**, `state_reason: "reopened"`).
Historia previa: primer PR #786 mergeó `21b3e1f` (cambios principales en `ci.yml` + `scripts/check_required_jobs.py`); la issue se reabrió porque los tests y los docs adyacentes quedaron desalineados con la nueva cadencia.

## Scope (este slice = #780 v3, follow-up al primer PR)

Cherry-pick sobre `feat/56-doc-01-pr2-pdf-storage` (que tiene la historia coherente con PR #794 + autogen ya commiteados):

1. `d11a2ad ci: reservar tests pesados para releases` — actualiza `ci.yml` (cron removido, `if:` de `mutation`/`security-deep`/`e2e` sin `schedule`), `Makefile`, `scripts/check_mutation.py`, `scripts/check_required_jobs.py`, `scripts/cosmic_ray_run_config.py`, `docs/quality/cosmic-ray.toml`, `docs/quality/hardening-roadmap.md`, `docs/codebase/ci-cd.md`, y los tests asociados.
2. `3631215 docs(ci): alinear cadencia de jobs pesados` — alinea `docs/codebase/quality-gates.md`, `docs/development.md`, `docs/roadmap/transversales.md`, `docs/runbooks/mutation-testing.md`, y `tests/test_ci_workflow.py`.

El merge commit `91e13c3 chore: merge main into correction branch` (merge de main antiguo `47072e0` hacia v2) NO se cherry-pickea: arrastra historia de un main obsoleto.

## Out of scope

- `codeql.yml` (cron independiente, no se toca).
- Otros repos / otras fases.
- Agregar nuevos tests: la cobertura de tests ya existe en los commits a cherry-pickear; este slice solo los trae al día.

## Work-unit commits planeados

| WU | Descripción | Estado |
|---|---|---|
| WU-1 | Tracking + creación de rama `ci/780-release-only-heavy-tests-v3` | en curso |
| WU-2 | Cherry-pick `d11a2ad` (ci: reservar tests pesados para releases) | pendiente |
| WU-3 | Cherry-pick `3631215` (docs(ci): alinear cadencia de jobs pesados) | pendiente |
| WU-4 | Validar `scripts/check_workflows.py` + `scripts/check_required_jobs.py` + `ruff check` + subset de pytest (los tests tocados) | pendiente |
| WU-5 | Push + PR contra `origin/main` con `Closes #780` + label `type:chore` | pendiente |
| WU-6 | Merge `--no-ff` (post CI verde) | pendiente |
| WU-7 | Cierre de issue + actualizar `docs/roadmap/transversales.md` (la fila de #780 dice "cerrado" pero la issue está OPEN) | pendiente |
| WU-8 | Limpiar worktree local | pendiente |

## Gates (CI required check, pre-MVP single-branch)

- `scripts/check_workflows.py` verde (meta-gate de los YAML; tocado en el slice).
- `scripts/check_required_jobs.py` verde (sin `SKIPS_BY_EVENT["schedule"]`).
- `scripts/check_mutation.py` verde (ajustes al wrapper).
- `ruff check .` limpio.
- `pytest tests/test_ci_workflow.py tests/test_check_mutation.py tests/test_check_required_jobs.py tests/test_security_scanning.py -q` verde.
- `ci / required` verde en el head del PR (lint + seguridad + typecheck + test + integration + verify-fallback-ready + build).
- `pr-name / branch-name` y `pr-size / pr-size` verde (diff ≤ 400 líneas, o `size:exception`).

## Legacy fidelity (P1)

N/A — este slice no toca legacy Access. Es un cambio de cadencia de CI puro.

## Estrategia de implementación

Cherry-pick de los dos commits no-merge desde `ci/780-release-only-heavy-tests-v2` (rama basada en `47072e0`) sobre una rama nueva `ci/780-release-only-heavy-tests-v3` que sale de `feat/56-doc-01-pr2-pdf-storage` (donde están los commits autogen y la historia coherente con PR #794). Push a la rama, PR contra `origin/main` (la default branch real del repo), merge con `--no-ff`.

Cherry-pick en orden cronológico (`d11a2ad` antes que `3631215`) para minimizar conflictos. Ambos commits tocan `tests/test_ci_workflow.py`; el segundo commit puede chocar con el primero si las expectativas sobre el `if:` del job `e2e` fueron reescritas.

## Riesgos identificados

1. **Divergencia entre `main` local (`55bd6ba`) y `origin/main` (`562effd`)**: hay dos historias paralelas desde los revert/reapply de contratos. Cherry-pick va sobre `feat/56-doc-01-pr2-pdf-storage` (que tiene PR #794 mergeado) para evitar arrastrar la historia vieja con `28614e1 feat(contratos): template engine`.
2. **Conflictos en `tests/test_ci_workflow.py`**: ambos commits a cherry-pickear modifican ese archivo. Si cherry-pick detecta conflicto, se resuelve tomando las expectativas más recientes (`3631215` después de `d11a2ad`).
3. **`scripts/check_required_jobs.py` ya tiene `SKIPS_BY_EVENT` sin la clave `"schedule"`** en mi main local — cherry-pick debería aplicar limpio, pero si el diff detecta que el upstream ya tiene la línea exacta, `--keep-redundant-commits` puede dar warning.
4. **Rama `ci/780-release-only-heavy-tests-v2` remota ya no es canónica**: el PR contra `origin/main` la reemplaza. La rama remota se retiene por AGENTS §15.2; la rama local y el worktree se limpian.

## Criterios de cierre del slice

- [ ] Cherry-picks mergeados en `ci/780-release-only-heavy-tests-v3` con SHA fresco (sin `Co-Authored-By`).
- [ ] CI verde en el head del PR.
- [ ] PR mergeado con `--no-ff` contra `origin/main`.
- [ ] #780 cerrada con SHA + path del test (`tests/test_ci_workflow.py::test_ci_workflow_runs_release_e2e_job_with_playwright`) + URL del run de `ci.yml`.
- [ ] `docs/roadmap/transversales.md` actualizado: la fila de #780 debe leer "cerrado (`<sha>`)" y no "cerrado (cron semanal removido...)" sin SHA, porque la fila provenía del cierre anterior que se reabrió.
- [ ] Worktree + rama local limpiados (sin `--delete-branch` remoto).
- [ ] Memoria de sesión guardada con `mem_session_summary`.
