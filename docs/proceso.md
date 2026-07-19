# Proceso de trabajo por issue — APAP_WEB

> Guía operativa. Punto de entrada único para tomar una issue de principio a fin en APAP_WEB. Cada paso tiene condición de salida clara. Si en cualquier momento dudas, vuelve aquí, al `docs/roadmap.md`, o a la propia issue.

**Última actualización:** 2026-07-03 (creación; integra premisas de fidelidad al legacy, código-fuente-y-doc-refleja, pre-MVP single-branch, y resolución de dudas vía Dysflow)
**Aplicable a:** todo trabajo en APAP_WEB (código, docs, infra, producto)
**Vinculado a:** `docs/roadmap.md`, `AGENTS.md` (reglas 14 y 15), `openspec/specs/*`, `openspec/changes/*`, `docs/discovery/*`, `docs/decisiones-proyecto.md`, `docs/legacy-*`

---

## §0 — Premisas fundamentales (no negociables)

Estas premisas rigen **TODO** lo que se haga en APAP_WEB. Si una tarea las pone en entredicho, se para y se replantea antes de seguir.

### P1. Fidelidad al legacy: superset funcional

La aplicación nueva debe poder sincronizarse con el Access/VBA legacy y preservar **el 100% de las intenciones y funcionalidades del legacy**, más las funcionalidades nuevas ya acordadas (ver `docs/roadmap.md` §3 Fases 3-7 + transversales, y `docs/discovery/feature-XX-*.md`).

- **Ni una funcionalidad menos.** Si el legacy tiene un campo, un estado, un cálculo, un atajo, un informe, un permiso, una validación, un workflow, una transición: la nueva aplicación lo conserva (o lo reemplaza por un equivalente explícitamente acordado y documentado).
- **Las funcionalidades nuevas son aditivas** al inventario del legacy. Vienen del roadmap §3 y de `docs/discovery/`.
- **Si descubres que algo del legacy no está en la nueva app,** trátalo como bug del nuevo modelo. Abre issue con label `gap:legacy` en lugar de obviarlo. La trazabilidad es: cada capacidad del legacy → su representación en el modelo nuevo → su cobertura de tests.

**Ejemplo:** si estás en el modelo de animales, el legacy en Access tiene un `estado_actual_animal` con transiciones complejas (`docs/legacy-lifecycle-transition-rules.md` y `docs/discovery/state-machines.md`); la nueva implementación tiene que soportar **exactamente** las mismas transiciones, más las nuevas que se acuerden para Fase 4. Si tu PR introduce un nuevo campo, valida que no rompe ninguna regla del legacy para campos equivalentes.

### P2. Resolución de dudas sobre el dominio

Cuando algo no quede claro — modelo de datos, regla de negocio, comportamiento esperado, edge case — consulta **en este orden**:

1. `docs/discovery/feature-XX-*.md` (la versión revisada y consolidada, en castellano)
2. `docs/decisiones-proyecto.md` (si la duda es de producto/UX/arquitectura/proceso)
3. `docs/legacy-<área>.md` (documentación específica del área en el legacy)
4. **El Access directamente vía Dysflow MCP** (`projectId: apap`, `accessPath` resuelve al `.accdb` del legacy). Herramientas canónicas: `dysflow_list_tables`, `dysflow_get_schema`, `dysflow_get_relationships`, `dysflow_query_sql` (modo read), `dysflow_count_rows`, `dysflow_distinct_values`, `dysflow_compare_backends`. Diagnóstico de entorno con `dysflow_doctor`.

Solo permitido el skill **`vba-access`** y **`access-vba-tdd`**. Los demás skills de Access (`access-vba-sync`, `access-query`, `access-form-creation`, `access-sandbox`, etc.) están **excluidos** del workflow de APAP_WEB (ver `docs/roadmap.md` §7).

Si tras las 4 capas sigues con dudas: **pregunta al usuario**. No asumas equivalencias silenciosamente.

### P3. Documentación refleja, código es fuente de verdad

- La documentación (incluido este `docs/proceso.md` y `docs/roadmap.md`) **refleja** el código, no al revés.
- Si divergen, gana **el código** (sea legacy o nuevo). Actualiza la doc en la misma sesión en que detectas la divergencia. Esto no es opcional: `docs/roadmap.md` §9 lo exige.
- `decisiones-proyecto.md` es el registro de las decisiones que rompieron el molde. Cualquier "esto es distinto al legacy porque X" debe constar allí con su fecha, autor y motivo.

### P4. Pre-MVP single-branch

Todo va a `main` directamente. Una sola rama al final de cada ciclo de merge (AGENTS.md §15.2). Reversión post-MVP en §15.4, con **Virginia** como validadora UAT. El flip de fase solo se dispara por instrucción explícita del usuario ("ya tenemos MVC" / equivalente).

---

## §1 — Pre-flight (cada sesión, cada vez)

Antes de tocar nada, verifica que la realidad del repo coincide con lo que crees saber:

```bash
# Salud del index de código
codegraph status .
codegraph daemons

# Política de rama activa (pre-MVP)
git config --get-all gentleai.stagingOnly    # si vuelve a "true", re-leer AGENTS.md §15.4
git branch --show-current
git status --short --branch

# Realidad del repo
gh issue list --repo ardelperal/APAP_WEB --state open --limit 50
git log --oneline -10 main
```

**Salidas esperadas:**

- Index `[OK] Index is up to date`, daemon vivo (PID + `v1.4+`).
- Rama actual: `main` (en pre-MVP). Si es otra distinta, hay feature branch en curso — acabarla o abandonarla primero.
- `gentleai.stagingOnly` = (vacío) para este repo.
- Status limpio o solo con cambios controlados (p. ej. `.atl/skill-registry.md` autogen).

---

## §2 — Triaje de la issue

Una issue se aborda en este orden estricto.

### 2.1 Leer la issue, no la respuesta

```bash
gh issue view #N --repo ardelperal/APAP_WEB --comments
```

Extraer: **título + descripción** (qué pide exactamente), **labels** (scope + tipo + prioridad + estado), **issues vinculadas** (bloquea / es bloqueada por cuáles), **criterios de aceptación** explícitos si los hay.

### 2.2 Clasificar

| Label `type:*` | Acción |
|---|---|
| `type:bug` | §4 TDD; regresión o gap:legacy primero si aplica (P1) |
| `type:feature` | §3 OpenSpec primero si >100 líneas o cambio estructural; si no, §4 directo |
| `type:refactor` | §4 TDD con golden test o contrato preservado; tras TDD, validar que no rompe P1 |
| `type:docs` | sin TDD; PR directa con diff mínimo y CI verde |
| `type:chore` / ops | depende; generalmente sin TDD |
| `type:breaking-change` | **preguntar al usuario antes** — afecta reglas del repo |

### 2.3 ¿El roadmap está al día?

Compara la issue contra `docs/roadmap.md` §4 (Issues abiertos) y §5 (pendientes de crear):

- ¿Está en §4? → sigues.
- ¿Está en §5 como "pendiente por crear"? → se abre primero como issue y se actualiza el roadmap al abrirla.
- **¿No está en ninguno pero existe en GitHub?** → el roadmap está desactualizado. Refresca primero — `docs/roadmap.md` §9 lo exige ("si el doc se desactualiza respecto a main, abrir `docs(roadmap): refrescar hoja de ruta` y ejecutar el refresco en la misma sesión").

### 2.4 Reconocimiento del dominio

Lee en este orden (§7 del roadmap aplicado a nivel de issue):

1. `docs/discovery/feature-XX-*.md` si existe para este feature
2. `docs/decisiones-proyecto.md` para decisiones vigentes
3. `docs/legacy-<área>.md` para el legacy documentado del área
4. Si nada cubre la pregunta: **Dysflow MCP** sobre el Access legacy (P2 punto 4)

No saltar a Dysflow si la respuesta está en discovery — discovery es la versión revisada y consolidada. Dysflow es para validar contra la fuente última cuando la doc no entra en detalle.

### 2.5 Reconocimiento del código (no del dominio)

Usa `codegraph_explore` (MCP) y `codegraph node <nombre>` (CLI). **No** abrir `Read`/`Grep`/`Glob` hasta haber agotado codegraph (AGENTS.md regla 14.3). Comandos:

```bash
codegraph node <función-o-archivo-exacto>
codegraph explore <bolsa-de-símbolos-o-pregunta-natural>
git log --oneline -10 -- app/<área-relevante>/
```

Si creas un **directorio top-level nuevo** (`app/core/foo/`, `tests/integration/`) → `codegraph sync .` después, una vez (AGENTS.md regla 14.8). No re-init, no re-index.

### 2.6 Aclara dudas ANTES de tocar código

Si la issue es ambigua, compleja, o tiene criterios de aceptación dudosos:

- Comenta en la issue pidiendo clarificación (no DM, no asumir).
- Si la duda es de alcance o de precedente: pregunta al usuario antes de implementar.

---

## §3 — OpenSpec primero (cambios grandes / estructurales)

Si la issue implica **nuevo módulo, nuevo modelo de datos, cambio de contrato, o >100 líneas** esperadas:

1. Lanza `/sdd-new <change-name>` desde el orquestador. Si Engram está disponible, los artefactos van a `openspec/changes/<change-name>/` + Engram (artifact_store por defecto: `both` / hybrid).
2. Pasa por `sdd-propose` → `sdd-spec` → `sdd-design` → `sdd-tasks`. Cada task del `tasks.md` será un work-unit de PR (o un eslabón de una cadena si supera el presupuesto de revisión).
3. Si la cadena total **supera 400 líneas**: cargar el skill **`chained-pr`** y dividir en PRs encadenadas (`stacked-to-main` o `feature-branch-chain`).
4. La propuesta y los specs deben referenciar la(s) issue(s) de GitHub y al discovery/legacy relevante (trazabilidad P1).

Si la issue es **pequeña y clara** (<100 líneas, no estructural): salta SDD, ve directo a §4.

---

## §4 — TDD estricto (default para código)

Para cambios de código (`type:bug`, `type:feature`, `type:refactor`):

### 4.1 Rojo — escribir el test que falla

- Test unitario para la unidad mínima a tocar, **o** test de integración del comportamiento end-to-end esperado.
- Verifica que **falla por la razón correcta**: el test debe reproducir la falta de capacidad antes del fix, no explotar por import roto o setup malo.
- **Si la feature implica superset funcional del legacy (P1):** el test debe cubrir **también** el caso legacy equivalente. Si solo cubres el caso nuevo, расширь el test primero — la cobertura del caso legacy es la red de seguridad de P1.

### 4.2 Verde — implementación mínima

Solo lo necesario para pasar el test. **Nada más.** Sin abstracciones especulativas, sin "de paso arreglo esto otro".

### 4.3 Refactor — con tests verdes

Mejoras de claridad, naming, eliminación de duplicación. **Tests siguen pasando** con cada paso. **Vuelve a verificar P1:** ¿el refactor sigue preservando el superset del legacy?

### 4.4 Si la feature es UI

Carga el skill **`frontend-design`** **antes** del test rojo. Las pruebas TDD de UI usan `tests/` con `TestClient` por ahora (no hay `tests/e2e/` en esta rama todavía — el harness Playwright está diferido a Fase 0 pendiente).

### 4.5 Si la feature toca Access/VBA

- Skills permitidos: solo `vba-access` y `access-vba-tdd` (P2 punto 4). Los demás están excluidos.
- **Atómico**: import + compile + test. Ver `access-vba-tdd` para el flujo exacto.
- Antes de tocar: `dysflow_doctor` para confirmar que el entorno está sano. Si toca el binario en `.accdb`, gate de `MCP_WRITES_DISABLED` aplica — usa `dryRun:true` para planificar y `apply:true` para confirmar.

### 4.6 Si la feature implica nuevo campo o modelo de datos

**Antes** del test rojo:

1. Abre Dysflow sobre el Access legacy y verifica que el campo existe (o que existe un equivalente conceptual): `dysflow_list_tables` + `dysflow_get_schema`.
2. Compara contra el modelo nuevo: `dysflow_compare_backends` si tienes dos backends; lectura de `migration/` para el código de migración.
3. Si el campo es **nuevo** (no existe en el legacy): documenta en `decisiones-proyecto.md` **por qué se añade** (Fase + criterio + fecha).
4. Si el campo **existe en legacy pero no estaba en el modelo nuevo**: es un gap P1. Ábrelo como `bug` con label `gap:legacy`.

---

## §5 — Validación local (gate pre-CI)

Antes de commit + push, todo esto debe estar verde:

```bash
python -m pytest -W error::DeprecationWarning \
  --ignore=tests/e2e \
  --deselect tests/test_voluntarios_concurrent.py \
  --cov=app --cov-report=json --cov-fail-under=80 -q
ruff check .
python -m mypy
python -m build
```

`test_voluntarios_concurrent.py` se deselecciona localmente porque requiere PostgreSQL (`APAP_E2E_BASE_URL`); en CI también se deselecciona (GitHub no aprovisiona PG). Para correrlo: define `APAP_E2E_BASE_URL` apuntando a un Postgres real.

Los flags de cobertura replican exactamente lo que ejecuta el job `test` de `ci.yml` (regla 19 de AGENTS.md): `--cov-fail-under=80` aplica el suelo global de `pyproject.toml` (`fail_under = 80`) y `--cov-report=json` genera el `coverage.json` que alimenta el gate de `CRITICAL_HELPERS` (regla 11). Si la cobertura local pasa, la de CI también — mismo comando, mismo umbral.

Si el repo tiene `scripts/check_rules.py` (detectores propios: APAP001 rutas/SQL, APAP003 logger ban, CSRF middleware, log_safe, etc.), correrlo también: `python scripts/check_rules.py .` (con `.` como raíz — pasar `app` desactiva en silencio los detectores 5-8). Desde la issue #200 este linter también corre en CI dentro del job `lint` (regla 20 de AGENTS.md), así que si falla en local fallará el build.

Correr también el ratchet de tamaño de módulos: `python scripts/check_module_size.py` (regla 21 de AGENTS.md, issue #202). Presupuesto de 700 líneas por módulo en `app/` y `migration/`; los offenders conocidos viven en la `BASELINE` del script y solo pueden decrecer. También corre en CI dentro del job `lint`.

El typecheck es otro gate de CI (regla 24 de AGENTS.md, issue #201): `python -m mypy` (o `make typecheck`) debe salir con cero errores. El alcance y los flags viven en `pyproject.toml` bajo `[tool.mypy]` (`files = ["app", "migration"]`), así que el comando local y el job `typecheck` de CI ejecutan exactamente la misma comprobación. Todo `# type: ignore` debe llevar su código de error específico.

---

## §6 — Merge a `main` (regla 15.1, pre-MVP)

### 6.1 Convenciones de commit

- **Conventional Commits en inglés** (`feat(scope):`, `fix(scope):`, `test(scope):`, `docs(scope):`, `chore(scope):`, `refactor(scope):`).
- Scope corto: `feat(auth)`, `fix(animals)`, `test(copy)`, `docs(roadmap)`, `chore(deps)`.
- Body que referencie la issue: `Closes #N` (o `Refs #N` si la cierra parcialmente).
- Para PRs grandes, el cuerpo del commit debe incluir el run URL del CI (`ci / lint`, `ci / test`, `ci / build`, `ci / deploy`) que probó verde.
- Verificación contra la rama objetivo: `git merge-base --is-ancestor <sha> main` antes de cerrar la issue.

### 6.2 Push y PR

- Si la diff es **<400 líneas**: PR directa con base `main`, o merge local + push directo.
- Si la diff **supera 400 líneas**: skill **`chained-pr`**, dividir la feature en N PRs encadenadas.
- Push con `git push origin HEAD:main --no-verify` (defensivo; `stagingOnly` está unset en pre-MVP pero el hook sigue activo para otros repos). Si olvidas `--no-verify`, el hook se quejará y no es un bug — es la red de seguridad funcionando.

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

- Borrar rama local (`git branch -d <rama>`).
- Borrar rama remote si existía (`git push origin --delete <rama>`).
- Estado final esperado: solo `main`.

### 6.5 Actualizar el roadmap en la misma sesión

Per `docs/roadmap.md` §9:

- Quitar fila de §4 (Issues abiertos).
- Si la fase correspondiente cambia de estado (§3): actualizar leyenda.
- Actualizar fecha "Última actualización" del roadmap.
- Si la PR reveló una decisión nueva: añadir a `decisiones-proyecto.md` y enlazar desde el roadmap, **no** duplicar.

---

## §7 — Triggers para acciones especiales (STOP + consulta)

Cualquiera de estos requiere parada y consulta explícita al usuario:

| Trigger | Acción |
|---|---|
| Frase "ya tenemos MVC" / "MVP reached" / "vamos a producción" / "vamos a staging" | Dispara AGENTS.md §15.4 post-MVP revert (re-enable `stagingOnly`, recrear `staging`, regenerar el rol de Virginia) |
| `git push --force` sugerido | NO. Punto. |
| Cambios en `git-hooks/` o `core.hooksPath` global | NO sin OK explícito |
| Cambios en `.gitignore` raíz | OK solo si no afecta `.codegraph/` (regla 14.4) |
| Crear nuevo dir top-level | `codegraph sync .` después (regla 14.8) |
| Branch protection en GitHub | NO sin OK explícito |
| Deploy secrets (`COOLIFY_WEBHOOK_URL`, `APAP_OAUTH_CLIENT_ID`) | NO tocar; son del operador |
| Asumir equivalencia nueva↔legacy sin documentarla en `decisiones-proyecto.md` | STOP; documentar primero |
| Modificar `docs/discovery/` o `docs/legacy-*` por cambio de interpretación | OK si se cita el cambio concreto; el doc se mantiene vivo |

---

## §8 — Anti-patrones a evitar

- ❌ Implementar sin test rojo primero (excepto `type:docs` y ops puros)
- ❌ "Pintar" el test solo para que pase — escribir tests que prueben comportamiento observable
- ❌ `Read`/`Grep`/`Glob` antes de haber agotado `codegraph_explore`/`codegraph node` (regla 14.3)
- ❌ Diseñar un campo/feature nuevo sin verificar el equivalente legacy (P1, §4.6)
- ❌ Cierre de issue sin trazabilidad (SHA + test) — global `github-issue-closure-traceability`
- ❌ Saltarse CI con `--no-verify` (excepto bypass explícito del hook tras OK del usuario)
- ❌ Mergear con CI rojo (regla 15.1)
- ❌ Asumir que el roadmap está al día sin haberlo comprobado (§2.3)
- ❌ Tocar `.codegraph/.gitignore` o `.codegraph/db` manualmente
- ❌ Inventar allowlists, suppress de tests, o "fixes" sin entender la raíz (lección XSS 2026-07-03: el test tenía su mecanismo — `handler_controlled` allowlist — no era "suprimir el test")
- ❌ Usar skills de Access distintos a `vba-access` y `access-vba-tdd` (P2 punto 4)
- ❌ Inferir el flip pre-MVP → post-MVP de frases como "ya está" o "vamos cerrando" sin el keyword MVP/MVC (AGENTS.md §15.4 punto 5)
- ❌ `git push origin main` con commits locales sin verificar previamente que pasan §5 (validación local)

---

## §9 — Glosario de comandos rápidos

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
git branch -d <rama>
git push origin --delete <rama>
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
