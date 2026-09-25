[← Back to Codebase Guide](../CODEBASE-GUIDE.md)

# Quality gates

Esta página posee las reglas §19, §20, §23 y §24 de AGENTS verbatim: el suelo global de cobertura, el linter APAP001/APAP003, la expectativa de E2E por slice UI y el job `typecheck` de mypy.

## Regla 19 — Suelo global de cobertura al 85% enforzado en CI

El umbral `fail_under = 85` declarado en `pyproject.toml` no es documentación.
El job `test` de CI corre pytest con `--cov=app --cov=migration`, genera
`coverage.json` y aplica `--cov-fail-under=85`. El mismo reporte alimenta el
gate de cobertura total sobre `CRITICAL_HELPERS`. Quitar flags o bajar el suelo
desactiva protección real y queda bloqueado.

**Aplicación**: `tests/test_ci_workflow.py::test_ci_workflow_test_job_enforces_global_coverage_floor` pinea los flags en `ci.yml` y su paridad con `fail_under` en `pyproject.toml`; `--cov-fail-under=85` hace pytest salir con código no-cero por debajo del suelo; `scripts/pytest_plugin/coverage_gate.py` sigue enforzando 100% sobre `CRITICAL_HELPERS` desde el `coverage.json` producido.

## Regla 20 — Linter APAP001/APAP003 enforzado en CI

El linter custom de reglas de AGENTS (`scripts/check_rules.py` — APAP001 aislamiento route/SQL, APAP003 prohibición de logger crudo, más Detectores 2-8: auth default-deny, redirects, listas de roles en DDL, prohibición de `print`, CSRF middleware/SameSite) es un gate de CI, no una conveniencia local. El job `lint` en `.github/workflows/ci.yml` corre `python scripts/check_rules.py .` después de `ruff check .`; cualquier violación falla el build. Ruff no puede correr estas reglas por sí mismo (ruff 0.15+ rechaza selectores de reglas definidas en Python en `select`), así que el paso del linter AST es la ÚNICA aplicación automática de APAP001/APAP003 — quitar el paso de `ci.yml` es un cambio bloqueado. El linter debe escanear la raíz del repo (`.`): pasar `app` como raíz de escaneo desactiva silenciosamente los Detectores 5-8, que resuelven paths relativos a `app/` contra la raíz escaneada. Los falsos positivos conocidos se silencian vía `DEFAULT_EXCLUDES` y `.check_rulesignore`.

**Aplicación**: `tests/test_ci_workflow.py::test_ci_workflow_lint_job_runs_check_rules_gate` pinea el paso (con scope a las líneas ejecutables del job `lint`) y la invocación en la raíz del repo; `scripts/check_rules.py` sale con código no-cero ante cualquier violación, fallando el job `lint`; los visitors quedan pineados por `tests/test_ruff_apap001.py` y `tests/test_apap003.py` para que el mirror de plugin de ruff y el gate de CI no puedan divergir.

## Regla 23 — E2E expectation: cada slice de UI crece la red E2E

Cada slice de feature que añade o cambia UI (routes que renderizan templates, formularios, interacciones HTMX) debe añadir o actualizar al menos un flujo Playwright E2E bajo `tests/e2e/`. Los slices solo-backend (services, migration, scripts) están exentos. La suite E2E es la única red que captura regresiones de wiring template/route/CSRF que los tests unitarios estructuralmente no pueden ver.

**QA-through-UI solamente.** La verificación de cualquier slice con superficie UI debe pasar por la suite Playwright E2E existente bajo `tests/e2e/` (o un test de navegador in-tree equivalente). QA vía shell de Python, inspección directa de DB o `curl` contra un servidor corriendo no es sustituto y no debe presentarse como tal en descripciones de PR, runbooks o reportes de estado.

El job `e2e` de CI se reserva para tags `v*` y `workflow_dispatch`; se salta en pull requests y pushes normales. Cuando corre, levanta la aplicación real contra PostgreSQL efímero, instala Chromium desde el lock y ejecuta la suite fail-closed `tests/e2e_ci/`: Chromium ausente, startup fallido, cero tests o cualquier fallo producen rojo. La suite histórica `tests/e2e/` no es el gate porque mezcla deuda funcional y skips condicionales; no se presenta como evidencia hasta su saneamiento. `ci / required` exige el smoke real en esos eventos de release y evita falsos verdes de infraestructura.

**Aplicación**: revisión de PR. Un PR cuyo diff toca `templates/` o añade/cambia una route UI sin tocar `tests/e2e/` debe justificar la exención explícitamente en la descripción del PR o ser bloqueado.

## Regla 24 — Gate mypy typecheck: cero errores en `app/` + `migration/`

El tipado estático se enforza, no se aspira: el job `typecheck` de CI corre `python -m mypy` y cualquier error falla el build. El scope y los flags viven en `pyproject.toml` bajo `[tool.mypy]` — la **única fuente de verdad** (`files = ["app", "migration"]`, `warn_unused_ignores`, `warn_redundant_casts`, `show_error_codes`, `enable_error_code = ["ignore-without-code"]`, `python_version = "3.11"`, `platform = "linux"` — la plataforma de CI es la vista autoritativa); ni el job de CI ni el Makefile los repiten, así que `make typecheck` local corre el chequeo exacto del job `typecheck` de CI. Cada `# type: ignore` debe llevar su código de error específico (por ejemplo, `# type: ignore[assignment]`) — los ignores desnudos los rechaza el código de error `ignore-without-code` habilitado en `enable_error_code`, mientras que `warn_unused_ignores` borra ignores que ya no se necesitan. Quitar el job `typecheck`, quitar flags de `[tool.mypy]` o reducir `files` es un cambio bloqueado: des-tipifica paquetes enteros silenciosamente. Apriete es una sola vía — la configuración solo puede AÑADIR flags (por ejemplo, `strict = true` por módulo), nunca quitarlos.

**Aplicación**: `tests/test_ci_workflow.py::test_ci_workflow_defines_typecheck_job_running_mypy` pinea el job de CI y su invocación `python -m mypy`; `ci / required` agrega `typecheck`, por lo que una regresión de tipos bloquea el merge y, en consecuencia, el deploy; mypy sale con código no-cero ante cualquier error, fallando el job.

## Contributor checklist

- [ ] Cada PR no baja la cobertura global de `app/` por debajo del 85% (gate de CI).
- [ ] Si toca `scripts/check_rules.py`, `pyproject.toml` o `ci.yml`, los flags siguen pineados por `tests/test_ci_workflow.py`.
- [ ] Cada nuevo form/route UI lleva su flujo Playwright E2E correspondiente en `tests/e2e/`.
- [ ] Cada `# type: ignore` lleva su código de error específico; ningún ignore desnudo.
- [ ] Si baja `[tool.mypy]` o elimina el job `typecheck`, lo bloquea el cambio (config se amplía, no se reduce).

## Estado de los gates (informativo vs bloqueante)

A raíz de la auditoría de fricción de CI 2026-09-24 (épica #935, inventario #957)
los siguientes gates pasaron de **bloqueantes** a **informativos**: el script
sigue ejecutándose en el mismo job (`lint` o `test`) y emite un `NOTE` por cada
hallazgo, pero `main()` sale con exit 0 aunque haya notas. La señal sigue
estando en el log del PR; lo que se quita es el bloqueo que forzaba reescritura
de código correcto sin defecto subyacente.

| Gate | Issue | Script | Razón para el cambio |
|---|---|---|---|
| Mutation-site density ratchet | #968 | `scripts/check_mutation_sites.py` | El conteo AST de nodos no detecta defectos; obligaba a partir módulos sin razón de bug. Mantiene el ratchet shrink-only de la BASELINE, pero el crecimiento se registra como `NOTE`. |
| Docstring coverage floor | #970 | `scripts/check_docstring_coverage.py` | El porcentaje de docstrings es una señal de documentación, no de defectos; `interrogate` y similares se usan como aviso, no como puerta. El suelo del 73 % se mantiene documentado. |
| Per-function CRAP score + baseline exactness | #969 | `scripts/check_crap.py` | La cobertura combinada (#929) no existe aún; el script solo mide cobertura unitaria, y el `check_baseline_exactness` penalizaba las mejoras. Se reevaluará cuando #929 esté mergeado. |
| Import-cycle baseline obsoleto | #971 | `scripts/check_import_cycles.py` (test) | Arreglar un ciclo rompía el job `test` hasta editar la BASELINE a mano. La entrada obsoleta ahora es `NOTE` (igual que el ratchet de ruff). |

Los gates que siguen siendo **bloqueantes** son los detallados en §19, §20,
§23 y §24 más arriba: cobertura global al 85 %, linter APAP001/APAP003, E2E
por slice UI y job `typecheck` de mypy.

**Aplicación**: si un PR restaura uno de estos gates a bloqueante, debe
justificarlo en el cuerpo del PR con la evidencia del defecto que el gate
estaba atajando (referencia a un incidente real o a un test que falla).


## Navigation

Previous: [Layer boundaries](layer-boundaries.md) | Next: [Module size budgets](module-size-budgets.md)
