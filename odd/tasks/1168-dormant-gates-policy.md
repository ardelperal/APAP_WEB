# #1168 — Gates sin evidencia de defecto se duermen tras ci-gate-policy.json (dormant, re-armables)

## Goal

Hacer explícito y testable el enforcement de `check_crap` y `check_mutation_sites` (epic #1065, handoff §8 criterio 5): NO se retiran — se duermen tras `.github/ci-gate-policy.json`, el gate sigue ejecutándose con findings visibles en el log, exit 0 en dormant, y re-arm por cambio de datos de una línea.

## Estado verificado en origin/main (5f643d7)

Ambos steps eran **bloqueantes mecánicamente** (`run:` directo, sin `continue-on-error`) aunque el inventario los clasificaba como informativos. El deliverable fue el policy file + wiring, no la eliminación.

## Acceptance criteria

1. `.github/ci-gate-policy.json`: ambos gates `dormant`, `reason` no vacía, `dormant_since: 2026-09-30`; schema pineado por test (allowed keys, enforcement ∈ {dormant, enforcing}, reason no vacía para dormant).
2. Los steps ejecutan el gate SIEMPRE (no skip silencioso, no false-green): findings visibles; dormant → exit 0; enforcing/no listado/policy ausente o inválida → fallo (default-deny).
3. Drift guard: gate del policy sin step real en ci.yml → test falla (demostrado con entrada bogus `check_nonexistent` → FAIL; restaurada → 19 passed).
4. Preflight espejo respeta el policy (los steps ejecutan `preflight.py run-gate`, misma semántica local y CI).
5. Docs actualizadas (`docs/quality/ci-gate-inventory.md`, `docs/codebase/quality-gates.md`) con estado Dormant + procedimiento de re-arm.

## Implementación

- `.github/ci-gate-policy.json` — policy declarativa (fuente del estado de enforcement).
- `scripts/preflight.py` — `run_gate_with_policy()` + CLI `run-gate GATE -- COMMAND...`; exit codes 0/1/2/3 (3 = policy inválida, fail loud). El gate se ejecuta siempre con output capturado y re-impreso (visibilidad garantizada y testeable).
- `.github/workflows/ci.yml` — los dos steps enrutan vía `preflight.py run-gate <gate> -- python scripts/<gate>.py` (el literal del gate queda visible en el comando, los pins existentes de `tests/test_ci_workflow.py` siguen pasando sin edición).
- `tests/test_ci_gate_policy.py` — schema, comportamiento (enforcing propaga rc; dormant devuelve 0 con findings visibles; no listado enforcing; inválida fail-loud), drift guard parametrizado, wiring pins.
- `docs/quality/ci-gate-inventory.md`, `docs/codebase/quality-gates.md` — filas Dormant + re-arm procedure.

## TDD evidence

- RED: `tests/test_ci_gate_policy.py` 17 failed / 1 skipped antes de implementar (API inexistente + policy ausente).
- GREEN: 19 passed tras implementar; suite completa 5271 passed / 21 skipped.
- TRIANGULATE: B007 y PLR2004 (2× magic value) detectados por ruff-ratchet en el camino y corregidos con constantes nombradas; drift guard negativo demostrado.

## Plan de validación (resultado)

1. `uv run --extra dev pytest` → 5271 passed, 21 skipped. ✅
2. `uv run --extra dev python -m mypy` → Success: no issues in 377 source files. ✅
3. `uv run --extra dev ruff check .` → All checks passed; ruff ratchet OK dentro de baseline. ✅
4. `.venv/bin/python scripts/check_vulture_guard.py` → OK (5 within baseline). ✅
5. `python scripts/preflight.py` → PASSED (20/20 steps), exit 0; `run-gate check_mutation_sites` muestra findings + banner DORMANT, exit 0. ✅
6. `actionlint` (1.7.12 con los tres `-ignore` declarados del step de CI) → exit 0; findings crudos pre-existentes en base (ci.yml minio service #900, deploy SC2129/SC2086). ✅

## Riesgos / fricciones (para la auditoría)

- El `run-gate` captura el output del gate y lo re-imprime al final (no streaming en vivo): garantiza visibilidad testeable; los gates tardan segundos, coste aceptable.
- La nueva ruta `run-gate` vive en `preflight.py` (superficie ya autorizada) para no añadir script nuevo; preflight gana un segundo modo documentado en su docstring.
- ruff-ratchet reportó NOTE de mejora posible (S603 2→0, ARG001, PLR0912, etc.): NO se tocan baselines en este PR (lock-in es el flujo del epic #1120).
- Presupuesto de revisión: diff ~390 líneas (bajo el techo de 400).
