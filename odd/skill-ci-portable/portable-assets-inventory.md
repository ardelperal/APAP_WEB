# Inventario de activos portables — patrón de CI

- **Repositorio inventariado:** `ardelperal/APAP_WEB` en `/home/ubuntu/repos/apap-app`
- **SHA de referencia:** `2045ea12d8f4fe0c27baef01233e9b6665800c12` (2026-10-01)
- **Método:** lectura de solo lectura (`git`, `wc -l`, `grep`) sobre el árbol de trabajo; ninguna ejecución de gates ni mutación de estado.
- **Skill bajo empaquetado:** `skills/ci-pattern/` (copia versionada en el repo; la copia canónica de `DysTelefonica/team-skills` vive en `~/personal-skills/personal/ardelperal/ci-pattern/`).
- **Alcance:** inventario de activos mecanizables, esquema de parámetros, huecos y auditoría de determinismo. **No** diseña el scaffolder; lo deja especificado por huecos para la pasada siguiente.

Los conteos del §1 corresponden a ficheros concretos; un activo "ya portable" es el que vive dentro de `skills/ci-pattern/assets/`.

---

## §1 — Activos mecanizables

Leyenda de **Estado**: `YA-PORT` = ya vive como asset de la skill; `PLANTILLA` = sirve tal cual pero tiene valores del origen incrustados; `PARAM` = ya se controla por argumento o fichero de datos; `APAP` = específico del origen, no pertenece al patrón portable.

### 1.1 — Preflight (espejo ejecutable del job `lint`)

| # | Activo | Lín. | Dependencias | Qué exige configurarse en otro repo | Estado |
|---|---|---|---|---|---|
| 1 | `scripts/preflight.py` | 505 | `pyyaml`, stdlib; lee `.github/workflows/ci.yml` y `.github/ci-gate-policy.json` | Nombre del job de lint (`lint`, `preflight.py:182`); ruta de la política (`preflight.py:60`); secuencia de pasos homogénea con `bash -e` | PLANTILLA (acepta `--workflow`, `--root`) |
| 2 | `tests/test_preflight.py` | 467 | `pytest`, `scripts.preflight` | Ruta del workflow (`WORKFLOW_PATH`, `:21`); plantillas de workflow de prueba | PLANTILLA |
| 3 | `tests/_workflow_yaml.py` | 163 | `pyyaml` | Ninguno (helper genérico de parseo de jobs/steps) | YA-PORT (genérico) |

### 1.2 — Trazabilidad issue↔PR, etiquetas y nombre de rama

| # | Activo | Lín. | Dependencias | Qué exige configurarse | Estado |
|---|---|---|---|---|---|
| 4 | `scripts/check_issue_specs.py` | 557 | stdlib `urllib` (GraphQL REST); `GITHUB_TOKEN`, `GITHUB_API_URL`, `GITHUB_EVENT_PATH`; importa `check_branch_name` | Formularios en `.github/ISSUE_TEMPLATE` (`:27`); etiquetas tipo (`:39-43`), `status:approved` (`:47`), `chain:partial` (`:51`); fuente de cierre `closingIssuesReferences` (`:53`) | PLANTILLA |
| 5 | `tests/test_check_issue_specs.py` | 386 | `pytest`, dobles de API | Fixtures del evento PR | PLANTILLA |
| 6 | `scripts/check_branch_name.py` | 77 | stdlib `re` | Regex (`:20`), tipos (`:46`), allowlist (`:11-19`), patrones Dependabot (`:22`) y `skill-fleet/` (`:28`) | PLANTILLA |
| 7 | `tests/test_check_branch_name.py` | 79 | `pytest` | Casos por repo | PLANTILLA |

### 1.3 — Presupuesto de revisión y ciclo de PR

| # | Activo | Lín. | Dependencias | Qué exige configurarse | Estado |
|---|---|---|---|---|---|
| 8 | `scripts/check_pr_size.py` | 134 | git (`git diff --shortstat`), `gh`/API los aporta el workflow | Presupuesto `400` (`:29`); prefijo `size-exception-reason:` (`:39`) | PLANTILLA |
| 9 | `tests/test_pr_size.py` | 183 | `pytest` | Ninguno más que el presupuesto | PLANTILLA |
| 10 | `.github/workflows/pr-size.yml` | 183 | `actions/checkout` (fetch-depth 0), `setup-python@5fda3b...`, `curl`, `jq`; `issues: read` | Ref del base (`github.base_ref`); exclusiones de lockfiles (`uv.lock`, `**/package-lock.json`); versión Python `3.12.11` (`:83`) | PLANTILLA |
| 11 | `.github/workflows/pr-name.yml` | 37 | `actions/checkout`, `setup-python@5fda3b...`; `contents: read` | Ninguna más que la regex del gate | PLANTILLA |
| 12 | `.github/PULL_REQUEST_TEMPLATE.md` | 49 | — | Secciones exactas que leen los gates; campo `size-exception-reason:` | PLANTILLA |

### 1.4 — Agregador de jobs requeridos (ya publicado como asset)

| # | Activo | Lín. | Dependencias | Qué exige configurarse | Estado |
|---|---|---|---|---|---|
| 13 | `skills/ci-pattern/assets/required-jobs/check_required_jobs.py` | 184 | stdlib; lee `needs.json` + política JSON | Nombres de jobs y skips viven **en la política**, no en el código | YA-PORT |
| 14 | `skills/ci-pattern/assets/required-jobs/required-jobs.policy.example.json` | 37 | — | `required_jobs`, `events.<evento>.accepted_skips` | YA-PORT (molde) |
| 15 | `skills/ci-pattern/assets/required-jobs/tests/` (2 suites) | 247 | `pytest` o stdlib | Paridad workflow↔política | YA-PORT |
| 16 | `skills/ci-pattern/assets/required-jobs/tests/fixtures/ci-workflow.fixture.yml` | 37 | `pyyaml` | Nombres de jobs del destino | YA-PORT |
| 17 | `scripts/check_required_jobs.py` (implementación del origen, aún divergente) | 413 | stdlib | `ALL_JOBS` (`:91-100`), `JOB_DEPENDENCIES` (`:114-124`), `SKIPS_BY_EVENT` (`:126-137`), allowlist no-UI (`:38-78`), ficheros anti-autoexención (`:80-88`) | PLANTILLA (migrar a la política del asset) |
| 18 | `tests/test_check_required_jobs.py` | 594 | `pytest` | DAG y skips del destino | PLANTILLA |
| 19 | `tests/test_ci_workflow.py` | 3032 | `pytest`, `_workflow_yaml` | Pinea job↔script de cada gate; **es el mayor riesgo de acoplamiento APAP** | APAP |

### 1.5 — Validador de workflows y etiquetas de runner

| # | Activo | Lín. | Dependencias | Qué exige configurarse | Estado |
|---|---|---|---|---|---|
| 20 | `scripts/check_workflows.py` | 476 | `pyyaml` | Ninguno (reglas generales: timeout, puertos fijos, comandos ausentes, concurrencia, self-hosted vs `pull_request`) | YA-PORT (lógica genérica) |
| 21 | `tests/test_check_workflows.py` | 519 | `pytest` | Ninguno | YA-PORT |
| 22 | `.github/actionlint.yaml` | 15 | actionlint 1.7.12 | Lista de etiquetas self-hosted (`:5-15`): `self-hosted, Linux, ARM64, apap, oracle, coolify, noble, deploy` | PLANTILLA |

### 1.6 — Política de gates dormibles

| # | Activo | Lín. | Dependencias | Qué exige configurarse | Estado |
|---|---|---|---|---|---|
| 23 | `.github/ci-gate-policy.json` | 14 | leído por `preflight.py` | Entradas `check_crap`, `check_mutation_sites`; claves `enforcement/reason/dormant_since` (ver §3 G9: diverge de `parameters.md`) | PLANTILLA |
| 24 | `tests/test_ci_gate_policy.py` | 226 | `pytest`, `preflight`, `_workflow_yaml` | Ruta de política y workflow (`:37-39`) | PLANTILLA |

### 1.7 — Evidencia de release/batería y smoke

| # | Activo | Lín. | Dependencias | Qué exige configurarse | Estado |
|---|---|---|---|---|---|
| 25 | `scripts/check_release_evidence.py` | 181 | `gh api`/JSON por stdin | Contextos `release/e2e-production` (`:41`) y `release/smoke-production` (`:42`); runbook (`:51`) | PLANTILLA |
| 26 | `tests/test_check_release_evidence.py` | 236 | `pytest` | Ninguno | PLANTILLA |
| 27 | `scripts/check_release_e2e_required.py` | 183 | git (`git diff`) | Fichero de rutas sensibles (`:39`) | PLANTILLA |
| 28 | `tests/test_check_release_e2e_required.py` | 255 | `pytest` | Cada patrón debe casar un fichero rastreado | PLANTILLA |
| 29 | `.github/release-e2e-paths.txt` | 49 | — | Globs de auth, sesión, CSRF, migraciones, wiring de despliegue | APAP (datos) |
| 30 | `scripts/production_smoke.py` | 286 | stdlib `urllib` | `--health-url` (`:249`), `--revision` (`:250`), `--attempts`/`--interval` (`:251-252`), `USER_AGENT` (`:58`), ruta `/healthz` y campo `revision` (`:138`,`:149`) | PLANTILLA |
| 31 | `tests/test_production_smoke.py` | 343 | `pytest` (HTTP stub) | Ninguno | PLANTILLA |
| 32 | `scripts/verify_deployment.py` | 79 | `httpx` | URL y `revision` por argumento | PARAM |
| 33 | `scripts/coolify_webhook.py` | 152 | `httpx`; `COOLIFY_WEBHOOK_URL/SECRET` | Proveedor de deploy (sustituible) | APAP |
| 34 | `tests/test_deploy_workflow.py` | 366 | `pytest`, `_workflow_yaml` | Estructura de `deploy.yml` del origen | APAP |

### 1.8 — Ratchets y presupuestos estructurales

| # | Activo | Lín. | Dependencias | Qué exige configurarse | Estado |
|---|---|---|---|---|---|
| 35 | `scripts/_ratchet_deadline.py` | 118 | stdlib `datetime` | `WARN_DAYS_AHEAD=30` (`:32`) | YA-PORT |
| 36 | `scripts/check_ruff_ratchet.py` | 551 | `ruff==0.15.21` (`:74`), `pyproject.toml` | `RUFF_VERSION` (`:74`), `BASELINE` (`:81`); `--update-baseline` shrink-only | PLANTILLA |
| 37 | `tests/test_ruff_ratchet.py` | 379 | `pytest`, ruff | Ninguno | PLANTILLA |
| 38 | `scripts/check_vulture_guard.py` | 400 | `vulture` | `BASELINE: int = 5` (`:100`) | PLANTILLA |
| 39 | `tests/test_check_vulture_guard.py` | 338 | `pytest` | Ninguno | PLANTILLA |
| 40 | `scripts/check_module_size.py` | 185 | stdlib `ast`; `_ratchet_deadline` | `MAX_LINES=700` (`:33`), `SCAN_DIRS=("app","migration")` (`:36`), `BASELINE` (`:40`), `TARGET` (`:64`) | PLANTILLA |
| 41 | `tests/test_module_size.py` | 166 | `pytest` | Ninguno | PLANTILLA |
| 42 | `scripts/check_route_size.py` | 400 | stdlib `ast` | `MAX_LINES=50` (`:63`), `MAX_FORM_PARAMS=8` (`:71`), `BASELINE`/`FORM_BASELINE` | PLANTILLA |
| 43 | `tests/test_route_size.py` | 316 | `pytest` | Ninguno | PLANTILLA |
| 44 | `scripts/check_complexity.py` | 268 | stdlib `ast` | `MAX_CC=15` (`:39`), `BASELINE_CC` (`:55`) | PLANTILLA |
| 45 | `scripts/check_docstring_coverage.py` | 181 | `interrogate` | `BASELINE_COVERAGE_FLOOR=73.0` (`:46`) | PLANTILLA |
| 46 | `scripts/check_alantyle.py` | 903 | stdlib `re` | `--informational` (`:859`); reglas de estilo documental | APAP/skill local |
| 47 | `tests/test_check_alantyle.py` | 1122 | `pytest` | Ninguno | APAP |

Detectores estructurales puramente APAP (no portables sin el modelo de capas del origen): `scripts/check_rules.py` (2034), `scripts/check_layers.py` (717), `scripts/check_slice_completeness.py`, `scripts/check_migration_boundaries.py`, `scripts/check_test_classification.py`, `scripts/check_jscpd.py`, `scripts/check_crap.py`, `scripts/check_mutation_sites.py`, `scripts/check_mutation.py`.

### 1.9 — Workflows y plantillas

| # | Activo | Lín. | Dependencias | Qué exige configurarse | Estado |
|---|---|---|---|---|---|
| 48 | `.github/workflows/ci.yml` | 1464 | actions pinneadas; DAG de 13 jobs | Nombres de jobs (`:48-1429`), `runs-on: ubuntu-24.04`, versión Python, `--cov-fail-under=85` (job `test`), contexto Postgres, MinIO replica | PLANTILLA (patrón) + APAP (jobs `rules/layers/slice/migration`) |
| 49 | `.github/workflows/deploy.yml` | 648 | self-hosted `[...,apap,oracle,coolify,noble,deploy]` (`:296`); `cosign`; GHCR; Coolify | `IMAGE=ghcr.io/ardelperal/apap-web` (`:310`); secretos `COOLIFY_*` (`:321-322`); var `APAP_DEPLOY_HEALTH_URL` (`:323`); contextos de status (`:154`) | PLANTILLA (patrón) + APAP (proveedor, host) |
| 50 | `.github/workflows/main-audit.yml` | 56 | `issues: write`; script propio | Cron 05:30 UTC; título de issue de seguimiento | PLANTILLA + APAP (script) |
| 51 | `.github/scripts/main_history_audit.py` | 244 | `gh api`/stdlib; `GH_TOKEN`, `REPO`, `LIMIT=30` | Título de issue; ventana de commits | APAP |
| 52 | `.github/workflows/codeql.yml` | 58 | `github/codeql-action` | Lenguajes a escanear | PLANTILLA |
| 53 | `.github/workflows/minio-replica.yml` | 126 | registry privado GHCR | Servicio APAP | APAP |
| 54 | `.github/actions/setup-python/action.yml` | 22 | `actions/setup-python@ece7cb...`; `uv==0.9.28`; `.python-version` | Versión de uv (string incrustado) | PLANTILLA |
| 55 | `.python-version` | 1 | — | `3.12.11` | PARAM |
| 56-61 | `.github/ISSUE_TEMPLATE/{bug_report,feature_request,documentation,maintenance,refactor}.yml` (48 cada uno) + `config.yml` | 242 | — | Secciones exactas vs `check_issue_specs.py`; `type:*` por formulario; `blank_issues_enabled: false` | PLANTILLA |
| 62 | `docs/quality/ci-gate-inventory.md` | 61 | — | Tabla gate↔evidencia↔decisión; hoy congelada al origen | PLANTILLA de doc |

**Total §1: 62 ficheros** (12 mínimos obligatorios: 1, 4, 6, 8, 12, 13-16, 23, 48; el resto opcional o específico del origen).

---

## §2 — Esquema de parámetros por repo

`Tipo` es el tipo lógico del valor. `Default` es el valor verificado en el origen. `Consumidor` da la evidencia `fichero:línea`.

| # | Parámetro | Tipo | Default (origen) | Consumidor |
|---|---|---|---|---|
| P01 | `branch_name_pattern` | regex | `^(?:(chore\|feat\|fix\|perf\|refactor\|docs\|ci\|test)/[0-9]+-[a-z0-9-]+\|archive/.+\|main)$` | `scripts/check_branch_name.py:20` |
| P02 | `branch_name_types` | lista | `chore,feat,fix,perf,refactor,docs,ci,test` | `check_branch_name.py:46` |
| P03 | `branch_name_allowlist` | lista | 3 ramas pretéritas + `resolve-conflict` | `check_branch_name.py:11-19` |
| P04 | `dependabot_branch_pattern` | regex | `^dependabot/(pip\|npm_and_yarn\|github_actions)/...$` | `check_branch_name.py:22` |
| P05 | `skill_fleet_branch_pattern` | regex | `^skill-fleet/[A-Za-z0-9._-]+$` | `check_branch_name.py:28` |
| P06 | `review_budget_lines` | entero | `400` | `scripts/check_pr_size.py:29` |
| P07 | `size_exception_field` | cadena | `size-exception-reason:` | `check_pr_size.py:39` |
| P08 | `lockfile_excludes` | lista | `**/package-lock.json`, `uv.lock` | `.github/workflows/pr-size.yml` (paso de diff) |
| P09 | `labels_type` | mapa formulario→etiqueta | `bug_report.yml→type:bug`, `documentation.yml→type:docs`, `feature_request.yml→type:feature`, `maintenance.yml→type:chore`, `refactor.yml→type:refactor` | `scripts/check_issue_specs.py:39-43` |
| P10 | `label_approval` | cadena | `status:approved` | `check_issue_specs.py:47` |
| P11 | `label_chain_partial` | cadena | `chain:partial` | `check_issue_specs.py:51` |
| P12 | `issue_form_dir` | ruta | `.github/ISSUE_TEMPLATE` | `check_issue_specs.py:27` |
| P13 | `closing_refs_source` | enumerado | `closingIssuesReferences` (GraphQL) | `check_issue_specs.py:53` |
| P14 | `status_context_e2e` | cadena | `release/e2e-production` | `scripts/check_release_evidence.py:41` |
| P15 | `status_context_smoke` | cadena | `release/smoke-production` | `check_release_evidence.py:42` |
| P16 | `release_runbook_path` | ruta | `docs/runbooks/e2e-production.md` | `check_release_evidence.py:51` |
| P17 | `sensitive_paths_file` | ruta | `.github/release-e2e-paths.txt` | `scripts/check_release_e2e_required.py:39` |
| P18 | `health_url_var` | nombre de variable | `APAP_DEPLOY_HEALTH_URL` | `.github/workflows/deploy.yml:323,464,504,520` |
| P19 | `health_path` | ruta | `/healthz` | `scripts/production_smoke.py:138` |
| P20 | `health_revision_field` | cadena JSON | `revision` | `production_smoke.py:149` |
| P21 | `smoke_user_agent` | cadena | `apap-production-smoke/1 (+https://github.com/ardelperal/APAP_WEB)` | `production_smoke.py:58` |
| P22 | `smoke_attempts` / `smoke_interval_s` | entero / flotante | `6` / `10.0` | `production_smoke.py:251-252` |
| P23 | `required_jobs` | conjunto | `pr-size, issue-spec, lint, security, security-deep, mutation, typecheck, test, integration, verify-fallback-ready, build, e2e, ui-detection` | `scripts/check_required_jobs.py:91-100` |
| P24 | `job_dependencies` | mapa job→needs | DAG de 13 nodos | `check_required_jobs.py:114-124` |
| P25 | `accepted_skips_by_event` | mapa evento→conjunto | `pull_request→{security-deep,mutation,e2e}`; `push→{security-deep,issue-spec,mutation,e2e}`; `workflow_dispatch→{issue-spec}` | `check_required_jobs.py:126-137` |
| P26 | `non_ui_path_allowlist` | tupla de prefijos | `.atl/, .codegraph/, ..., scripts/, skills/, tests/` + ficheros raíz | `check_required_jobs.py:38-78` |
| P27 | `gate_source_files` | tupla | `check_required_jobs.py`, `ci.yml`, `deploy.yml` | `check_required_jobs.py:80-88` |
| P28 | `required_status_contexts` | lista | `ci / required`, `pr-name / branch-name`, `pr-size / pr-size` | `.github/branch-protection.md` (tabla «Checks requeridos») |
| P29 | `runner_labels_selfhosted` | lista | `self-hosted,Linux,ARM64,apap,oracle,coolify,noble,deploy` | `.github/actionlint.yaml:5-15`; `deploy.yml:296` |
| P30 | `python_version` | cadena | `3.12.11` | `.python-version`; `ci.yml:89,128`; `pr-name.yml:...` |
| P31 | `uv_version` | cadena | `0.9.28` | `.github/actions/setup-python/action.yml:15` |
| P32 | `coverage_floor` | entero | `85` | `pyproject.toml:360` (`[tool.coverage.report] fail_under`) |
| P33 | `module_budget_lines` | entero | `700` | `scripts/check_module_size.py:33` |
| P34 | `module_scan_dirs` | tupla | `("app","migration")` | `check_module_size.py:36` |
| P35 | `handler_budget_lines` | entero | `50` | `scripts/check_route_size.py:63` |
| P36 | `form_param_budget` | entero | `8` | `check_route_size.py:71` |
| P37 | `cc_budget` | entero | `15` | `scripts/check_complexity.py:39` |
| P38 | `docstring_floor_pct` | flotante | `73.0` | `scripts/check_docstring_coverage.py:46` |
| P39 | `ruff_version` | cadena | `0.15.21` | `scripts/check_ruff_ratchet.py:74` |
| P40 | `vulture_baseline` | entero | `5` | `scripts/check_vulture_guard.py:100` |
| P41 | `gate_policy_path` | ruta | `.github/ci-gate-policy.json` | `scripts/preflight.py:60` |
| P42 | `gate_policy_keys` | conjunto | `enforcement, reason, dormant_since` | `preflight.py:62` |
| P43 | `enforcement_values` | conjunto | `dormant, enforcing` | `preflight.py:63` |
| P44 | `lint_job_name` | cadena | `lint` | `preflight.py:182` |
| P45 | `deploy_image` | cadena | `ghcr.io/ardelperal/apap-web` | `.github/workflows/deploy.yml:310` |
| P46 | `coolify_webhook_secrets` | nombres de secreto | `COOLIFY_WEBHOOK_URL`, `COOLIFY_WEBHOOK_SECRET` | `deploy.yml:321-322` |
| P47 | `ratchet_warn_days_ahead` | entero | `30` | `scripts/_ratchet_deadline.py:32` |
| P48 | `smoke_checks` | contrato HTTP | `/healthz` ok+revision; `/login`→200; `/`→redirect a `/login` | `production_smoke.py:6-14` |

`parameters.md` ya documenta 13 de estos (P01, P06, P09-P11, P14, P15, P17, P18, P28, P29 por origen, P32) más tres secundarios (host de producción, versión de Python, lista de checks requeridos); el resto son el delta que un scaffolder tendría que generar.

---

## §3 — Huecos (lo que no existe hoy)

| # | Hueco | Qué debe hacer | Activo que orquesta | Prioridad |
|---|---|---|---|---|
| G1 | **Scaffolder** (no existe) | Copiar los activos de §1 al destino, sustituir cada parámetro de §2 y dejar un PR único de gobernanza (porting-guide Fase 3). | §1 completo + `skills/ci-pattern/references/porting-guide.md` | Alta |
| G2 | **Verificador de adopción / self-check** (no existe) | Recorrer las Fases 0-5 del porting-guide y fallar si una fase no tiene su evidencia; comprobar que cada contrato ejecutó contra datos reales del destino. | `references/porting-guide.md` + gates de §1 | Alta |
| G3 | **Esquema `ci-pattern.yaml` + validador** (no existe) | Declarar los ~48 parámetros de §2 con tipo, default y rango; el validador rechaza una clave desconocida o un valor fuera de rango antes de que el scaffolder escriba. | §2 + `preflight.py` (patrón de fallo-fuerte) | Alta |
| G4 | **Plantilla de job para preflight de tooling del runner** (parcial) | Paquete reusable de los chequeos de herramienta (`uv`, `docker info` bajo `timeout`, comandos ausentes) hoy embebidos en `ci.yml`/`check_workflows.py`. | `check_workflows.py` + `setup-python/action.yml` | Media |
| G5 | **Bloque dispatcher generado para `AGENTS.md`** (no existe como generador) | Generar la tabla HR+trigger del patrón en el `AGENTS.md` del destino sin prosa manual. | `skills/ci-pattern/SKILL.md` (§2/§3) | Media |
| G6 | **Plantilla de doc de inventario de gates** (contenido sin parametrizar) | `ci-gate-inventory.md` con filas vacías y criterio, no congelada al origen de 61 líneas. | `docs/quality/ci-gate-inventory.md` | Media |
| G7 | **Modo `--dry-run` del scaffolder** (no existe) | Imprimir el plan de ficheros y parámetros sin escribir; prerequisito de G1. | G1 + G3 | Alta |
| G8 | **Contrato de idempotencia** (no existe) | Re-ejecutar el scaffolder no debe alterar bytes ya generados ni duplicar bloques; hash por fichero generado. | G1 | Alta |
| G9 | **Reconciliación del esquema de política de gates** (divergencia real) | `parameters.md` documenta `policy_version`/`activation_snapshot`/`grandfathered_entries`, pero `ci-gate-policy.json` y `preflight.py:62` usan `enforcement`/`reason`/`dormant_since`. Hay que unificar el esquema antes de empaquetar. | `parameters.md` + `preflight.py:62` + `test_ci_gate_policy.py` | Alta |
| G10 | **Plantilla de encargo de delegación** (no existe como asset) | Campos obligatorios: repo, remote verificado, SHA, worktree, rama, superficies editables, `verified_at` con comando y salida real. Cierra HR-25 y el "repo equivocado". | HR-24/HR-25 de `SKILL.md` | Alta |
| G11 | **Helper generador de nombre de rama** (no existe; solo el gate) | Dado `#N` y tipo, construir `<tipo>/<N>-<slug>` y validarlo con el gate; nunca dejar el nombre a la memoria. | `check_branch_name.py` | Alta |
| G12 | **Guard de sonda de solo lectura** (no existe) | Envolver cualquier «probe» en un runner que solo permita `GET`; un PATCH exige confirmación explícita y queda auditado. | `check_release_evidence.py` / patrón de smoke | Media |

---

## §4 — Auditoría de determinismo (fallos de la sesión)

| Fallo observado | Por qué ocurrió | Mecanismo que lo haría imposible | Clase | ¿Existe? |
|---|---|---|---|---|
| Nombre de rama sin el número de issue (5×) | El nombre se escribió a mano; la regla es una convención, no un generador | G11: helper `branch-name new --issue N --type T` que emite y valida el nombre antes del `checkout -b` | Script | No (solo el gate) |
| Superficies de edición prescritas de memoria | El orquestador citó un snapshot sin volver a inventariarlo | Comando de inventario obligatorio (`git ls-files`, `preflight --list`) y campo `verified_at` en el encargo (G10) | Script + plantilla | No |
| Repo equivocado en una tarea delegada | El encargo nombraba el repo en prosa, sin remote verificado | G10 exige `git remote get-url origin` leído de vuelta y estampado en el encargo | Plantilla + verificador | No |
| Prescribir de memoria (conteo de pasos de preflight, §15.8, SHA de slice) | Una afirmación sin comando adjunto; HR-25 es una regla sin puerta automática | Que toda prescripción lleve `comando + salida` verificable; el verificador de adopción (G2) rechaza una prescripción sin esa evidencia | Gate (parcial) | Regla sí; automatización no |
| Esperas no deterministas (watch loops, pollers) | La IA actuó de vigía por defecto | Jerarquía mecanismo>script>IA (HR-23): auto-merge + `allow_update_branch` + sonda única con deadline | Capacidad de harness + script | Regla sí; cableado de auto-merge documentado, no empaquetado |
| Una «sonda» emitió un PATCH | El probe tenía credenciales de escritura y no había guard | G12: runner de solo lectura por diseño; un PATCH exige confirmación y auditoría | Script + gate | No |
| Adopción del patrón sin el checklist | El STOP gate es prosa en `SKILL.md §1`; nada lo ejecuta | G2: verificador que falla si las fases 0-5 no están cerradas; el STOP gate deja de depender de la lectura humana | Gate + fichero generado | STOP gate sí; verificador no |

### Lo que NO puede hacerse determinista

- **La completitud de una spec de issue** (`check_issue_specs.py` prueba estructura, no que el requisito exista). Procedimiento acotado: aprobador nombrado + issue `status:approved` explícita.
- **La clasificación de la causa raíz de un rojo** (código vs infra vs flake). Procedimiento acotado: paso exacto vía `gh api jobs/<id>` + regla 8 del playbook, decisión humana registrada.
- **La elección entre partir/encadenar/`size:exception`.** Procedimiento acotado: orden de escape de `chained-pr` y motivo escrito obligatorio.
- **El juicio de calidad documental** (`check_alantyle` es informativo). Procedimiento acotado: lente de revisión obligatoria.
- **Si una edición es material** (bump de versión, re-medición de baseline). Procedimiento acotado: regla de reporte y revisión humana.
- **La revisión de un diff high-stakes** (consentimiento, veredicto). Procedimiento acotado: `judgment-day` con rondas limitadas y disposición del operador.

---

## Orden de construcción recomendado (scaffolder + verificador)

1. **Primero (sin esto, todo lo demás cambia de forma):** G9 (unificar el esquema de política) y G3 (esquema `ci-pattern.yaml` + validador). El esquema es el contrato; los activos se adaptan a él, nunca al revés.
2. **Segundo (núcleo mínimo ejecutable):** empaquetar `check_preflight` (§1.1), `check_issue_specs`+`check_branch_name` (§1.2), `check_pr_size`+plantillas (§1.3) y el asset `required-jobs` ya portable (§1.4). Añadir G7 (`--dry-run`) y G8 (idempotencia) al scaffolder en el mismo tramo.
3. **Tercero (evidencia y estructura):** §1.7 (release/smoke/evidence) y §1.8 (ratchets + `_ratchet_deadline`). Suman valor solo con `deploy.yml` presente (Fase 0/G4.5 del porting-guide).
4. **Cuarto (verificación):** G2 (verificador de adopción) + G10 (plantilla de encargo) + G6 (plantilla de doc de inventario). Cierran el STOP gate con evidencia, no con prosa.
5. **Último (específico del origen, puede esperar):** G4, G5, G12 y los detectores APAP (`check_rules`, `check_layers`, `check_slice_completeness`, `check_migration_boundaries`, `check_alantyle`, `check_complexity`, `check_docstring_coverage`) y `deploy.yml`/`codeql.yml`/`minio-replica.yml`/`main-audit.yml`.
