# #1129 (CI perfecto) — Roadmap operacional

> Working doc como el resto de `odd/tasks/*.md`. Guía para que cualquier
> agente AI ataque las 12 issues de la campaña CI-perfection (#1118-#1129)
> en orden, sin re-derivar contexto. Castellano peninsular formal.
>
> Insumos previos (leer primero si la duda aparece):
> - `odd/tasks/ci-audit-friction-log.md` — fricciones vividas F-001..F-007.
> - `odd/tasks/ci-audit/wu2-ciyml-findings.md` — F1..F5 sobre `ci.yml`.
> - `odd/tasks/ci-audit/wu3-deploy-findings.md` — F-01..F-13 sobre `deploy.yml` + `check_release_evidence.py`.
> - `odd/tasks/ci-audit/wu4-gates-findings.md` — G1..G9 sobre `pr-size`/`pr-name`/`issue-spec`.
> - `odd/tasks/ci-audit/wu5-scripts-findings.md` — Top-5 + per-script sobre `scripts/check_*.py`.
> - Épica padre: issue #935 (memoria de diseño: «gates must not penalize splitting work»).

---

## 1. Objetivo dual

La épica #935 persigue simultáneamente dos fines:

1. **CI perfecto en este repo** — que cada ejecución roja signifique un defecto
   real y cada verde signifique que se probó lo que importa; que la señal sea
   reproducible en local y que el ciclo sea trazable. Es el destino que las
   11 issues operativas (#1118-#1128) deben materializar.
2. **Skill portable para otros repos web** — destilar el patrón resultante
   en una skill reutilizable, con principios, catálogo de gates, procedimiento
   de adopción y anti-patrones con evidencia. Es el contenido de la issue
   #1129, que cierra la épica.

Las dos metas son interdependientes: la skill (#1129) presupone que las
olas 1-3 están aterrizadas; las olas 1-3 presuponen que se documenta cada
fricción para alimentar la destilación.

---

## 2. Mapa de issues con olas y grafo de dependencias

### 2.1. Ola 0 — Estado actual y prerrequisitos

Antes de abrir cualquier issue nueva, el repo debe estar en este estado:

- **PR #1111 verde**: el run más reciente (`36595438537`) ya muestra todos
  los checks en `SUCCESS` (`lint`, `required`, `pr-size / pr-size`,
  `issue-spec`, `build`, `e2e`, `integration`, `security`, `test`,
  `typecheck`, `verify-fallback-ready`, `CodeQL`, `GitGuardian`). El PR
  sigue `OPEN` con `mergeable: MERGEABLE`. **Estado:** listo para merge
  según autorización standing de §15.6. Verificar rebase contra `main`
  actual antes de declarar mergeable.
- **PR #962 mergeado** (rama `chore/933-ci-on-stacked-prs`): elimina
  `branches: [main, staging]` de `ci.yml` y `codeql.yml`. Habilita que
  PRs encadenados (`base != main`) ejecuten la suite completa; sin este
  merge, parte del grafo de Ola 3 queda cojo.
- **PR #1110 mergeado** (rama `chore/1082-release-e2e-gate-per-sha`):
  introduce el contrato per-SHA (`release/e2e-record` + `release/e2e-gate`
  + `scripts/check_release_evidence.py`). Habilita Ola 2. **Requiere
  bootstrap manual** (registrar `release/e2e-production=success` o
  `=skipped:bootstrap-before-1082-gate` sobre SHA `460c56f1` antes del
  primer deploy post-merge — la issue #1124 cierra esa deuda).

### 2.2. Ola 1 — Paralelizable (con caveats de ownership)

Cinco issues independientes en superficie, con un solapamiento real de
archivos en el subconjunto `{pr-size.yml, check_pr_size.py, ci.yml}`.

| # | Issue | Archivos principales | Bloquea | Bloqueada por |
|---|---|---|---|---|
| #1118 | root cause en `required` | `scripts/check_required_jobs.py` (+ test) | nada | nada |
| #1119 | preflight canónico | `scripts/preflight.py` (nuevo) + `CONTRIBUTING.md` | nada | nada |
| #1120 | ratchet `--update-baseline` | `scripts/check_ruff_ratchet.py` | nada | nada |
| #1121 | `size:exception` en datos | `pr-size.yml` + `check_pr_size.py` | nada | nada |
| #1122 | re-lectura en `labeled` | `ci.yml` + `pr-size.yml` | nada | nada |

**Reglas de paralelización:**

- **#1118** y **#1119** no comparten archivos; pueden ir en worktrees
  paralelos.
- **#1120** no toca ni `ci.yml` ni `pr-size.yml`; libre.
- **#1121** y **#1122** comparten `pr-size.yml` y la lógica de
  excepción. **Cadena interna:** #1121 primero (deja el gate
  determinista), #1122 después (extiende triggers). Excepción: si el
  approach de #1121 deja la label dance atrás del todo, #1122 puede
  ejecutarse en paralelo. Decisión del worker que arranque #1121.
- Los cinco issues están `status:approved`.

### 2.3. Ola 2 — Cadena sobre `deploy.yml` + `check_release_evidence.py`

Las tres issues tocan los mismos archivos (`deploy.yml`,
`scripts/check_release_evidence.py`, `tests/test_*.py`). **No se pueden
paralelizar** sin conflicto de merge; **no se puede empezar sin #1110
mergeado** (introducen contrato nuevo en código no vigente).

```
#1123 (operator verdicts) → #1124 (bootstrap) → #1125 (harden)
```

- **#1123 — operator verdicts**: `release-e2e-record` no debe sobrescribir
  un veredicto terminal existente; el fallo del record job debe ser
  fail-loud post-deploy. **Razón de ir primero:** deja el estado de
  evidencia determinista antes de tocar el bootstrap.
- **#1124 — bootstrap automático**: degradación explícita para SHAs
  anteriores al gate (deja atrás el bootstrap manual sobre `460c56f1`).
  **Razón de ir segundo:** presupone que la superficie de verdicts es
  estable (la fix de #1123); si no, la marca de bootstrap puede caer
  sobre un veredicto que se va a pisar.
- **#1125 — harden**: empates `same_second`, paginación >100 estados,
  exit codes (`JSONDecodeError` → exit 1 con `code="malformed"`),
  `branch=main` parametrizable. **Razón de ir último:** lógica pura
  con tests exhaustivos; presupone contrato de evidencia cerrado.

Solo #1123 y #1124 están `status:approved`; **#1125 debe recibir
`status:approved` antes de empezar**.

### 2.4. Ola 3 — Bordes del gate nuevo y poda

Tres issues con dependencias distintas:

| # | Issue | Bloqueada por |
|---|---|---|
| #1126 | CodeQL paths YAML | nada |
| #1127 | issue-spec edges | **#1111 mergeado** |
| #1128 | poda de gates sin cobertura | **Olas 1 + 2 completas** |

- **#1126** puede arrancar en paralelo con Ola 1 — solo toca
  `.github/workflows/codeql.yml`. **Nota:** aún no tiene `status:approved`;
  etiquetar antes de empezar.
- **#1127** requiere el gate `issue-spec` en `main` (#1111 mergeado), porque
  endurece sus exemptions (R1-exempt-branch-widen,
  R3-archive-exemption-untested-scope, R3-branch-violations-path-untested
  según lentes de la review nativa de #1111). **Mismo ownership** que
  #1111 (`scripts/check_issue_specs.py`); ejecutar en worktree dedicado.
  Etiquetar antes de empezar.
- **#1128** es la poda. Requiere haber aterrizado Olas 1 + 2 para que el
  inventario refleje el estado final. Audita cada gate del inventario
  (`docs/quality/ci-gate-inventory.md`) con run-IDs de cuándo detectó
  un defecto real por última vez, y emite PR por cada gate a podar con
  tests del workflow actualizados. **Riesgo principal:** podar un gate
  que las olas 1-2 iban a endurecer — el orden protege contra eso.
  Etiquetar antes de empezar.

### 2.5. Ola 4 — Destilación a skill

- **#1129** — skill portable. **Solo arranca cuando:**
  1. Las 11 issues operativas (#1118-#1128) están mergeadas y el
     `ci-audit-friction-log.md` está 100 % `fixed` o `wontfix`.
  2. `make verify` corre verde en `main` en menos de N minutos (baseline
     medible contra run actual).
  3. Se ha hecho una prueba de fuego de adopción: aplicar el
     procedimiento a un repo web real (o dry-run documentado) con
     evidencia.
- Skill en castellano (consistente con el catálogo del repo) o en
  inglés según el catálogo destino; estructura según `skill-style-guide`
  con frontmatter válido. Auditar con `skill-improver` antes de cerrar.
- **No etiquetada aún**; etiquetar antes de empezar.

### 2.6. Resumen visual del grafo

```
                       Ola 0
            (PR #1111 verde + #962/#1110 mergeados)
                          │
            ┌─────────────┴─────────────┐
            │                           │
         Ola 1                        Ola 3
   #1118 ─┐                            ┌─ #1126
   #1119 ─┤ (paralelo, salvo          │
   #1120 ─┤  cadena interna           ├─ #1127 (necesita #1111)
   #1121 ─┤  #1121→#1122)             │
   #1122 ─┘                            └─ #1128 (necesita Olas 1+2)
            │                           │
            └─────────────┬─────────────┘
                          │
                       Ola 2 (cadena)
            #1123 → #1124 → #1125 (necesita #1110)
                          │
                          ▼
                       Ola 4
                       #1129 (cierra #935)
```

---

## 3. Contrato de ataque por issue (plantilla)

Cada issue sigue este contrato, sin excepciones:

1. **Autorización previa.** La issue `#N` debe tener `status:approved`.
   Hoy: #1118-#1124 sí; **#1125-#1129 deben etiquetarse antes de empezar**
   (operación administrativa, no requiere código). Las issues de Ola 2
   están `status:approved` y deben esperar al merge de #1110.
2. **Rama y worktree.** `git worktree add
   /home/ubuntu/repos/apap-app-worktrees/<N>-<slug> -b
   <tipo>/<N>-<slug> main`. Validar nombre con `scripts/check_branch_name.py`.
   Pre-MVP single-branch (P4): la rama apunta a `main`.
3. **Sincronización.** `uv sync --frozen --extra dev` en el worktree.
4. **TDD RED → GREEN → REFACTOR.** Cuando aplique un test determinista
   ejecutable y un resultado esperado claro, observar RED antes del
   fix. Documentar la salida del RED en el cuerpo del PR. Para trabajo
   pasivo (docs, refactors sin cambio de comportamiento), documentar la
   excepción al TDD explícitamente.
5. **Preflight local.** `make verify` en verde antes del primer commit.
   Cobertura ≥ 85 % en lo tocado; ratchets shrink-only; mypy sin errores
   en archivos tocados.
6. **Presupuesto 400 líneas.** `git diff --stat` antes de pedir
   revisión. Si excede, encadenar vía `chained-pr` o declarar
   `size-exception-reason: <por qué>` en el cuerpo (verificar que
   `pr-size` re-lee el label — la fix de #1121 lo deja determinista).
7. **Self-review.** Lente `code-review-expert` (subagente) sobre el diff
   antes de `gh pr create`. Lentes adicionales cuando aplique:
   `judgment-day` para diffs high-stakes (auth, secrets, migrations,
   SQL crudo — la issue #1123 entra por tocar `release-e2e-record` y
   la manipulación de estados de GitHub).
8. **Anti-slop.** Antes del commit, ejecutar el self-check de
   `gentle-ai-ai-slop-discipline` (4 preguntas, 3 firmas, scope-boundary
   guard para subagentes).
9. **Evidencia run-ID.** Incluir en el cuerpo del PR el `gh run view
   <id> --json conclusion` de la corrida verde de la rama propia (no
   del PR aún).
10. **PR body.** `Closes #<N>` + `Refs #935` + bloque de evidencia
    ejecutable (comandos y resultados literales). Sin atribución de IA en
    el footer; sin `Co-Authored-By: ...` en commits.
11. **Friction log (regla transversal).** Toda fricción experimentada
    durante el trabajo (local-CI drift, rerun manual, gate mudo, etc.)
    se registra en `odd/tasks/ci-audit-friction-log.md` con formato
    `F-0NN` **antes** de continuar. Una fricción no documentada es una
    oportunidad perdida para la skill #1129.
12. **Merge.** Con CI verde contra `main` actual (rebase si la base
    avanzó) y autorización standing activa (§15.6) — `--merge` con
    `--no-ff`, nunca `--delete-branch` en remoto.

---

## 4. Detalle por issue

### 4.1. Ola 1

#### #1118 — `ci: surface root cause in required aggregator`

- **Files owned:** `scripts/check_required_jobs.py` (~60-80 LOC), nuevo
  test en `tests/test_check_required_jobs.py` (~30 LOC).
- **DoD técnico:** el script imprime primero los jobs con `result='failure'`
  como «root cause» y agrupa los `skipped` como `skipped (upstream: <causa>)`;
  el test fija el formato nuevo con un fixture de 1 fallo + N cascadas;
  el formato legacy queda detrás de `--legacy-format` durante una release
  para mantener verdes los `tests/test_ci_workflow.py::test_required_aggregator_*`.
- **Anti-patrón a evitar:** emitir una línea `FAIL` por cada `skipped`
  en cascada (estado actual — run 36592991754 muestra 7 rojos por una
  sola causa). Mantener la jerarquía causa → consecuencias en una sola
  pasada, sin volver a recorrer el grafo dos veces.

#### #1119 — `ci: canonical preflight command with local-CI parity`

- **Files owned:** `scripts/preflight.py` (nuevo, ~50-100 LOC),
  `CONTRIBUTING.md` (sección preflight), test anti-drift nuevo.
- **DoD técnico:** el preflight ejecuta exactamente el mismo set de reglas
  que el job `lint` de `ci.yml` (ruff estándar + ratchet + formato); el
  test parsea `ci.yml` y compara su set con el del preflight (asserts
  `set(preflight_steps) == set(ci_lint_steps)`); `CONTRIBUTING.md` lo
  nombra como LA forma de validar antes de pushear; alternativa
  opcional: alias `make preflight` que apunte al mismo recipe.
- **Anti-patrón a evitar:** ejecutar `ruff check .` solo (que no ve los
  rulesets extendidos `S,ERA,ARG,FAST,N,C901,PLR,SIM,RET,TRY,PTH` —
  gap documentado en wu5 Top-5 #1 con caso real TRY003 188>186 invisible
  en local). El preflight debe ser lo que corre CI, no lo que la
  documentación dice que «debería bastar».

#### #1120 — `ci: ratchet auto lock-in (--update-baseline)`

- **Files owned:** `scripts/check_ruff_ratchet.py` (~40-60 LOC), test
  nuevo del flag.
- **DoD técnico:** `--update-baseline` reescribe las constantes cuando
  el conteo baja (nunca sube) con diff legible; test cubre que baja
  exactamente al conteo, que nunca sube, y que es idempotente. Commit
  de lock-in para las 9 mejoras activas (`ARG001 28<31`, `C901 17<19`,
  `PLR0911 10<12`, `PLR0912 9<12`, `S101 4<6`, `S603 0<2`,
  `SIM105 14<15`, `SIM108 4<6`, `TRY003`).
- **Anti-patrón a evitar:** abrir un job semanal que automatice el
  lock-in sin gate humano (la propuesta del cuerpo lo marca como
  «opcional documentado»). El shrink-only se mantiene por construcción:
  el flag solo opera cuando `medido < baseline`. Si pasa a `medido >
  baseline`, el script aborta y el humano decide.

#### #1121 — `ci: declare size:exception in data; gate parses size-exception-reason`

- **Files owned:** `pr-size.yml` (~25 LOC nuevos — fetch del body),
  `scripts/check_pr_size.py` (nuevo parámetro `HAS_REASON`), test nuevo
  del parser, `CONTRIBUTING.md` (alinear), `.github/PULL_REQUEST_TEMPLATE.md`
  (sección ya existe; verificar), `docs/quality/ci-gate-inventory.md`.
- **DoD técnico:** `check_pr_size.py` acepta la excepción cuando el cuerpo
  del PR contiene `^size-exception-reason:\s*\S+` (regex determinista, una
  línea, no vacía); el label `size:exception` pasa a informativo/opcional;
  tests del parser cubren: válida, vacía, multilínea, ausente. El gate
  queda auto-contenido y re-leíble en cada run (sin rerun manual).
- **Anti-patrón a evitar:** quedarse en el gesto (label + texto a mano,
  como hoy — ver `wu4-gates-findings.md` G2: 4 lugares documentan el
  campo, 0 lugares lo parsean). La regla de diseño de la épica #935 es
  explícita: «si la política pide trocear, ningún gate puede penalizar
  el troceo; la excepción debe declararse en datos, no en gestos».

#### #1122 — `ci: re-read labels on labeled events (size:exception, chain:partial)`

- **Files owned:** `ci.yml` (~15 LOC — extender `pull_request:` types
  con `labeled, unlabeled`), `pr-size.yml` (verificar el `concurrency`
  suffix que ya separa `label`/`call` por trigger, wu4 keep-list #1),
  test nuevo que fija los tipos en el trigger.
- **DoD técnico:** ambos gates (`pr-size` y `issue-spec`) re-evalúan en
  el evento `labeled`/`unlabeled` de forma idempotente y barata, con
  concurrency group que aísla cada path (`pr-size-${{ github.ref }}-{label|call}`
  ya cubre `pr-size.yml`; replicar para `issue-spec`). Tests fijan que
  añadir `size:exception` o `chain:partial` post-apertura deja los
  checks en verde sin rerun manual.
- **Anti-patrón a evitar:** publicar un workaround prose-only (del tipo
  «haz `gh run rerun <id>`» — el workaround actual en CONTRIBUTING.md).
  El gate tiene que leer el label cuando cambia el label. La
  single-publisher rule (#890) se preserva replicando el patrón de
  `pr-size.yml`, no inventando uno nuevo.

### 4.2. Ola 2

#### #1123 — `deploy: protect operator verdicts from re-run overwrite`

- **Files owned:** `deploy.yml` (job `release-e2e-record` + summary),
  `tests/test_deploy_workflow.py` (test nuevo `test_release_e2e_record_does_not_overwrite_existing_verdict`).
- **DoD técnico:** `release-e2e-record` consulta el estado actual antes
  de postear `pending`; si el último estado es `success` o `failure`,
  sale con exit 0 y un notice nombrando el veredicto preservado. El
  fallo del record job se surfacea en el summary del deploy (`::error::`
  si `needs.release-e2e-record.result != 'success'`).
- **Anti-patrón a evitar:** POST incondicional de `pending` (estado actual
  — destruye evidencia operator en silencio, ver wu3 F-02 marcado como
  CRITICAL con caso real de re-run por flaky Trivy + smoke-test flake).
  La evidencia per-SHA es la fuente de verdad para el gate del próximo
  deploy; perderla bloquea despliegues legítimos sin señal clara.

#### #1124 — `deploy: automatic bootstrap for per-revision evidence gates`

- **Files owned:** `deploy.yml` (rama `prev_sha` con sentinel-date
  check), `scripts/check_release_evidence.py` (nuevo verdict
  `bootstrap:<motivo>`), `tests/test_check_release_evidence.py` (test
  que cubre marca única con motivo), `docs/runbooks/e2e-production.md`
  (actualizar bootstrap).
- **DoD técnico:** cuando `prev_sha` resuelve y su estado es `absent`,
  comparar fecha del commit contra un sentinel (merge de PR que
  introduce el gate). Si el SHA es anterior, exit 0 con notice
  nombrando la ventana de bootstrap y exigiendo motivo obligatorio.
  Test cubre: SHA previo sin estado + marca con motivo → pass una vez;
  SHA previo sin estado + sin marca → fail-closed; SHA posterior al
  sentinel + absent → fail-closed normal.
- **Anti-patrón a evitar:** quedarse en bootstrap manual vía runbook
  (estado actual — el operador debe correr `gh api .../statuses/${SHA}`
  con `success` o `skipped:<motivo>`; el mensaje del deploy nombra el
  SHA pero no apunta a la sección del runbook). La regla de diseño
  (d) de #935 es categórica: «every new gate ships its automatic
  bootstrap or an explicit degradation for revisions older than the
  gate». La degradación explícita en código cumple; el bootstrap
  manual en prosa no.

#### #1125 — `deploy: harden check_release_evidence (ties, pagination, exit codes, branch pin)`

- **Files owned:** `scripts/check_release_evidence.py` (~40 LOC),
  `tests/test_check_release_evidence.py` (cuatro tests nuevos),
  `deploy.yml` (parametrizar `branch=main`).
- **DoD técnico:** cuatro fixes independientes:
  1. `_latest_status` usa `(created_at, id)` como clave total (no
     `max(created_at)` solo) — test cubre empates `same_second`.
  2. Paginación hasta encontrar el entry o confirmar agotamiento —
     test cubre status list truncada antes del entry relevante.
  3. `JSONDecodeError` retorna `Verdict(ok=False, code="malformed")` y
     exit 1; reservar exit 2 solo para CLI usage errors — test cubre
     ambos caminos.
  4. `branch=main` reemplazado por `branch=${GITHUB_REF#refs/heads/}`
     (compatible con staging si se reactiva).
- **Anti-patrón a evitar:** mezclar fix de bug con fix de contrato sin
  separar tests (wu3 F-10 muestra que mezclar puede ocultar regresiones
  verificadas como `set -euo pipefail` ya estaba presente). Cada uno
  de los cuatro puntos tiene su test aislado.

### 4.3. Ola 3

#### #1126 — `ci: trigger CodeQL on workflow YAML changes`

- **Files owned:** `.github/workflows/codeql.yml` (~3 LOC), test nuevo
  en `tests/test_ci_workflow.py` que fija el paths filter.
- **DoD técnico:** `paths` extendido a `["**.py", ".github/workflows/**/*.yml",
  ".github/workflows/**/*.yaml"]` (alternativa: drop `paths:` completo
  con coste de más runs por PR). Test fija el patrón. CI real: PR
  propio tocando un YAML dispara CodeQL (evidencia run-ID).
- **Anti-patrón a evitar:** la opción B de wu2 F4 (drop `paths:`) sin
  evaluar el coste — CodeQL en cada PR es ruido si los YAML-driven
  vulns son improbables. La opción A (extensión quirúrgica) es la
  mínima-máxima; preserva el filtro de docs/UI.

#### #1127 — `ci: harden issue-spec edges (exemptions, cross-repo signal, docs alignment)`

- **Files owned:** `scripts/check_issue_specs.py` (tests de exenciones
  + logging cross-repo), `tests/test_check_issue_specs.py` (~80 LOC
  de tests de scope), `CONTRIBUTING.md` (alinear con lo que el gate
  evalúa), `docs/quality/ci-gate-inventory.md`.
- **DoD técnico:**
  1. Tests de scope completos para exenciones (`archive/`, `skill-fleet/`,
     `main`, `dependabot[bot]`) según hallazgos R1/R3 de la review
     nativa de #1111.
  2. `closingIssuesReferences` cross-repo: warning en output (no
     fallo), nombre el repo descartado.
  3. Documentación alineada con lo que el gate realmente evalúa
     (rama + label + `closingIssuesReferences` — nada de prosa).
- **Anti-patrón a evitar:** reintroducir parseo de prosa en el cuerpo
  del PR (anti-patrón original que produjo el 404 de la ejecución
  36151968865 arreglado en #960). La postura del gate debe ser
  «estructura sí, prosa no».

#### #1128 — `ci: prune gates without real coverage`

- **Files owned:** `docs/quality/ci-gate-inventory.md` (tabla de
  evidencia por gate con run-IDs), `.github/workflows/*.yml` (PR por
  cada gate a podar), `tests/test_ci_workflow.py` (tests del workflow
  actualizados al remover steps).
- **DoD técnico:** análisis por gate del inventario con columnas
  «Última vez que detectó un defecto real (run-ID)», «Fricción
  observada», «Decisión: mantener / podar / fundir». PR por cada gate
  a podar, con su commit de remoción + tests del workflow. Comparativa
  pre/post de tiempos del job `lint` y `test` como evidencia de ahorro.
- **Anti-patrón a evitar:** podar gates con defectos reales
  documentados (los `keep-list` de wu2/wu3/wu5 son la línea base
  explícita — ver wu2 keep-list con 8 patrones defendidos por tests,
  wu3 keep-list con 10 patrones, wu5 keep-list con 5). El inventario
  ya marca varios como «Informativo» — podar los que ni siquiera
  llegaron a ese estado.

### 4.4. Ola 4

#### #1129 — `epic: portable perfect-CI skill for web repos`

- **Files owned:** nueva skill `skills/perfect-ci/SKILL.md` (o
  equivalente en el catálogo del repo, castellano o inglés según
  destino), frontmatter válido según `skill-style-guide`.
- **DoD técnico:** ver §5 abajo. Estructura, secciones, principios,
  catálogo, procedimiento, anti-patrones, keep-lists. Auditar con
  `skill-improver`. Prueba de fuego: aplicar el procedimiento a un
  repo web real o dry-run documentado. Friction log 100 %
  `fixed`/`wontfix` antes de cerrar la épica.

---

## 5. Para la skill #1129 — Qué destilar

La skill portable hereda de cuatro fuentes:

1. **Principios** (del cuerpo de #1129 + memoria de diseño de #935):
   - **Fail-loud**: cada defecto real → rojo; cada verde → evidencia
     de lo que se probó. Sin rojos por cascades ni verdes por
     auto-exención.
   - **Shrink-only**: los ratchets solo bajan; el lock-in se automatiza
     (#1120) pero la dirección nunca se invierte.
   - **Least-privilege**: `permissions:` por job, no por workflow
     (issue #879 / `repository-delivery-governance` HR-6).
   - **Excepciones-en-datos**: si la política pide trocear, ningún
     gate penaliza el troceo (#1121 + #935).
   - **Bootstrap-de-gates**: cada gate nuevo trae bootstrap automático
     o degradación explícita (#1124 + #935 regla (d)).
   - **Causa-raíz-visible**: el agregador dice cuál es el job raíz y
     etiqueta los cascades (#1118).

2. **Catálogo de gates con su función, test y trampa** (de wu2/wu3/wu5):
   - Lista tabular por gate: qué detecta, qué test lo fija, qué
     trampa histórica lo ha afectado. Ejemplos del repo: `pr-size`,
     `issue-spec`, `required`, `release-e2e-gate`, `codeql`,
     `ruff-ratchet`, `complexity`, `module-size`, `route-size`,
     `layers`, `import-cycles`, `mutation`, `security`,
     `verify-fallback-ready`, `ui-detection`. La skill debe permitir
   instanciar este catálogo en un repo nuevo con auditoría previa.

3. **Procedimiento de adopción incremental** (de wu1-wu5 + la cadena
   Ola 0 → Ola 4): auditoría → baseline → gates → preflight → poda →
   destilación. Cada paso con su entregable verificable.

4. **Anti-patrones con evidencia run-ID** (de la friction log + los
   informes wu):
   - **Prosa-parseo**: parsear el cuerpo del PR para trazabilidad
     (anti-patrón #931 → fix #952 → fix determinista #956).
   - **Labels-carrera**: gates que dependen de labels pero no se
     re-evalúan en `labeled` (#926 → #936; gap #941 + nuevo #1122).
   - **Máscara-de-causa-raíz**: agregador que enumera cascades sin
     jerarquía (run 36592991754 → #1118).
   - **Veredictos-pisados**: jobs que sobrescriben estados terminales
     sin guard (wu3 F-02 → #1123).
   - **Bootstrap-manual-en-prosa**: gates nuevos sin bootstrap en
     código (wu3 F-01 → #1124).
   - **BASELINE-edit-manual**: ratchets sin `--update-baseline` (wu5
     Top-5 #2 → #1120).
   - **size:exception-como-gesto**: label + texto a mano, gate mudo
     (wu4 G2 → #1121).

5. **Keep-lists como checklist de revisión** (de wu2/wu3/wu5): cada
   keep-list del repo es un patrón que la skill debe proponer
   activamente. Ejemplos: SHA-pinning de actions, digest-pinning de
   images, per-job `permissions:`, per-ref concurrency, etc.

---

## 6. Reglas transversales

1. **Friction log (regla obligatoria).** Toda fricción experimentada
   durante la ejecución de cualquier issue se registra en
   `odd/tasks/ci-audit-friction-log.md` con formato `F-0NN` **antes
   de continuar**. El formato sigue el patrón de F-001..F-007: estado
   (`open`/`fixed`/`wontfix`), experiencia vivida, causa raíz,
   evidencia (run-ID, comando, output), remedio propuesto. Una
   fricción no documentada es una oportunidad perdida para la skill
   #1129 y rompe la regla de P3 (los documentos reflejan el código).

2. **Memoria Engram.** Tras cada merge, `mem_save` con `topic_key`
   estable bajo `apap/<issue>` o `apap/ci-perfect/<tema>`. Esto
   permite la recuperación cross-session y alimenta la destilación
   de la skill.

3. **Conventional commits sin atribución IA.** Mensaje en
   castellano o inglés según scope (consistente con `CONTRIBUTING.md`
   §Castellano peninsular en artefactos raíz, inglés en código).
   Sin `Co-Authored-By: ... <AI>`. Sin footer de IA en el body.

4. **Pre-MVP single-branch (P4).** Todo PR contra `main`. El flip a
   `staging` requiere declaración explícita del usuario. La fix de
   #1125 (parametrizar `branch=main`) deja el gate listo pero no
   activa `staging`.

5. **Memoria de la épica padre.** El cuerpo de #935 y el cuerpo de
   #1129 ya enuncia el principio rector: «la CI no impone fricción
   que la industria no imponga. Un gate bloqueante solo se mantiene
   si detecta defectos reales o es práctica estándar». Cualquier
   propuesta de gate nuevo debe acreditar ambos criterios.

---

## 7. Estado actual (snapshot 2026-09-29)

| Issue | Estado | `status:approved` | Bloqueada por |
|---|---|---|---|
| #1118 | abierta | sí | nada |
| #1119 | abierta | sí | nada |
| #1120 | abierta | sí | nada |
| #1121 | abierta | sí | nada |
| #1122 | abierta | sí | nada (cadena con #1121) |
| #1123 | abierta | sí | #1110 mergeado |
| #1124 | abierta | sí | #1110 mergeado |
| #1125 | abierta | **NO** (etiquetar antes) | #1110 mergeado |
| #1126 | abierta | **NO** (etiquetar antes) | nada |
| #1127 | abierta | **NO** (etiquetar antes) | #1111 mergeado |
| #1128 | abierta | **NO** (etiquetar antes) | Olas 1 + 2 |
| #1129 | abierta | **NO** (etiquetar antes) | Olas 1 + 2 + 3 |

PRs abiertos: #1111 (mergeable), #962 (mergeable), #1110 (mergeable).

Run-ID de referencia para evidencia inicial: `36592991754` (síntoma
de F-003 / #1118), `36595438537` (PR #1111 verde), `36041158202` y
`36046072242` (#926 / wu4 keep-list #1).

---

## 8. Procedimiento de cierre

Cuando las 12 issues estén mergeadas:

1. Verificar `ci-audit-friction-log.md` con cero entradas `open`.
2. Verificar `docs/quality/ci-gate-inventory.md` consistente con el
   estado real (incluye la poda de #1128).
3. Medir baseline de `make verify` y de `lint`/`test` (tiempo
   mediana en 20 corridas) y archivar en
   `odd/tasks/ci-perfect-roadmap.md` §Estado actual.
4. Crear la skill con su `SKILL.md`, pasar `skill-improver`, y
   ejecutar la prueba de fuego (adopción a un repo web real o
   dry-run documentado).
5. Cerrar #1129 con `Refs #935` y referencia a la skill publicada.
6. Cerrar #935 con checklist completo y enlace a la skill.

Si alguna issue queda bloqueada por una decisión del usuario (no
técnica), etiquetarla `wontfix` en el friction log y abrir issue de
seguimiento en la épica siguiente, no cerrarla en silencio.
