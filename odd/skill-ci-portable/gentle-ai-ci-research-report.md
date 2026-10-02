# Informe de investigación — ingeniería inversa del CI de `Gentleman-Programming/gentle-ai`

> **Propósito:** encontrar ideas transferibles al CI de `ardelperal/APAP_WEB`. Investigación read-only sobre el repo público de Alan, contrastada con el patrón propio documentado en `odd/HANDOFF-ci-2026-09-30.md`, `odd/skill-ci-portable/source-notes.md` y la épica #935.
>
> **Fecha de corte:** 2026-09-30 (HEAD de `gentle-ai` = `717087b`). Clon shallow (`--depth 50`) en `/tmp/gentle-ai-research`. Toda la evidencia lleva `fichero:línea` o URL de commit/run.
>
> **Convención:** castellano peninsular formal (usted), tercera persona del agente, longitud ≤ 200 caracteres por párrafo en lo posible.

---

## Resumen ejecutivo

El CI de `gentle-ai` es un sistema de **dos capas desacopladas** — `pr-check.yml` (informativo/bloqueante para autores de PR) y `pr-size-policy.yml` (política de confianza ejecutada con `pull_request_target`) — más un `ci.yml` que corre en paralelo por formato (Go, Linux/Windows/Darwin, E2E multi-distro), un preflight de release que **nunca se fía** de que CI haya ido verde y un verificador posterior que re-descarga los artefactos y re-firma contra anclas de confianza. El mantenimiento está sostenido por un catálogo de **documentos por tarea** (`odd/tasks/<n>-<slug>.md`) con posición de causa raíz, tareas y evidencia cronológica, exactamente el patrón que nuestro traspaso `odd/HANDOFF-ci-2026-09-30.md` ya aplica a la épica #935.

**Nueve ideas transferibles concretas** (sección 5): siete de CI puro, dos candidatas dobles (CI + colaboración humano-IA). Tres fricciones que veríamos como bloqueantes pero que Alan resuelve con elegancia — workflow manual con bypass, suite deslastada del gate de release, ratchet en lugar de clean gate — son la base de las mejores ideas.

---

## 1. Mapa del sistema

### 1.1 Workflows (topología)

Siete workflows en `.github/workflows/` (1593 LOC en total):

| Workflow | Trigger | Runs-on | Tiempo medio (últimas 30) | Bloquea |
|---|---|---|---|---|
| `pr-check.yml` | `pull_request` (tipos `opened, edited, synchronize, labeled, unlabeled`) | ubuntu-latest | ~18-21 s | sí (cuatro jobs requeridos en `main`) |
| `pr-size-policy.yml` | `pull_request_target` (los mismos tipos) | ubuntu-latest | ~10-17 s | **dormant** (política dormida por diseño, ver §2.3) |
| `ci.yml` | `pull_request`, `push` a `main`, `schedule` (03:00 UTC), `workflow_dispatch` | ubuntu-latest, windows-latest, macos-latest | ~5-9 min | sí (`Unit Tests`, `E2E Tests (ubuntu/arch/fedora)`) |
| `release.yml` | `push` tag `v*` (excluye `v*-*`) | ubuntu-24.04 | preflight + verify (~15 min) | sí (publicación de release) |
| `promote-stable-rc.yml` | `workflow_dispatch` (entradas `source_prerelease_tag`, `stable_tag`, `release_environment_policy_id`) | ubuntu-24.04 | preflight + release + verify | sí (promoción de RC → estable) |
| `windows-full-suite.yml` | `push` a `main`, `schedule` (03:20 UTC), `workflow_dispatch` | windows-latest | ~31 min (cron/ push), termina en `failure` con frecuencia (ver §1.4) | **NO** bloquea release |
| `discord-notifications.yml` | `release.published`, `issues.{opened,closed,reopened}` | ubuntu-latest | < 30 s | n/a (informativo) |

Fuente: `ls .github/workflows/` (7 ficheros, 1593 LOC); `gh run list -R Gentleman-Programming/gentle-ai --limit 30` (datos de tiempos); `gh api repos/Gentleman-Programming/gentle-ai/rulesets/13932547` (reglas de merge requeridas).

### 1.2 Topología del fan-out (ci.yml)

`ci.yml` corre **en paralelo por formato**, no por pasos:

- `go-format` (formato) → `unit-tests`, `claude-network-none`, `windows-runtime`, `darwin-runtime`, `organic-runtime-e2e` (matriz Ubuntu+Windows), `e2e-tests` (matriz 3×distro Ubuntu/Arch/Fedora) — todos con `needs: go-format` y `if: always()` para no bloquear por un fallo anterior (`ci.yml:66-69`, `:184-187`, `:335-338`, `:370-373`, `:474-477`).
- `opencode-v2-contracts` y `installer-module-path` corren **sin** dependencia de `go-format` (son contratos externos), con su propio checkout.

Detalle singular: cada paso dependiente vuelve a **comprobar** el éxito del formato con `if: needs.go-format.result != 'success' / run: exit 1` (`ci.yml:73-74`, `:197-199`, `:342-343`, `:386-387`, `:491-493`). Patrón explícito en el comentario de `windows-runtime`: *"Deliberately not `if: failure()`-guarded or made required"* (`ci.yml:209-211`).

### 1.3 Reglas de protección (rulesets, no branch-protection legacy)

`gh api repos/Gentleman-Programming/gentle-ai/rulesets/13932547` muestra **un único ruleset activo**, `pr`, con seis reglas:

1. `deletion` (no borrar rama)
2. `non_fast_forward` (no force-push)
3. `copilot_code_review` (revisión en push, no en draft)
4. `required_status_checks` (7 checks: `Check Issue Has status:approved`, `Check Issue Reference`, `Check PR Has type:* Label`, `Unit Tests`, `E2E Tests (ubuntu|arch|fedora)`) con `strict_required_status_checks_policy: false`
5. `commit_message_pattern` (Conventional Commits, regex exact)
6. `branch_name_pattern` (regex tipo/kebab-slug)

> **Nota:** la rama está marcada `protected: true` con `protection.enabled: false` (`gh api repos/.../branches/main` → `protection.enabled:false`). La protección vive en el ruleset, no en `branches/main/protection` (legacy), por eso esa API devuelve 404.

### 1.4 Historial reciente — la suite Windows falla siempre

`gh run list -R Gentleman-Programming/gentle-ai --workflow "Windows Full Suite" --limit 10` muestra **diez ejecuciones consecutivas en `failure`**, con tiempos entre 21 m y 35 m. Es el resultado del acuerdo documentado en `windows-full-suite.yml:3-17`: hasta el 2026-07-29 esa suite nunca terminó; se decidió sacarla de `ci.yml` para que la release no quedara rehén del debt, y se documentó en el comentario *"This is not a permanent home: once the eighteen are fixed, fold this back into ci.yml so it gates again"*. Cuesta: el CI principal nunca prueba los defectos de Windows nativos; el push a `main` mantiene una deuda visible.

### 1.5 Capa de contratos externos

`contracts/review-provider-contract/CONTRACT_SEMVER` es un fichero versionado que el release flow lee y valida (`release.yml:67-69`, `:144-146`; `promote-stable-rc.yml:71-78`, `:105-107`); la build produce `gentle-ai-review-provider-contract-${SEMVER}.tar.gz` que se publica y se re-verifica (`verify-release-assets.sh:39`). Es la frontera entre la versión del binario y la del contrato que otros (consumidores) firman contra nosotros.

---

## 2. Convenciones del maintainer (cómo se hacen cumplir)

### 2.1 El trilero: doc + skill + workflow + label

Alan hace cumplir las reglas en **cuatro capas** que se refuerzan:

| Capa | Vehículo | Ejemplo |
|---|---|---|
| Documentación pública | `CONTRIBUTING.md:24-373` (411 líneas) | Convenciones de commit, formato de PR, checklist de revisión |
| Documentación para IAs | `AGENTS.md` (28 líneas, índice de skills) y `AI_POLICY.md` (62 líneas) | Reglas para agentes (sin `Co-Authored-By`, disclosure obligatorio) |
| Skill versionada en repo | `skills/branch-pr/SKILL.md`, `skills/chained-pr/SKILL.md`, `skills/work-unit-commits/SKILL.md` | Procedimientos canónicos por escenario |
| Mecánica en workflow | `pr-check.yml`, `ci.yml`, reglas de ruleset | Validación automática |

Las plantillas de issue (`.github/ISSUE_TEMPLATE/bug_report.yml`) llevan el texto: *"PRs that fix issues without `status:approved` will be automatically rejected"* (líneas 7-8). El contributor recibe el mensaje **al abrir el issue**; la mecánica **al abrir el PR**; el agente (IA) lo lee en `AGENTS.md` y `branch-pr/SKILL.md`.

### 2.2 Issue-first workflow — el contrato entre issue y PR

La pareja `pr-check.yml:59-108` (`Check Issue Reference`) y `pr-check.yml:109-163` (`Check Issue Has status:approved`) cierra el contrato:

- El parser vive en `.github/scripts/parse-linked-issues.cjs` (102 LOC, ~10 regex, fail-closed sobre comentarios HTML, referencias cross-repo, malformadas, mezcladas closing/non-closing para el mismo número).
- Los tests viven en `.github/scripts/parse-linked-issues.test.cjs` (162 LOC, 16 casos) y corren con `node --test` en `pr-check.yml:57`.
- El segundo job **consume el output** del primero (`pr-check.yml:122`: *"Reuse the parse output; do not re-scan the raw body"*) — un patrón explícito de "no reconstruir datos que ya validaste".

> **Detalle no obvio:** `pr-check.yml:77-83` comenta el porqué de leer el `event body` directamente y no el PR fresco: *"The PR description is rewritten by tooling (e.g. CodeRabbit) after the event fires, so a freshly fetched body would never match the event payload"*. Es la **misma clase** de problema que nuestro `closingIssuesReferences` se rellena segundos después de crear el PR (regla R10 y `B11` en `odd/HANDOFF-ci-2026-09-30.md`).

### 2.3 Conventional Commits y nombres de rama — tres enforcement superpuestos

- **Regla del ruleset** (`commit_message_pattern`, regex exacto) — bloquea push a `main`.
- **Regla del ruleset** (`branch_name_pattern`) — bloquea creación de PR.
- **Skill** (`branch-pr/SKILL.md:43-64`) — el agente lo sabe de antemano.
- **Documentación** (`CONTRIBUTING.md:222-302`) — el contributor lo lee.

`pr-size-policy.yml` opera por separado con un **doble** enforcement (ver §2.4).

### 2.4 Tamaño del PR — ratchet por doble gate dormido

`pr-size-policy.yml` usa `pull_request_target` (no `pull_request`), lo que le permite hacer `sparse-checkout` de `.github/scripts/check-pr-size.cjs` y `.github/grandfather-size-exceptions.json` **del `default_branch`** (`pr-size-policy.yml:18-25`). La lógica, en `.github/scripts/check-pr-size.cjs:1-187`:

- Define `REVIEW_BUDGET_LIMIT = 400`.
- Carga la política desde `grandfather-size-exceptions.json`.
- Valida la política: claves permitidas (`POLICY_KEYS`), `enforcement ∈ {dormant, enforcing}`, inmutabilidad del `activation_snapshot`, y la transición entre versiones (`validatePolicyTransition`, líneas 157-185).
- Distingue tres veredictos: `pass` (en presupuesto), `warning` (sobre presupuesto pero grandfathered o dormido), `failure` (sobre presupuesto y `enforcement === 'enforcing'`).

Y `pr-check.yml:13-49` corre **otra vez** el mismo cálculo de manera informativa: si la etiqueta `size:exception` está, sólo advierte; si no, falla con `setFailed`.

**Estado actual** (`.github/grandfather-size-exceptions.json`): `enforcement: "dormant"`, `activation_snapshot: null`, `grandfathered_prs: []`. Es decir: el motor está **commited, probado y dormido**, listo para activar cuando Alan decida. Esto resuelve nuestro B2 (`strict` sin cola) sin imposiciones irreversibles.

### 2.5 `status:approved` — quién lo pone, cuándo

`bug_report.yml:3-7` aplica `"status:needs-review"` automáticamente al crear el issue. La transición a `status:approved` es **manual del maintainer** y nunca es automática: `branch-pr/SKILL.md:23-24` y `pr-check.yml:152-156` lo refuerzan (*"Use the canonical issue-creation workflow contract only when a current direct instruction and target-host capability grant authorize the exact action; otherwise wait"*).

---

## 3. Gates mecánicos

### 3.1 Inventario por check

| Check | Workflow / ubicación | Qué valida | Cómo | Coste si se quita |
|---|---|---|---|---|
| `Check PR Cognitive Load` (informativo) | `pr-check.yml:13-49` | Líneas modificadas ≤ 400, o `size:exception` | Inline `actions/github-script` con `pr.additions + pr.deletions` | Pierdes la guía visible al autor |
| `Check Workflow Scripts` | `pr-check.yml:50-57` | Tests Node de los scripts del workflow | `node --test` sobre los `.test.cjs` | Falsos rojos/verdes al cambiar parser |
| `Check Issue Reference` | `pr-check.yml:59-108` | El cuerpo del PR contiene `Closes/Refs #N` válido | `parseLinkedIssues` (`parse-linked-issues.cjs`) | PRs sin issue aprobado pasan |
| `Check Issue Has status:approved` | `pr-check.yml:109-163` | La issue referenciada tiene la etiqueta | `github.rest.issues.get` por issue referenciada | Issue-first workflow se rompe silenciosamente |
| `Check PR Has type:* Label` | `pr-check.yml:165-201` | Exactamente una etiqueta `type:*` | `github.rest.pulls.get`, filtro por prefijo | Una PR sin tipo pasa |
| `Report PR Cognitive Load` (trusted, dormido) | `pr-size-policy.yml` | Idéntico al primero, pero sobre `default_branch` con `pull_request_target` | `check-pr-size.cjs` con `grandfather-size-exceptions.json` | Mismo que el primero, pero pierde la prueba de provenance |
| `OpenCode V2 Released SDK Contracts` | `ci.yml:18-34` | `unittest` + `bash scripts/test-opencode-v2-contracts.sh` | Python unittest + bash | SDK se desincroniza del release |
| `Installer Module Path Tests` | `ci.yml:36-46` | `bash scripts/test-install-module-path.sh` | Bash | Instaladores en versiones equivocadas |
| `Go Format` | `ci.yml:48-64` | `go run ./internal/gofmtcheck` | Compilador de formato | Formato divergente |
| `Unit Tests` | `ci.yml:66-162` | `go test ./...` + bench módulo + ratchet de deadcode | Go test + bench journey | Defectos no cazados |
| `Claude Network-None Runtime` (Required) | `ci.yml:164-182` | El binario corre sin red, con `docker run --network none` | Docker + bash | El runtime puede depender de red en silencio |
| `Windows Runtime` (release-blockers subset) | `ci.yml:184-323` | Subset curado de tests con `go test -list` primero para drift | Go test en powershell | Defectos Windows-only escapan |
| `Darwin Runtime` (release-blockers curated) | `ci.yml:335-368` | Manifest curado, drift guard con `go test -list` | `scripts/darwin-release-blockers.sh` | Defectos macOS-only escapan |
| `Organic Runtime E2E` (matriz Ubuntu/Windows) | `ci.yml:370-472` | Suite e2e con OpenCode/Claude/Codex reales, opt-in por env | Go test con build tags | Defectos de integración con host pasan |
| `E2E Tests` (matriz 3 distros) | `ci.yml:474-546` | Suite completa Tier 1+2+3 en Ubuntu/Arch/Fedora | Docker buildx + bash | Defectos de distro específica escapan |
| `Check for new unreachable functions` | `ci.yml:161-162` (dentro de `unit-tests`) | Ratchet: nuevas funciones sin callers vs baseline | `scripts/deadcode-ratchet.sh` con `comm` | Código muerto crece sin freno |
| `Discord Notifications` (informativo) | `discord-notifications.yml` | Re-emite eventos a Discord | curl con `X-GitHub-Event` | Comunidad no se entera de releases/issues |

> **Detalles no triviales:**
> - `windows-runtime` no es `required_status_check` por el motivo de `ci.yml:209-211`: Defender puede romper el `Add-MpPreference`, y *"a CI lane must not go red because an optimisation was unavailable"*. El job está en el workflow pero no en el ruleset.
> - `darwin-runtime` **sí** está marcado como required en el comentario `ci.yml:332-334`, pero el ruleset no lo lista (sólo `Unit Tests` y los E2E). Esto sugiere que Alan tiene intención de activarlo pero no lo ha hecho — misma dinámica que `pr-size-policy.yml`.

### 3.2 El ratchet de deadcode — un patrón para nosotros

`scripts/deadcode-ratchet.sh:1-72` es un caso de estudio:

- **No es un clean gate.** Acepta el inventario actual (230 funciones no alcanzadas en `main`) y rechaza sólo lo **nuevo** (`comm -13 baseline current`).
- **El baseline se regenera con `--update`** y se commitea.
- **El locale está pineado** (`export LC_ALL=C`, línea 29) — *"comm(1) requires both inputs sorted under the SAME collation, and silently produces nonsense when they are not. A baseline sorted under en_US.UTF-8 and compared under C... reports every baselined entry as new"*. Misma clase de problema que `pip cache` ignorando `uv sync` (nuestro C-08 cerrado sin merge por falta de ahorro medible).
- **Distingue lo que NO caza**: ramas inalcanzadas dentro de funciones vivas, campos de struct no asignados, funciones llamadas con efectos muertos por configuración ausente (líneas 15-18). Es un gate honesto: declara sus límites.

> **Transferible a nosotros:** el veredicto de `odd/skill-ci-portable/source-notes.md` §6 lista `check_mutation_sites`, `check_crap`, `check_alantyle` como candidatos a simplificar. La forma `comm`-baseline-regenerable es ideal para `check_mutation_sites` (BASELINE 464 y subiendo) y para `check_alantyle` (si decide quedarse).

### 3.3 El drift guard del Darwin manifest

`scripts/darwin-release-blockers.sh:101-141` corre `go test -list` contra cada paquete del manifest y compara el listado contra los nombres declarados. Si un test renombrado o borrado sigue en el manifest, el job **falla antes** de ejecutar nada. Razonamiento (`scripts/darwin-release-blockers.sh:5-9`): *"A manifest entry naming a renamed or deleted test would therefore silently run nothing and the lane would go green while enforcing nothing"*.

> **Transferible a nosotros:** `check_vulture_guard` (#1143) hace exactamente esta idea para vulture; el principio es generalizable a `check_mutation_sites` (¿sigue apuntando a tests que existen?) y a la `BASELINE_SHRINK_ONLY` de vulture si la migramos.

### 3.4 Gates que se prueban a sí mismos

`pr-check.yml:50-57` corre `node --test` sobre los `.test.cjs` en el mismo job. Garantía: si cambias el parser, rompes los tests **en el mismo commit** que introduce el cambio. Es nuestra R5 (*"Todo lo que el CI ejecuta debe poder ejecutarse en local con un solo comando"*) aplicada al workflow.

---

## 4. Release flow

### 4.1 De commit a publicación — el camino feliz

1. **PR con issue aprobada** pasa los 7 required checks.
2. **Merge a `main`** dispara `ci.yml` (todos los lanes).
3. **Tag anotado `vMAJOR.MINOR.PATCH`** se empuja: `release.yml` se activa (línea 5-10: `!v*-*` excluye prerelease).
4. **`preflight` job** (`release.yml:22-96`):
   - `./scripts/require-ci-success.sh` — exige CI verde en el SHA exacto (línea 50).
   - `goreleaser release --snapshot --clean --skip=sign,publish` (línea 72-75) — genera el plan sin publicar.
   - `./scripts/verify-release-distribution-policy.sh` — verifica que las únicas distribuciones son Linux/macOS y Homebrew (Windows omitido por política, ver `docs/release-signing.md` "Windows distribution restoration gate").
   - `go run ./internal/providercontractbundlecmd verify --archive ...` — verifica el bundle de contrato.
   - `./scripts/release-preflight.sh` — verifica tag anotado, SHA triple (checkout, event, tag-peel), main remoto idéntico, working tree limpio, `go mod tidy -diff` (líneas 38-57).
   - `go test ./...`, `go vet ./...`, `go run ./internal/gofmtcheck`.
5. **`release` job** (`release.yml:97-191`):
   - Re-corre `release-preflight.sh`.
   - `./scripts/canonicalize-release-public-keys.sh` (línea 137) — valida anclas de confianza, rechaza duplicados, placeholder, claves de test.
   - Materializa la clave Minisign desde el secret de la environment protegida (`release`).
   - `./scripts/release-signing-preflight.sh` — firma un canary y lo verifica contra el ancla.
   - `goreleaser release --clean` con la clave.
   - `shred --remove` del fichero de clave (línea 184-186).
6. **`verify` job** (`release.yml:193-222`):
   - Re-descarga los assets publicados por GitHub.
   - `sha256sum --check --strict checksums.txt` contra el manifest firmado.
   - `minisign -VQ -m checksums.txt -x checksums.txt.minisig -P "$key"` — verifica la firma.
   - Verifica el comentario trusted: `"repo=Gentleman-Programming/gentle-ai;tag=vMAJOR.MINOR.PATCH"`.

### 4.2 La promoción de RC a estable

`promote-stable-rc.yml` es el **segundo** camino de release, manual por `workflow_dispatch` con tres entradas (`source_prerelease_tag`, `stable_tag`, `release_environment_policy_id`). Lo importante:

- **Lee el `source_prerelease_tag`** (regex `vMAJOR.MINOR.PATCH-rc.N`), exige que la `stable_tag` se derive de él (líneas 24-28).
- **Comprueba el estado de la release RC** vía GraphQL (línea 60): `draft=false, prerelease=true, immutable=true`. Sin esas tres, rechaza.
- **Detecta el estado de recuperación** (`recovery_state ∈ {fresh, resume-tag, reset-empty-draft, verify-existing}`) y sólo publica si está en `fresh`, `resume-tag` (tag creado, release ausente) o `reset-empty-draft` (release vacía). En `verify-existing` no republica — sólo verifica.
- **Re-firma el chequeo de procedencia**: vuelve a correr `release-signing-preflight.sh` con `RELEASE_SIGNING_TAG=$stable_tag` (líneas 214-220).
- **Restaura el acceso a `main`** vía `release/deployment-branch-policies/$POLICY_ID` después de verificar (job `restore-main-access`, líneas 292-308). Esto está atado a la `environment: release` y exige `RELEASE_ENVIRONMENT_POLICY_TOKEN` (un PAT separado, no `GITHUB_TOKEN`).

> **Lo más valioso para nosotros:** el desacople entre release **del binario** y promoción de versión de contrato. `contracts/review-provider-contract/CONTRACT_SEMVER` es un fichero versionado que el contrato bundle firma. Es la prueba de que un release **nunca** cambia el contrato por sorpresa: el SEMVER del contrato está en el repo, en la release RC, en la release estable.

### 4.3 El contrato que nunca se firma "porque CI fue verde"

El error histórico que `require-ci-success.sh` cierra está documentado en sus líneas 5-9: *"That is not hypothetical: v2.2.0 published green with CI failing on ee83e83d, because nothing in the release path had ever looked"*. Esto es **literalmente** nuestro `release-e2e-gate` (#1110): la evidencia del deploy requiere que la revisión anterior tuviera `release/e2e-production=success`.

---

## 5. Catálogo de ideas transferibles

Cada idea: qué hace `gentle-ai`, qué tenemos hoy, por qué la considero mejor, coste estimado (S/M/L).

### IDEA T1 — Doble gate de tamaño: informativo + trusted dormido

- **Qué hace:** `pr-check.yml:13-49` corre un check de tamaño informativo que falla el PR (autor → arregla). `pr-size-policy.yml` corre el **mismo cálculo** con `pull_request_target` y `sparse-checkout` de la política en `default_branch`, dormido por ahora. Cuando se active, el motor ya está probado, la política ya tiene `grandfathered_prs` y `validatePolicyTransition` valida el cambio.
- **Qué tenemos hoy:** un solo `check_pr_size.py` invocado desde `pr-size.yml`, falla cerrado si supera 400. La excepción `size:exception` se gestiona por etiqueta.
- **Por qué mejor:** separa el **acto de informar al autor** del **acto de proteger la rama por defecto**. La política dormida permite negociar la activación con un PR de un solo fichero (`enforcement: "enforcing"`) sin riesgo. Es nuestra R10 conmutada por dato.
- **Coste:** S — un workflow nuevo (10-50 LOC) + JSON de grandfathered + 187 LOC de `check-pr-size.cjs` portados (o reimplementados en Python).
- **Evidencia:** `pr-size-policy.yml:1-53`; `.github/scripts/check-pr-size.cjs:1-187`; `.github/grandfather-size-exceptions.json:1-6` (`enforcement: "dormant"`).

### IDEA T2 — Ratchet sobre la colección de funciones/baseline (en lugar de clean gate)

- **Qué hace:** `scripts/deadcode-ratchet.sh:41-44` corre `go run golang.org/x/tools/cmd/deadcode`, normaliza a `archivo\tsímbolo`, ordena y compara con `.deadcode-baseline.txt` por `comm`. Si hay entradas nuevas, falla; si hay entradas que desaparecieron, sólo avisa ("tighten the baseline"). `--update` regenera el baseline.
- **Qué tenemos hoy:** `check_mutation_sites` con BASELINE que sube (decisión 5 del veredicto), `check_crap`, `check_alantyle`, todos clean gates.
- **Por qué mejor:** convierte un gate que pediría "código perfecto" en uno que pide "código **no peor** que el actual". Es la única forma de adoptar un control que de otro modo sería inalcanzable. Aplicable textual a `check_mutation_sites` (BASELINE 464).
- **Coste:** M — sustituir el gate por la lógica de `comm -13 baseline current` + un fichero committed de baseline. Ya tenemos `scripts/vulture` casi en esa forma (#1143).
- **Evidencia:** `scripts/deadcode-ratchet.sh:22-49`; `odd/skill-ci-portable/source-notes.md:64` y §6.

### IDEA T3 — Drift guard con `go test -list` (o equivalente) antes de cualquier manifest/selector

- **Qué hace:** `scripts/darwin-release-blockers.sh:101-141` verifica que cada entrada del manifest existe antes de ejecutar nada. El comentario es explícito: *"a pattern matching nothing is a silent hole"* (líneas 162-169 de `windows-full-suite.yml`). El bench capability probe hace lo mismo en `ci.yml:428-441`.
- **Qué tenemos hoy:** `check_vulture_guard` (#1143) lo hace para vulture. No lo hacemos para `check_mutation_sites` ni para `e2e`/`integration`/`lint` cuando se selecciona por nombre.
- **Por qué mejor:** cierra la clase de bug "el test renombrado no falla porque nadie lo busca". Aplicable a cualquier selección por nombre en workflows.
- **Coste:** S — añadir un paso de "verifica que los nombres existen" antes del selector. Para `lint`, un `uv run ruff check --select <codes>` con un `0` después sería trivial.
- **Evidencia:** `scripts/darwin-release-blockers.sh:101-141`; `ci.yml:428-441`; `windows-full-suite.yml:161-169`.

### IDEA T4 — Desacoplar preflight de release del workflow de release (módulos de preflight reusables)

- **Qué hace:** `release.yml:22-96` corre `require-ci-success.sh`, `verify-release-distribution-policy.sh`, `release-preflight.sh`, unit tests, vet, format — **todos scripts versionados en el repo**, todos bash con `set -euo pipefail`. La política de release se valida en tres ejes independientes (CI previo, contenido a publicar, identidad del tag).
- **Qué tenemos hoy:** `check_release_evidence.py`, `check_release_e2e_required.py`, `production_smoke.py` — scripts nuestros, pero viven sólo en el job de `deploy.yml`. No hay un `release-preflight.sh` separado del workflow.
- **Por qué mejor:** si la release está mal, los scripts pueden correrse en local antes de empujar el tag; reproduce nuestra R5 (*"Todo lo que el CI ejecuta debe poder ejecutarse en local"*). Y desacoplar `release-preflight` del job significa que cualquier pipeline nuevo (release a staging, dry-run de release) lo hereda gratis.
- **Coste:** M — extraer los chequeos inline de `deploy.yml` a scripts en `scripts/`, añadir un job `release-preflight` que se pueda invocar por `workflow_dispatch` o desde `deploy.yml`.
- **Evidencia:** `release.yml:50`, `:80`, `:86`; `scripts/release-preflight.sh:1-58`; `scripts/require-ci-success.sh:1-57`; nuestro `deploy.yml` job `evidence` (líneas 46-68 del HANDOFF).

### IDEA T5 — Documentar la no-gate (Windows Full Suite)

- **Qué hace:** `windows-full-suite.yml:1-17` documenta en el comentario del workflow **por qué** se separó de `ci.yml` (deuda visible, no bloqueante) y **cuándo** se vuelve a integrar (*"once the eighteen are fixed, fold this back into ci.yml so it gates again"*).
- **Qué tenemos hoy:** `check_alantyle` ya decidimos pasarlo a informativo (sección 3.3 del HANDOFF). Pero el cómo — ¿en `lint` o en un job separado? — está abierto.
- **Por qué mejor:** la decisión "esto no bloquea pero es deuda" debe ser **visible y fechada** para que un futuro agente la revoque cuando pueda. Sin ese comentario, el próximo agente ve un job separado y lo borra o lo integra ciegamente.
- **Coste:** S — mover los chequeos informativos a un job propio y añadir el comentario contractual.
- **Evidencia:** `windows-full-suite.yml:3-17`; `ci.yml:209-211` (Windows Defender caveat); decisión 3 del HANDOFF.

### IDEA T6 — Compartir suite entre Linux y Windows con sharding por coste medido

- **Qué hace:** `windows-full-suite.yml:79-114` define **10 shards** dimensionados por coste medido en Linux (segundos) — no por letras A-Z, sino por clústeres de coste (TestR*, TestReview*, TestRevi*). El shard `cli-r-other` (líneas 100-102) cubre TestR* no reclamado por cli-review, con un arm vacío (`^TestR[A-Da-d]`) para mantener el espacio R tileado. Cada shard se **comprueba a sí mismo** antes de correr (líneas 161-169).
- **Qué tenemos hoy:** un único `test` job, 6-8 min, todo el camino crítico (#939). Sin sharding.
- **Por qué mejor:** nuestro `test` job es el eslabón débil (decisión 2 del HANDOFF: *"repartir `test` en shards (#939) y ahorrar la caché lo llevaría hacia ~6 min"*). El método de Alan — medir coste por selector, balancear shards — es lo que recomienda el HANDOFF.
- **Coste:** M-L — instrumentar los tests con tiempos por selector, escribir el shard matrix, duplicar la lógica en nuestro runner (`pytest -k` + `--collect-only`).
- **Evidencia:** `windows-full-suite.yml:38-67`; `odd/HANDOFF-ci-2026-09-30.md:87`.

### IDEA T7 — `workflow_dispatch` para re-run cuando el workflow ha cambiado

- **Qué hace:** `ci.yml:8-12` documenta que `gh run rerun` rechaza runs cuyo workflow ha cambiado desde, lo cual es exactamente cuando un re-run es más necesario (flaky conocido en commit listo para tag). La solución: `workflow_dispatch` permite re-correr el mismo commit contra el workflow nuevo.
- **Qué tenemos hoy:** nuestros workflows tienen `workflow_dispatch` pero no está documentado para qué sirve ni quién debe usarlo.
- **Por qué mejor:** es una invariante operacional documentada. Si un agente ve un fallo "infra" o "workflow actualizado", sabe que `gh workflow run ci.yml --ref <sha>` es el camino. La fricción "el único modo de re-correr CI en main es empujar otro commit" desaparece.
- **Coste:** S — verificar que todos nuestros workflows lo tengan (los principales sí) + una nota en `docs/codebase/ci.md` sobre cuándo usarlo.
- **Evidencia:** `ci.yml:8-12`.

### IDEA T8 — Contrato versionado + bundle firmado (para releases que rompen compatibilidad)

- **Qué hace:** `contracts/review-provider-contract/CONTRACT_SEMVER` es un fichero (un entero) versionado en repo. El release produce `gentle-ai-review-provider-contract-${SEMVER}.tar.gz` que se firma con el mismo Minisign que el binario. El `verify-release-assets.sh` exige que ese asset exista en la release publicada (líneas 39-44) y el workflow de promoción RC lee el mismo SEMVER desde el tag origen (líneas 51-54).
- **Qué tenemos hoy:** no versionamos contratos de ningún tipo (no tenemos API pública).
- **Por qué mejor:** si en el futuro tenemos una API o un SDK, este patrón lo deja autoexplicable. **Hoy no es transferible**; es **candidata doble** porque es también colaboración: documenta a los consumidores qué cambió.
- **Coste:** L — sólo si tenemos API. Anotar en el backlog como referencia para cuando llegue ese día.
- **Evidencia:** `release.yml:67-69`, `:144-146`; `promote-stable-rc.yml:71-78`; `verify-release-assets.sh:34-46`.

### IDEA T9 — Documento por tarea (`odd/tasks/<n>-<slug>.md`) con secciones fijas

- **Qué hace:** `odd/tasks/ga-4882-telemetry-lock.md` (50 líneas visibles) tiene secciones estables: **Claimed**, **Root-cause position (verified)**, **Tasks**, **Evidence**. Cada `Evidence` lleva fecha y enlaces a runs (`CI run 35883778782`).
- **Qué tenemos hoy:** `odd/HANDOFF-ci-2026-09-30.md` es esencialmente el mismo patrón, pero **para una sola épica** (#935). `odd/tasks/` existe en el repo (`ls odd/tasks` lista `1640-login-csrf.md` etc.) pero no es el patrón canónico para cada issue.
- **Por qué mejor:** un documento por tarea fija el ritmo de "qué sabemos, qué probamos, qué falta" en un lugar que sobrevive a la sesión y al agente. Alan lo usa como recibo de progreso.
- **Coste:** S — declarar la plantilla (claim, root-cause position, tasks, evidence) y crear el primer documento para una issue abierta.
- **Evidencia:** `odd/tasks/ga-4882-telemetry-lock.md:1-50`; `odd/tasks/remove-sdd-odd-only-main.md` (otro ejemplo).

---

## 6. Cosas que NO copiaríamos

### NC1 — Tres sistemas operativos en CI

`ci.yml` corre Linux + Windows + macOS en cada PR/push. Cada push a `main` consume ~30 min de runner de Windows y ~30 min de macOS. **No es sostenible** para `ardelperal/APAP_WEB` (que ni siquiera tiene binarios nativos). Mantener `windows-runtime` y `darwin-runtime` exige runners macOS que cuestan 10× los Linux (`ci.yml:328`). Lo que sí nos sirve: el patrón de "suite deslastada que se observa en `windows-full-suite.yml`" — pero no la obsesión de ejecutar el nativo en cada push.

### NC2 — `pull_request_target` para política "trusted"

`pr-size-policy.yml` usa `pull_request_target` para leer el `default_branch` con la política curada. Es un patrón estándar de GitHub, pero requiere cuidado: **`pull_request_target` se ejecuta con secretos** y un fork puede inyectar código en los logs. Para una sola lectura de JSON sin secretos está bien, pero cada vez que alguien añade un paso, hay que auditar. **No lo adoptamos** salvo que tengamos un caso claro de "política mantenida por el maintainer y chequeada contra el PR actual".

### NC3 — El complejo de release con Minisign, environment protegida, doble workflow, etc.

`release.yml` + `promote-stable-rc.yml` + `verify-release-assets.sh` + `release-signing-preflight.sh` + `canonicalize-release-public-keys.sh` es **una inversión enorme** para un binario Go que se instala vía `go install`. La justificación: distribuir un binario firmado fuera del módulo Go. **No publicamos binarios** — desplegamos via Coolify, y el firmamos con Cosign (lo tenemos en #1132-#1133). Lo que sí vale: la disciplina de **leer de vuelta lo publicado** (`verify` job) es adoptable (ver IDEA T4).

### NC4 — El lock-in de la `environment: release` con policies dinámicas

`promote-stable-rc.yml:117-125` añade y borra `deployment-branch-policies/$POLICY_ID` sobre la environment `release`. Requiere `RELEASE_ENVIRONMENT_POLICY_TOKEN` (un PAT separado). **No es necesario para nuestro modelo single-branch pre-MVP** (regla P4 del HANDOFF). Si en el futuro tenemos un flip post-MVP, considerar; ahora, no.

### NC5 — `discord-notifications.yml`

Re-emite eventos de release e issues a Discord vía webhooks. Es informativo, no bloquea, y nuestro `apap-app` no tiene una comunidad Discord de la magnitud de `gentle-ai`. Lo que sí sirve: la forma de enmascarar el webhook con `::add-mask::` y el regex de validación antes del POST (`discord-notifications.yml:26-29`). **No lo adoptamos** salvo que aparezca la necesidad.

### NC6 — Conventional Commits como regla dura del ruleset

Alan lo aplica a `commit_message_pattern`. Nosotros somos más laxos (sólo lo aplicamos a mensajes de PR, no de commit). **No copiamos** la regla dura — pero sí el patrón del **enforcement por regex** (lo tenemos con `branch-name`; extender a mensajes de PR sí).

---

## 7. Sin verificar

1. **Frecuencia exacta de fallo del CI principal.** Las ejecuciones de `ci.yml` en las últimas 30 son todas `success` — pero la muestra puede estar sesgada por selección (`gh run list` por defecto ordena por tiempo). No hice la consulta `--json` con breakdown por estado. Veredicto provisional: muy fiable.
2. **Si `darwin-runtime` está en los required status checks.** El comentario `ci.yml:332-334` dice que el maintainer debe añadirlo; la consulta al ruleset muestra que **no** está. Alan tiene intención de activarlo pero no lo ha hecho.
3. **Por qué `windows-runtime` queda en `ci.yml` y `windows-full-suite` se separa.** El comentario explica la cronología (deuda visible) pero no por qué `windows-runtime` (subset curado) sigue ahí y la suite completa se va. Suposición: `windows-runtime` cubre los release-blockers; la suite completa los integra. Sin tener acceso al Slack/Discord del proyecto, no verificable.
5. **El estado del `recovery_state=verify-existing` en producción.** El código lo trata como no-publicación, pero no pude verificar que se haya usado en una promoción real reciente.
6. **Quién aplica las etiquetas `type:*` y `status:approved` en producción.** El código lo lee pero no pude verificar el flujo del actor (humano o agente).
7. **El bench coverage.** `ci.yml:99-150` invoca journeys de bench (`j51`, `j59`, `j60`, `j75`, ...) en el job `unit-tests`. No verifiqué que cada journey tenga un test ejecutable que lo cubra — la lista de 13 journeys + el modelo-picker untagged (`j97`) parece exhaustiva pero requiere inspección individual.

---

## 8. Patrones de colaboración humano-IA (candidatas dobles)

Esta sección recoge patrones que son **a la vez** de CI y de cómo Alan colabora con agentes.

### COL1 — El `branch-pr` skill que arranca pidiendo autorización

`skills/branch-pr/SKILL.md:29-39`: el primer paso del workflow es **pedir permiso** (*"obtain explicit authorization for the remote destination, operation and credential/session"*). No asume, no sondea credenciales. Esto es CI (no se ejecuta ningún paso sin autorización) y a la vez colaboración (la IA sabe cuándo preguntar).

> **No transferible literal** (sus razones regulatorias son distintas), pero el **principio** — *"cada operación necesita su propia autoridad humana"* — sí lo es. Nuestro `gentle-ai review status` (HLV §6) ya lo hace para revisiones nativas.

### COL2 — `odd/tasks/<n>-<slug>.md` con timeline de evidencia

Documento de tarea con secciones fijas + entradas con fecha y run IDs. **Ya lo hacemos** en `odd/HANDOFF-ci-2026-09-30.md`. La versión de Alan lleva el timeline más atomizado (un fichero por issue, no por épica). Es la diferencia entre "handoff entre sesiones" (nuestro) y "recibo por issue" (suyo). Ambos válidos; el suyo escala mejor.

### COL3 — `AI_POLICY.md` declarativo y verificable

`AI_POLICY.md:38-39`: *"AI tools must not receive human attribution, including `Co-Authored-By`, `Reviewed-by`, `Tested-by`, `Signed-off-by`, approval, or equivalent credit"*. Es nuestra regla global ("sin atribución de IA en commits"), pero Alan la codifica como **política del proyecto**, no como convención. La hace cumplir por **revisión humana**, no por gate (línea 60: *"the project does not use automated AI detection or an automated disclosure gate"*).

### COL4 — Validación cruzada en el mismo workflow

`pr-check.yml:122`: el job `Check Issue Has status:approved` **reusa el output** del job anterior (`REFERENCES` env). Un solo parse, muchos consumidores. Es el mismo principio que nuestro `closingIssuesReferences` se rellena una vez — pero Alan lo hace en el **mismo workflow**, sin esperar a la API.

### COL5 — Conventional Commits en la skill, no en el workflow

Alan **sí** enforza commits en el ruleset (`commit_message_pattern`). Pero la skill `branch-pr/SKILL.md:162-223` lo explica en detalle con tabla de mapeo `type → label`. La IA que escribe el commit ya sabe el formato. **Doble enforcement: workflow + skill.** Nuestro `CONTRIBUTING.md` está detrás del patrón `documentation-alan-style`; todavía no lo tenemos como skill cargable.

---

## 9. Tabla resumen — transferible vs no, con coste

| Idea | Transferible | Coste | Referencia |
|---|---|---|---|
| T1 — Doble gate tamaño | sí | S | §5 IDEA T1 |
| T2 — Ratchet sobre baseline | sí | M | §5 IDEA T2 |
| T3 — Drift guard con `test -list` | sí | S | §5 IDEA T3 |
| T4 — Preflight reusables | sí | M | §5 IDEA T4 |
| T5 — No-gate documentada | sí | S | §5 IDEA T5 |
| T6 — Sharding por coste medido | sí | M-L | §5 IDEA T6 |
| T7 — `workflow_dispatch` para re-run | sí | S | §5 IDEA T7 |
| T8 — Contrato versionado + bundle | no (no aplica aún) | L | §5 IDEA T8 |
| T9 — Doc por tarea (`odd/tasks/`) | sí | S | §5 IDEA T9 |
| COL1 — Skill pide autorización | sí (principio) | S | §8 COL1 |
| COL2 — Timeline por issue | sí (ya lo hacemos, atomizar) | S | §8 COL2 |
| COL3 — `AI_POLICY.md` declarativo | sí | S | §8 COL3 |
| COL4 — Validación cruzada en workflow | sí (parcial) | M | §8 COL4 |
| COL5 — Conventional Commits en skill | sí | S | §8 COL5 |
| NC1 — Tres OS en CI | no | — | §6 NC1 |
| NC2 — `pull_request_target` | no (salvo caso claro) | — | §6 NC2 |
| NC3 — Release firmado complejo | no | — | §6 NC3 |
| NC4 — `environment: release` con policy | no (single-branch) | — | §6 NC4 |
| NC5 — Discord notifications | no | — | §6 NC5 |
| NC6 — CC duro en ruleset | no (regla nuestra más laxa) | — | §6 NC6 |

**Ideas transferibles concretas: 14** (T1-T9 + COL1-COL5). **Accionables a coste S: 8.** Coste M-L: 3. Las demás son candidatos para backlog o referencias para cuando cambie el contexto.

---

## 10. Notas finales sobre el método

- El comando `git clone --depth 50` deja el repo en `717087b`. Algunos commits referenciados en el informe pueden no aparecer en la historia shallow; cuando los cito, llevo SHA cuando está disponible o referencio el mensaje del commit visible.
- Las llamadas a `gh api` consultaron metadatos públicos únicamente: `repos/...`, `branches/main`, `rulesets`, `runs`. Sin issues, PRs, stars, comments, ni fork.
- La cuenta del repo es de **usuario** (`juan@barbat.dev`), no organización — coincide con la observación de nuestro #958.
- La rama principal tiene un solo committer "real" en las últimas 50: el bot `web-flow` (el servicio de GitHub para merges via UI) más Juan Barbat. Los merges del bot aparecen como `Merge pull request #N from <author>/<branch>`; el autor del branch es `barbatdev` o `egdev6` (otros contribuidores), no Alan. **Alan no usa su cuenta personal para push** — usa la de la organización? O el flujo es "los contribuidores externos empujan, Alan mergea vía UI". No verificado.
- El `odd/` directorio del repo `gentle-ai` contiene 29 ficheros en `odd/tasks/` — **el patrón de documentos por tarea** está activo y vigente, no es vestigio. Ejemplo notable: `odd/tasks/ga-4882-telemetry-lock.md` con 6 entradas en `Evidence` (cronología).

---

## Key Learnings

- El CI de `gentle-ai` se sostiene sobre tres invariantes invisibles: (1) cada release exige **leer de vuelta** lo publicado (`verify-release-assets.sh`), (2) cada manifest curado exige **drift guard** antes de ejecutar (`go test -list` vs el manifest), (3) cada política dormida vive en el repo lista para activarse (`grandfather-size-exceptions.json` con `enforcement: dormant`).
- El patrón **odd/tasks/<n>-<slug>.md** de Alan es la versión atomizada de nuestro `odd/HANDOFF-ci-2026-09-30.md`: un documento por issue con secciones fijas (Claimed, Root-cause position, Tasks, Evidence) y timeline de runs/PRs. Escala mejor entre sesiones; nosotros lo aplicamos a una épica entera.
- La elegancia de Alan está en declarar **lo que el gate NO hace** (`scripts/deadcode-ratchet.sh:15-18`; `ci.yml:209-211`) y en **versionar la política dormida** (`.github/grandfather-size-exceptions.json`). Esa honestidad reduce la deuda oculta y permite la activación reversible.