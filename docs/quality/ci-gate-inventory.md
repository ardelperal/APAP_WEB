# Inventario de gates de CI

> Auditoría de fricción (issue #957, épica #935). Cubre cada gate bloqueante
> de `ci.yml`, `codeql.yml`, `pr-name.yml`, `pr-size.yml` y las reglas de
> branch protection de `main`.

## Criterio

Decisión del mantenedor, 2026-09-25: un gate bloqueante solo se mantiene si
detecta defectos reales o es práctica estándar del sector. Todo lo demás pasa
a informativo (avisa, no bloquea) o se elimina. Si una métrica obliga a
reestructurar código correcto para cumplirla, el defecto está en el gate, no
en el código.

Un corolario de esa misma decisión se aplica al diseño del propio gate: el
contrato de CI se lee de datos estructurados (rama, labels, API de GitHub),
nunca de parseo de texto libre, y sin reinventar funciones nativas de la
plataforma. Ejemplo: `issue-spec` leía `Closes #N` con una expresión regular
propia (falsos positivos, #952) en lugar del campo `closingIssuesReferences`
que calcula GitHub; la corrección es leer ese campo, no prohibir `Closes #N`.

## Inventario

| Gate | Qué exige (file) | Defectos reales detectados (evidencia) | Fricción observada (evidencia) | Equivalente en la industria | Decisión | Issue |
|---|---|---|---|---|---|---|
| `pr-size` | Diff ≤ 400 líneas salvo `size:exception` (`scripts/check_pr_size.py`, `.github/workflows/pr-size.yml`) | PR grande bloqueado según diseño (ejecución 36046072242) | Carrera de labels: un evento `labeled` cancelaba la ejecución y `size:exception` no se releía en rerun (#926, arreglado en #936) | Guías de tamaño de revisión (Google Engineering Practices); normalmente informativas, no bloqueantes | Mantener | #941, #958 |
| `issue-spec` | Cada PR debe cerrar una issue aprobada; parsea el cuerpo del PR en busca de una referencia de cierre (`scripts/check_issue_specs.py`) | Ninguno | 404 por parseo de texto libre (ejecución 36151968865, arreglado en #960); sub-issues artificiales para no romper el gate (#954, #955); cierre prematuro de #913 por un tramo intermedio (#931) | Vincular PR e issue es habitual; obligar a cerrar una issue completa en cada PR de una cadena, no | Arreglar — resolver el vínculo de forma determinista vía rama, labels o la API de cierre de GitHub, no parseo de texto | #956 |
| `ruff check` | Lint estándar de Python (`ruff check .`) | — | — | Estándar del sector | Mantener | — |
| `check_ruff_ratchet` | Baseline shrink-only sobre reglas de ruff aún no globales (`scripts/check_ruff_ratchet.py`) | Detectó TRY300 real (ejecución 36041158202) y PLR0402 real (#951); una mejora sobre el baseline solo avisa, no bloquea | — | Ratchet con baseline shrink-only; patrón conocido de adopción incremental de linters | Mantener — modelo a seguir para otros gates de este inventario | — |
| `check_rules`, `check_docstring_balance`, `check_module_size` (700 líneas), `check_route_size` (50 líneas), `check_layers`, `check_complexity` (CC ≤ 15) | Reglas AST y estructurales propias (`scripts/check_rules.py`, `scripts/check_docstring_balance.py`, `scripts/check_module_size.py`, `scripts/check_route_size.py`, `scripts/check_layers.py`, `scripts/check_complexity.py`) | Sin evidencia específica registrada en este inventario más allá de lo ya documentado en `docs/codebase/quality-gates.md` y `docs/codebase/module-size-budgets.md` | Sin fricción registrada | Guardarraíles estructurales habituales (linter propio, límites de tamaño, capas) | Mantener | — |
| `check_workflows` | Analiza los workflows de GitHub Actions (`scripts/check_workflows.py`) | Incidente real (#522) | — | Validación de YAML de CI; práctica habitual | Mantener | — |
| `check_test_classification` (marcador de integración) | Exige el marcador `integration` en los tests que llaman a Postgres real (`scripts/check_test_classification.py`) | Guardarraíl de marcador de integración (#932) | — | Marcado de suites lentas/externas; práctica habitual de pytest | Mantener | — |
| `check_alantyle`, `check_slice_completeness`, `check_migration_boundaries`, `check_vulture_guard`, `check_jscpd` | Estilo de documentación, completitud de slice hexagonal, límites de la capa de migración, guard de vulture y duplicación de código (`scripts/check_alantyle.py`, `scripts/check_slice_completeness.py`, `scripts/check_migration_boundaries.py`, `scripts/check_vulture_guard.py`, `scripts/check_jscpd.py`) | Sin fallos en las últimas 100 ejecuciones fallidas revisadas; coste y valor no verificados | No verificado | No verificado | Mantener hasta tener evidencia | — |
| `check_docstring_coverage` (73 %) | Cobertura de docstrings vía `interrogate` (`scripts/check_docstring_coverage.py`) | Ninguno | No verificado | `interrogate` suele usarse en modo informativo, no bloqueante | Informativo | #970 |
| `check_mutation_sites` | Densidad de sitios de mutación por fichero, solo puede bajar (`scripts/check_mutation_sites.py`) | Ninguno | Obligó a crear `app/modules/adopciones/_actor_guard.py` (#950) y `app/modules/acogidas/_actor_flow.py` (#961) solo para no subir el contador | Sin equivalente habitual | Informativo | #968 |
| `check_import_cycles` | Ciclos de imports nuevos contra un baseline exacto (`scripts/check_import_cycles.py`) | Detecta ciclos nuevos: valioso | El baseline exacto rompe la CI al arreglar un ciclo existente, no solo al introducir uno (#951) | `import-linter` y equivalentes; el patrón de baseline exacto no es habitual | Arreglar — una entrada obsoleta del baseline (ciclo ya resuelto) debe avisar, no bloquear | #971 |
| `check_crap` | Grado A de CRAP score, solo con cobertura unitaria, baseline exacto (`scripts/check_crap.py`) | No verificado | Todos los fallos muestreados del job `test` fueron CRAP (ejecuciones 36041610048, 35781820929, 35717450890); obligó a 411 líneas de fakes que duplican tests contra Postgres real (#913, reducidas a 307 en #931) | `Crap4j` existe como herramienta; este uso bloqueante con cobertura solo unitaria no es habitual | Informativo hasta #929 | #969, #929 |
| Cobertura combinada (`--cov-fail-under=85`) | Suelo de cobertura del 85 % sobre `app/` y `migration/` (`.github/workflows/ci.yml`, job `test`) | No verificado | — | Suelo de cobertura en CI; práctica habitual | Mantener | #929 |
| `typecheck` (mypy) | Cero errores de tipos en `app/` y `migration/` (`python -m mypy`, `.github/workflows/ci.yml`, job `typecheck`) | Detectó dependencias sin stubs reales (ejecuciones 35631571955, 35274071081) | — | Estándar del sector | Mantener | — |
| `security` (pip-audit, gitleaks, trivy config) | Auditoría de dependencias y de secretos en el árbol actual (`.github/workflows/ci.yml`, job `security`) | No verificado | Falso positivo de gitleaks sobre un fixture de test (ejecución 35526972737) | Estándar del sector | Mantener, con excepción por fingerprint del hallazgo | #967 |
| `security-deep` (gitleaks histórico) | Escaneo de secretos sobre todo el historial de commits (`.github/workflows/ci.yml`, job `security-deep`) | Detectó una API key real en el commit inicial del repo | — | Estándar del sector | Mantener | #967 |
| `integration` (Postgres real) | Ejecuta `tests/integration/` con marcador `integration` contra Postgres real (`.github/workflows/ci.yml`, job `integration`) | Detectó #944, #945 y #947 | — | Suite de integración contra base de datos real; práctica habitual | Mantener | — |
| `mutation` (cosmic-ray) | Mutation testing solo en tags `v*` y `workflow_dispatch`, nunca por PR (`.github/workflows/ci.yml`, job `mutation`) | — | Sin coste en el camino crítico de PR | Mutation testing fuera del camino de PR; práctica habitual | Mantener como está | #902 |
| `e2e` (Playwright) | Suite E2E contra la aplicación real, reservada a `release`/`workflow_dispatch` (`.github/workflows/ci.yml`, job `e2e`) | — | Fallo de infraestructura por pull anónimo de la imagen `minio/minio` (ejecución 36035660912), no defecto de producto | Suite E2E de release; práctica habitual | Mantener el gate; arreglar la infraestructura de la imagen | #973 |
| `required` (agregador) | Agrega el resultado de los jobs obligatorios y falla cerrado ante skips inesperados (`scripts/check_required_jobs.py`, `.github/workflows/ci.yml`) | — | — | Patrón estándar de check agregador para branch protection | Mantener | — |
| `branch-name` | Valida el nombre de rama contra la convención `<tipo>/<nº>-<slug>` (`scripts/check_branch_name.py`, `.github/workflows/pr-name.yml`) | — | — | Convención de nombre de rama habitual | Mantener | — |
| `CodeQL` | Análisis estático de seguridad (`.github/workflows/codeql.yml`) | No verificado | Ninguna en el análisis en sí; el problema está en cómo bloquea el merge (ver `required_conversation_resolution` más abajo) | Estándar del sector | Mantener CodeQL | #934, #937, #972 |
| Protección de rama: `strict: true` | Exige rama actualizada contra `main` antes de mergear (configuración de branch protection en GitHub, no versionada en el repo) | Evita verdes obsoletos (stale-green) | Coste medido: rebases manuales y repetición completa de la CI tras cada merge (#958) | Requiere una merge queue para no tener coste; el repo es de un único usuario y no tiene acceso a merge queue | Decisión pendiente del mantenedor | #958 |
| Protección de rama: `required_conversation_resolution` | Exige resolver todos los hilos de conversación del PR antes de mergear (configuración de branch protection en GitHub, no versionada en el repo) | No verificado | Bloquea el merge por hilos automáticos que CodeQL abre sobre alertas preexistentes que cambian de línea (#931, #946) | Habitual para revisión humana; no para comentarios automáticos de una herramienta de análisis estático | Arreglar | #972 |

## Cómo usar este inventario

Todo gate bloqueante nuevo añade su fila a esta tabla con evidencia: qué
defecto real detecta o qué práctica estándar del sector replica. La tabla se
revisa cada vez que un gate causa fricción, como parte de la auditoría
continua de la épica #935.

## Navigation

Previous: [Codebase guide](../CODEBASE-GUIDE.md) | Related: [Quality gates](../codebase/quality-gates.md), [Hardening roadmap](hardening-roadmap.md)
