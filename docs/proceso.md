# Proceso de trabajo por issue — APAP_WEB

[Back to Codebase Guide](CODEBASE-GUIDE.md)

El proceso de APAP_WEB garantiza que cada issue llegue de `open` a `closed` preservando el superset funcional del Access legacy, con TDD estricto, trazabilidad por commit y SHA, y refresco del roadmap en la misma sesión de entrega. No posee reglas del proyecto — esas viven en [AGENTS.md](../AGENTS.md) y se aplican en paralelo.

[Quick Navigation](#quick-navigation) · [Roadmap](roadmap.md) · [AGENTS.md](../AGENTS.md) · [README](../README.md)

---

## Quick Navigation

| Sección | Para qué |
|---|---|
| [Core invariants](#core-invariants) | P1–P4: fidelidad legacy, resolución de dudas, docs reflejan código, pre-MVP single-branch. |
| [§1 Pre-flight](#1-pre-flight-cada-sesión-cada-vez) | Comprobaciones de salud del repo al iniciar. |
| [§2 Triaje de la issue](#2-triaje-de-la-issue) | Lectura, clasificación, refresco del roadmap, reconocimiento del dominio. |
| [§3 OpenSpec primero](#3-openspec-primero-cambios-grandes--estructurales) | Cuándo abrir un change SDD en `openspec/changes/<name>/`. |
| [§4 TDD estricto](#4-tdd-estricto-default-para-código) | Ciclo rojo → verde → refactor; reglas para UI, Access y modelo de datos. |
| [§5 Validación local](#5-validación-local-gate-pre-ci) | Comandos exactos del gate antes de commit + push. |
| [§6 Merge a `main`](#6-merge-a-main-regla-151-pre-mvp) | Commit, push, PR, cierre con trazabilidad, limpieza, sync del roadmap. |
| [§7 Triggers stop + consulta](#7-triggers-stop--consulta) | Acciones que requieren OK explícito del usuario. |
| [§8 Anti-patrones a evitar](#8-anti-patrones-a-evitar) | Lista cerrada de lo que está prohibido. |
| [§9 Glosario de comandos rápidos](#9-glosario-de-comandos-rápidos) | Cheatsheet de bash para copiar y pegar. |

**Vinculado a:** [`docs/roadmap.md`](roadmap.md), [`AGENTS.md`](../AGENTS.md) (reglas 14 y 15), `openspec/specs/*`, `openspec/changes/*`, `docs/discovery/*`, `docs/architecture/decisiones-proyecto.md`, `docs/legacy-*`.

**Aplicable a:** todo trabajo en APAP_WEB (código, docs, infra, producto).

---

## Core invariants

Estas premisas rigen **todo** lo que se haga en APAP_WEB. Si una tarea las pone en entredicho, se para y se replantea antes de seguir. Los nombres son citables en review.

- **P1-fidelity-legacy**: la aplicación nueva debe poder sincronizarse con el Access/VBA legacy y preservar **el 100% de las intenciones y funcionalidades del legacy**, más las funcionalidades nuevas acordadas ([`docs/roadmap.md`](roadmap.md) §3 Fases 3–7 + transversales, y `docs/discovery/feature-XX-*.md`). Si el legacy tiene un campo, un estado, un cálculo, un atajo, un informe, un permiso, una validación, un workflow o una transición: la nueva aplicación lo conserva (o lo reemplaza por un equivalente explícitamente acordado y documentado). Las funcionalidades nuevas son aditivas al inventario del legacy. Si descubre que algo del legacy no está en la nueva app, trátelo como bug del nuevo modelo y abra issue con label `gap:legacy`. La trazabilidad es: cada capacidad del legacy → su representación en el modelo nuevo → su cobertura de tests. **Ejemplo:** el legacy en Access tiene un `estado_actual_animal` con transiciones complejas (`docs/legacy-lifecycle-transition-rules.md` y `docs/discovery/state-machines.md`); la nueva implementación tiene que soportar **exactamente** las mismas transiciones, más las nuevas que se acuerden para Fase 4. Un PR que introduzca un nuevo campo debe validar primero que no rompe ninguna regla del legacy para campos equivalentes.
- **P2-domain-doubt-ladder**: cuando algo no quede claro — modelo de datos, regla de negocio, comportamiento esperado, edge case — consultar **en este orden**: (1) `docs/discovery/feature-XX-*.md` (la versión revisada y consolidada, en castellano); (2) [`docs/architecture/decisiones-proyecto.md`](architecture/decisiones-proyecto.md) (si la duda es de producto/UX/arquitectura/proceso); (3) `docs/legacy-<área>.md` (documentación específica del área en el legacy); (4) **el Access directamente vía Dysflow MCP** (`projectId: apap`, `accessPath` resuelve al `.accdb` del legacy). Herramientas canónicas: `dysflow_list_tables`, `dysflow_get_schema`, `dysflow_get_relationships`, `dysflow_query_sql` (modo read), `dysflow_count_rows`, `dysflow_distinct_values`, `dysflow_compare_backends`. Diagnóstico de entorno con `dysflow_doctor`. Solo se permiten los skills **`vba-access`** y **`access-vba-tdd`**. Los demás skills de Access (`access-vba-sync`, `access-query`, `access-form-creation`, `access-sandbox`, etc.) están **excluidos** del workflow de APAP_WEB (ver [roadmap](roadmap.md) §7). Si tras las cuatro capas sigue la duda, **preguntar al usuario**. Nunca asuma equivalencias silenciosamente.
- **P3-docs-reflect-code**: la documentación (incluido este `docs/proceso.md` y [`docs/roadmap.md`](roadmap.md)) **refleja** el código, no al revés. Si divergen, gana **el código** (sea legacy o nuevo). Actualice la doc en la misma sesión en que detecte la divergencia — no es opcional: [`docs/roadmap.md`](roadmap.md) §9 lo exige. `docs/architecture/decisiones-proyecto.md` es el registro de las decisiones que rompieron el molde; cualquier "esto es distinto al legacy porque X" debe constar allí con su fecha, autor y motivo.
- **P4-pre-mvp-single-branch**: todo va a `main` directamente. Una sola rama al final de cada ciclo de merge ([AGENTS.md](../AGENTS.md) §15.2). Reversión post-MVP en §15.4, con **Virginia** como validadora UAT. El flip de fase solo se dispara por instrucción explícita del usuario ("ya tenemos MVC" o equivalente). Invertir el flujo por frases como "ya está" o "vamos cerrando" sin el keyword MVP/MVC está prohibido ([AGENTS.md](../AGENTS.md) §15.4 punto 5).

---

## §1 Pre-flight (cada sesión, cada vez)

Antes de tocar nada, verificar que la realidad del repo coincide con lo que se cree saber:

```bash
codegraph status .
codegraph daemons

git config --get-all gentleai.stagingOnly    # si vuelve a "true", re-leer AGENTS.md §15.4
git branch --show-current
git status --short --branch

gh issue list --repo ardelperal/APAP_WEB --state open --limit 50
git log --oneline -10 main
```

**Salidas esperadas:**

- Index `[OK] Index is up to date`, daemon vivo (PID + `v1.4+`).
- Rama actual: `main` (en pre-MVP). Si es otra distinta, hay feature branch en curso — acabarla o abandonarla primero.
- `gentleai.stagingOnly` = (vacío) para este repo.
- Status limpio o solo con cambios controlados (p. ej. `.atl/skill-registry.md` autogen).

---

## §2 Triaje de la issue

Una issue se aborda en este orden estricto.

### 2.1 Leer la issue, no la respuesta

```bash
gh issue view #N --repo ardelperal/APAP_WEB --comments
```

Extraer: **título + descripción** (qué pide exactamente), **labels** (scope + tipo + prioridad + estado), **issues vinculadas** (bloquea / es bloqueada por cuáles), **criterios de aceptación** explícitos si los hay.

### 2.2 Clasificar

| Label `type:*` | Acción |
|---|---|
| `type:bug` | §4 TDD; regresión o gap:legacy primero si aplica (P1). |
| `type:feature` | §3 OpenSpec primero si >100 líneas o cambio estructural; si no, §4 directo. |
| `type:refactor` | §4 TDD con golden test o contrato preservado; tras TDD, validar que no rompe P1. |
| `type:docs` | Sin TDD; PR directa con diff mínimo y CI verde. |
| `type:chore` / ops | Depende; generalmente sin TDD. |
| `type:breaking-change` | **Preguntar al usuario antes** — afecta reglas del repo. |

### 2.3 ¿El roadmap está al día?

Comparar la issue contra [`docs/roadmap.md`](roadmap.md) §4 (Issues abiertos) y §5 (pendientes de crear):

- ¿Está en §4? → seguir.
- ¿Está en §5 como "pendiente por crear"? → se abre primero como issue y se actualiza el roadmap al abrirla.
- **¿No está en ninguno pero existe en GitHub?** → el roadmap está desactualizado. Refrescar primero — [`docs/roadmap.md`](roadmap.md) §9 lo exige.

### 2.4 Reconocimiento del dominio

Leer en este orden:

1. `docs/discovery/feature-XX-*.md` si existe para este feature.
2. [`docs/architecture/decisiones-proyecto.md`](architecture/decisiones-proyecto.md) para decisiones vigentes.
3. `docs/legacy-<área>.md` para el legacy documentado del área.
4. Si nada cubre la pregunta: **Dysflow MCP** sobre el Access legacy (P2 punto 4).

No saltar a Dysflow si la respuesta está en discovery — discovery es la versión revisada y consolidada. Dysflow es para validar contra la fuente última cuando la doc no entra en detalle.

### 2.5 Reconocimiento del código (no del dominio)

Usar `codegraph_explore` (MCP) y `codegraph node <nombre>` (CLI). **No** abrir `Read`/`Grep`/`Glob` hasta haber agotado codegraph ([AGENTS.md](../AGENTS.md) regla 14.3). Comandos:

```bash
codegraph node <función-o-archivo-exacto>
codegraph explore <bolsa-de-símbolos-o-pregunta-natural>
git log --oneline -10 -- app/<área-relevante>/
```

Si se crea un **directorio top-level nuevo** (`app/core/foo/`, `tests/integration/`) → `codegraph sync .` después, una vez ([AGENTS.md](../AGENTS.md) regla 14.8). No re-init, no re-index.

### 2.6 Aclarar dudas antes de tocar código

Si la issue es ambigua, compleja o tiene criterios de aceptación dudosos:

- Comentar en la issue pidiendo clarificación (no DM, no asumir).
- Si la duda es de alcance o de precedente: preguntar al usuario antes de implementar.

---

## §3 OpenSpec primero (cambios grandes / estructurales)

Si la issue implica **nuevo módulo, nuevo modelo de datos, cambio de contrato, o >100 líneas** esperadas:

1. Lanzar `/sdd-new <change-name>` desde el orquestador. Si Engram está disponible, los artefactos van a `openspec/changes/<change-name>/` + Engram (artifact_store por defecto: `both` / hybrid).
2. Pasar por `sdd-propose` → `sdd-spec` → `sdd-design` → `sdd-tasks`. Cada task del `tasks.md` será un work-unit de PR (o un eslabón de una cadena si supera el presupuesto de revisión).
3. Si la cadena total **supera 400 líneas**: cargar el skill **`chained-pr`** y dividir en PRs encadenadas (`stacked-to-main` o `feature-branch-chain`).
4. La propuesta y los specs deben referenciar la(s) issue(s) de GitHub y al discovery/legacy relevante (trazabilidad P1).

Si la issue es **pequeña y clara** (<100 líneas, no estructural): saltar SDD, ir directo a §4.

---

## §4 TDD estricto (default para código)

Para cambios de código (`type:bug`, `type:feature`, `type:refactor`):

### 4.1 Rojo — escribir el test que falla

- Test unitario para la unidad mínima a tocar, **o** test de integración del comportamiento end-to-end esperado.
- Verificar que **falla por la razón correcta**: el test debe reproducir la falta de capacidad antes del fix, no explotar por import roto o setup malo.
- **Si la feature implica superset funcional del legacy (P1):** el test debe cubrir **también** el caso legacy equivalente. Si solo cubre el caso nuevo, ampliar el test primero — la cobertura del caso legacy es la red de seguridad de P1.

### 4.2 Verde — implementación mínima

Solo lo necesario para pasar el test. **Nada más.** Sin abstracciones especulativas, sin "de paso arreglo esto otro".

### 4.3 Refactor — con tests verdes

Mejoras de claridad, naming, eliminación de duplicación. **Tests siguen pasando** con cada paso. **Volver a verificar P1:** ¿el refactor sigue preservando el superset del legacy?

### 4.4 Si la feature es UI

Cargar el skill **`frontend-design`** **antes** del test rojo. Las pruebas TDD de UI usan `tests/` con `TestClient` por ahora; `tests/e2e/` se ejecuta en el job `e2e` de CI cuando `APAP_OAUTH_CLIENT_ID` está configurado.

### 4.5 Si la feature toca Access/VBA

- Skills permitidos: solo `vba-access` y `access-vba-tdd` (P2 punto 4). Los demás están excluidos.
- **Atómico**: import + compile + test. Ver `access-vba-tdd` para el flujo exacto.
- Antes de tocar: `dysflow_doctor` para confirmar que el entorno está sano. Si toca el binario en `.accdb`, gate de `MCP_WRITES_DISABLED` aplica — usar `dryRun:true` para planificar y `apply:true` para confirmar.

### 4.6 Si la feature implica nuevo campo o modelo de datos

**Antes** del test rojo:

1. Abrir Dysflow sobre el Access legacy y verificar que el campo existe (o que existe un equivalente conceptual): `dysflow_list_tables` + `dysflow_get_schema`.
2. Comparar contra el modelo nuevo: `dysflow_compare_backends` si hay dos backends; lectura de `migration/` para el código de migración.
3. Si el campo es **nuevo** (no existe en el legacy): documentar en `docs/architecture/decisiones-proyecto.md` **por qué se añade** (Fase + criterio + fecha).
4. Si el campo **existe en legacy pero no estaba en el modelo nuevo**: es un gap P1. Abrir como `bug` con label `gap:legacy`.

---

## §5 Validación local (gate pre-CI)

Antes de commit + push, todo esto debe estar verde:

```bash
python -m pytest -W error::DeprecationWarning \
  --ignore=tests/e2e \
  --deselect tests/test_voluntarios_concurrent.py \
  --cov=app --cov-report=json --cov-fail-under=80 -q
ruff check .
python -m mypy
python -m build
python scripts/check_rules.py .
python scripts/check_module_size.py
```

**Detalle por comando:**

| Comando | Por qué |
|---|---|
| `pytest -W error::DeprecationWarning ...` | `tests/test_voluntarios_concurrent.py` se deselecciona localmente porque requiere PostgreSQL (`APAP_E2E_BASE_URL`); en CI también se deselecciona (GitHub no aprovisiona PG). Para correrlo: definir `APAP_E2E_BASE_URL` apuntando a un Postgres real. |
| `--cov-fail-under=80` | Replica el suelo global de `pyproject.toml` (`fail_under = 80`); `--cov-report=json` genera el `coverage.json` que alimenta el gate `CRITICAL_HELPERS`. Si pasa local, pasa en CI — mismo comando, mismo umbral ([AGENTS.md](../AGENTS.md) §19). |
| `ruff check .` | Linter estándar. |
| `python -m mypy` | Typecheck gate de CI ([AGENTS.md](../AGENTS.md) §24); alcance y flags en `pyproject.toml` bajo `[tool.mypy]`. Todo `# type: ignore` debe llevar su código de error específico. |
| `python -m build` | Genera el wheel que consume el job `deploy`. |
| `python scripts/check_rules.py .` | Detectores propios (APAP001/APAP003 + Detectors 5–8: logger ban, CSRF middleware, `SameSite=Strict`, etc.). Pasar `.` como raíz — pasar `app` desactiva silenciosamente los detectores 5–8. Corre también en CI dentro del job `lint` ([AGENTS.md](../AGENTS.md) §20). |
| `python scripts/check_module_size.py` | Ratchet de 700 líneas por módulo en `app/` y `migration/`; los offenders conocidos viven en `BASELINE` y solo pueden decrecer ([AGENTS.md](../AGENTS.md) §21). Corre también en CI dentro del job `lint`. |

---

## §6 Merge a `main` (regla 15.1, pre-MVP)

### 6.1 Convenciones de commit

- **Conventional Commits en inglés** (`feat(scope):`, `fix(scope):`, `test(scope):`, `docs(scope):`, `chore(scope):`, `refactor(scope):`).
- Scope corto: `feat(auth)`, `fix(animals)`, `test(copy)`, `docs(roadmap)`, `chore(deps)`.
- Body que referencia la issue: `Closes #N` (o `Refs #N` si la cierra parcialmente).
- Para PRs grandes, el cuerpo del commit debe incluir el run URL del CI (`ci / lint`, `ci / test`, `ci / build`, `ci / deploy`) que probó verde.
- Verificación contra la rama objetivo: `git merge-base --is-ancestor <sha> main` antes de cerrar la issue.

### 6.2 Push y PR

- Si la diff es **<400 líneas**: PR directa con base `main`, o merge local + push directo.
- Si la diff **supera 400 líneas**: skill **`chained-pr`**, dividir la feature en N PRs encadenadas. Documentar la cadena en la issue y enlazar cada PR.
- Push con `git push origin HEAD:main --no-verify` (defensivo; `stagingOnly` está unset en pre-MVP pero el hook sigue activo para otros repos). Si se olvida `--no-verify`, el hook se quejará y no es un bug — es la red de seguridad funcionando.

### 6.3 Cierre de la issue (trazabilidad obligatoria)

Tras merge verde:

```bash
gh issue close #N --repo ardelperal/APAP_WEB --comment "<cuerpo>"
```

El comentario debe incluir, según la regla global `github-issue-closure-traceability`:

1. **SHA(s) del commit de implementación** (verificable con `git merge-base --is-ancestor <sha> main`).
2. **Referencia al test** que prueba el cumplimiento (path del módulo + nombre del test). Para spec/doc-only: declararlo explícito ("es spec, no requiere TDD") y enlazar el commit del doc.
3. Si la PR tiene varias commits, listarlas todas.
4. Si un test se modificó en commit distinto al de implementación, nombrar ambos.

Plantilla mínima en castellano:

```
Cerrada con evidencia (YYYY-MM-DD): commit <sha> "<subject>" cubre <one-liner>. TDD: <test module>::<test name>. PR #N. Trazabilidad P1 (legacy): <cómo se preserva el superset>.
```

### 6.4 Limpieza tras merge

Per [AGENTS.md](../AGENTS.md) §15.2: las ramas mergeadas **se retienen**, no se borran. Lo único que se limpia es el **worktree local** (si se creó específicamente para sacar la PR):

- Si la rama se trabajó en un worktree (`git worktree add ...`): `git worktree remove --force <path>`.
- Si la rama no se trabajó en un worktree: nada que limpiar — la rama local se queda hasta que se decida renombrarla (`archive/<old-name>` si queda abandonada).
- **Nunca** `git push origin --delete <rama>`: las ramas remotas se retienen para que un fork herede el historial completo y los `refs/pull/<n>/head` queden enlazables.
- Estado final esperado: rama local (potencial worktree remoto) + `main`.

### 6.5 Actualizar el roadmap en la misma sesión

Per [`docs/roadmap.md`](roadmap.md) §9:

- Quitar fila de §4 (Issues abiertos).
- Si la fase correspondiente cambia de estado (§3): actualizar leyenda.
- Actualizar fecha "Última actualización" del roadmap.
- Si la PR reveló una decisión nueva: añadir a `docs/architecture/decisiones-proyecto.md` y enlazar desde el roadmap, **no** duplicar.

---

## §7 Triggers stop + consulta

Cualquiera de estos requiere parada y consulta explícita al usuario:

| Trigger | Acción |
|---|---|
| Frase "ya tenemos MVC" / "MVP reached" / "vamos a producción" / "vamos a staging" | Dispara [AGENTS.md](../AGENTS.md) §15.4 post-MVP revert (re-enable `stagingOnly`, recrear `staging`, regenerar el rol de Virginia). |
| `git push --force` sugerido | no. Punto. |
| Cambios en `git-hooks/` o `core.hooksPath` global | no sin OK explícito. |
| Cambios en `.gitignore` raíz | OK solo si no afecta `.codegraph/` ([AGENTS.md](../AGENTS.md) §14.4). |
| Crear nuevo dir top-level | `codegraph sync .` después ([AGENTS.md](../AGENTS.md) §14.8). |
| Branch protection en GitHub | no sin OK explícito. |
| Deploy secrets (`COOLIFY_WEBHOOK_URL`, `APAP_OAUTH_CLIENT_ID`) | no tocar; son del operador. |
| Asumir equivalencia nueva↔legacy sin documentarla en `docs/architecture/decisiones-proyecto.md` | stop; documentar primero. |
| Modificar `docs/discovery/` o `docs/legacy-*` por cambio de interpretación | OK si se cita el cambio concreto; el doc se mantiene vivo. |

---

## §8 Anti-patrones a evitar

- Implementar sin test rojo primero (excepto `type:docs` y ops puros).
- "Pintar" el test solo para que pase — escribir tests que prueben comportamiento observable.
- `Read`/`Grep`/`Glob` antes de haber agotado `codegraph_explore`/`codegraph node` ([AGENTS.md](../AGENTS.md) §14.3).
- Diseñar un campo/feature nuevo sin verificar el equivalente legacy (P1, §4.6).
- Cierre de issue sin trazabilidad (SHA + test) — global `github-issue-closure-traceability`.
- Saltarse CI con `--no-verify` (excepto bypass explícito del hook tras OK del usuario).
- Mergear con CI rojo ([AGENTS.md](../AGENTS.md) §15.1).
- Asumir que el roadmap está al día sin haberlo comprobado (§2.3).
- Tocar `.codegraph/.gitignore` o `.codegraph/db` manualmente.
- Inventar allowlists, suppress de tests, o "fixes" sin entender la raíz (lección XSS 2026-07-03: el test tenía su mecanismo — `handler_controlled` allowlist — no era "suprimir el test").
- Usar skills de Access distintos a `vba-access` y `access-vba-tdd` (P2 punto 4).
- Inferir el flip pre-MVP → post-MVP de frases como "ya está" o "vamos cerrando" sin el keyword MVP/MVC ([AGENTS.md](../AGENTS.md) §15.4 punto 5).
- `git push origin main` con commits locales sin verificar previamente que pasan §5 (validación local).

---

## §9 Glosario de comandos rápidos

```bash
# Issue en curso
gh issue view #N --repo ardelperal/APAP_WEB --comments
gh issue edit #N --repo ardelperal/APAP_WEB --add-label "status:in-progress"

# Branch + trabajo
git checkout -b <tipo>/<scope>
# ... TDD (§4) ...
git add <files específicos>
git commit -m "tipo(scope): subject"
git push origin HEAD

# Validación local
pytest -W error::DeprecationWarning --ignore=tests/e2e --deselect tests/test_voluntarios_concurrent.py --cov=app --cov-report=json --cov-fail-under=80
ruff check .
python -m mypy
python -m build
python scripts/check_rules.py .
python scripts/check_module_size.py

# CodeGraph
codegraph status .           # sesión start
codegraph sync .             # tras crear dir top-level
codegraph node <exacto>      # un símbolo
codegraph explore <bolsa>    # varios + blast radius

# PR + CI (pre-MVP)
gh pr create --base main --title "..." --body "Closes #N"
gh run watch $(gh run list --branch main --limit 1 --json databaseId -q '.[0].databaseId') --exit-status

# Tras merge verde
git checkout main
# Solo si hubo worktree: git worktree remove --force <path>
# NO git push origin --delete — la rama remota se retiene (AGENTS §15.2)
git branch -m archive/<old-name>   # solo si la rama queda abandonada
gh issue close #N --comment "..."

# Dysflow (P2 punto 4)
dysflow_list_tables --projectId apap
dysflow_get_schema --projectId apap --tableName <tabla>
dysflow_get_relationships --projectId apap
dysflow_query_sql --projectId apap --sql "SELECT ..."

# Mantenimiento post-sesión
codegraph status .
git config --get-all gentleai.stagingOnly
git log --oneline -5 main
```

## Contributor checklist

- [ ] Al iniciar cualquier sesión que toque código o specs, lea `docs/proceso.md` y entendió las cuatro premisas.
- [ ] Antes de abrir un PR, ejecutar `python -m pytest -W error::DeprecationWarning --ignore=tests/e2e --deselect tests/test_voluntarios_concurrent.py --cov=app --cov-report=json --cov-fail-under=80 -q` y confirmar suelo verde en local.
- [ ] Si la issue implica nuevo campo o modelo, verificar primero el equivalente en el Access legacy (P1, §4.6) antes de escribir el test rojo.
- [ ] Si la duda de dominio no cierra con discovery + decisiones + legacy, escalar a Dysflow MCP (P2) y, si persiste, preguntar al usuario.
- [ ] Si la PR toca `docs/proceso.md` o `docs/roadmap.md`, abrirla como `type:docs` y citar la regla o sección que cambia.
- [ ] Al cerrar la issue, incluir SHA del commit, path del test, trazabilidad P1 (cómo preserva el superset) y, si aplica, referencia al SDD change.
- [ ] Al cerrar una PR, refrescar `docs/roadmap.md` en la misma sesión (quitar fila de §4, mover fase si corresponde, actualizar fecha "Última actualización").
- [ ] Si descubre una divergencia con el legacy, abrirla como `gap:legacy` antes de continuar con la issue principal.

## Navigation

Previous: [Development workflow](development.md) | Next: [RBAC matrix](security/rbac-matrix.md)
