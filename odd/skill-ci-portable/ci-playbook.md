# CI Playbook para agentes IA — ardelperal/APAP_WEB

**Propósito.** Navegar el CI de este repositorio sin quemar reruns: cada regla de este playbook es una lección que costó al menos un rojo, un rerun o un diagnóstico erróneo. Si va a abrir un issue, abrir un PR, esperar CI, clasificar un rojo, mergear o tocar producción, aplique la regla del ciclo correspondiente **antes** de actuar.

**Contexto del repo en una línea.** FastAPI + HTMX con CI de Actions (`ci.yml`), gates deterministas (`issue-spec`, `pr-size`, `vulture`, `gitleaks`), branch protection con `strict: true`, 3 checks requeridos (`branch-name`, `required`, `pr-size / pr-size`) y un deploy a producción vía Coolify con evidencia por revisión.

**Checklist ejecutable.** El equivalente mecánico de las reglas 5 y 6 vive en `scripts/preflight.py`: `uv run python scripts/preflight.py` reproduce los pasos del job `lint` antes de empujar. Este playbook es el resto: lo que ningún script puede comprobar por usted.

**Recuento.** 20 reglas, agrupadas por ciclo de vida: CREAR ISSUE (1), ABRIR PR (2-4), CI EN VUELTA (5-7), CLASIFICAR ROJOS (8-10), MERGE (11-15), PRODUCCIÓN (16-17), ENTORNO Y RECURSOS (18-20).

---

## CREAR ISSUE

### Regla 1 — Abra cada issue desde el inicio con el contrato canónico completo de `check_issue_specs.py`

**Por qué costó un rojo.** Tres PR (#1156, #1157, #1159) llegaron a CI con el gate `issue-spec` en rojo porque la issue vinculada usaba un formato acortado: faltaban secciones, los encabezados usaban `##` en vez de `###`, o la etiqueta `status:approved` no estaba aplicada antes de abrir el PR. El preflight local **no puede** cazar esta clase de fallo: el gate lee la issue remota por la API de GitHub, no su copia local. Cada caso costó un rojo de CI y un ciclo de corrección.

**Procedimiento correcto.** Al crear la issue, incluya las seis secciones con encabezados `###` exactos, en este orden:

1. `### Problema y contexto`
2. `### Evidencia verificable`
3. `### Alcance y no objetivos`
4. `### Criterios de aceptación`
5. `### Plan de validación`
6. `### Dependencias y riesgos`

Y aplique la etiqueta antes de abrir el PR:

```bash
gh issue create --title "<tipo>: <resumen>" --label status:approved --body-file /tmp/issue-body.md
gh api repos/ardelperal/APAP_WEB/issues/<N> --jq '.labels[].name'   # verificación: status:approved presente
```

La rama deriva la issue para el gate: nómbrela `<tipo>/<N>-<slug>` (ver regla 4).

---

## ABRIR PR

### Regla 2 — Aplique todas las etiquetas al crear el PR, nunca después

**Por qué costó un rojo.** En #1145 y #1150 las etiquetas (`chain:partial`, `type:*`) se aplicaron tras crear el PR: el workflow no declara el disparador `labeled`, así que `issue-spec` no se reevalúa y el gate queda en rojo hasta un rerun manual o un push nuevo. Además, `gh pr edit` está roto en la versión instalada (retirada de GraphQL Projects classic), así que corregir etiquetas después es más lento de lo que parece.

**Procedimiento correcto.** Todas las etiquetas en el comando de creación:

```bash
gh pr create --label chain:partial --label "type:chore" --title "..." --body-file /tmp/pr-body.md
```

Si tiene que tocar el PR después de crearlo, use la API REST directamente:

```bash
# Cambiar la rama base:
gh api -X PATCH repos/ardelperal/APAP_WEB/pulls/<N> -f base=main
# Añadir etiquetas:
gh api -X POST repos/ardelperal/APAP_WEB/issues/<N>/labels -f 'labels[]=chain:partial'
```

Y si el cambio afecta a `issue-spec`, espere un rerun o un push: etiquetar después no lo reevalúa.

### Regla 3 — Verifique `closingIssuesReferences` tras crear el PR; si GitHub no registra el cierre, use `chain:partial` y cierre a mano. Nunca ponga palabras de cierre en el título

**Por qué costó un rojo.** Doble incidente. (a) GitHub rellena `closingIssuesReferences` unos segundos después de crear el PR, y a veces **nunca**: en B11 (#1119 vía #1144 y #1145) la referencia quedó como mención con `willCloseTarget: false` durante más de 15 minutos, con el cuerpo diciendo `Closes #1119` y el gate fallando con «add 'Closes #1119' to the PR body» — un mensaje que culpa al cuerpo de algo que el cuerpo ya tenía y que ningún gesto del autor corregiría. (b) En #1138, poner la palabra de cierre en el **título** del PR hizo que el merge commit cerrara #1073 antes de tiempo, y la issue hubo que reabrirla.

**Procedimiento correcto.** Tras crear el PR, verifique el registro del cierre:

```bash
gh api graphql -f query='query{repository(owner:"ardelperal",name:"APAP_WEB"){pullRequest(number:<N>){closingIssuesReferences(first:5){nodes{number}}}}}' --jq '.data.repository.pullRequest.closingIssuesReferences.nodes'
```

- Si devuelve la issue: correcto, siga.
- Si está vacío tras unos segundos (o nunca aparece): aplique `chain:partial` como excepción **declarada en el cuerpo del PR** (documente lo probado) y cierre la issue a mano después del merge, con un comentario que lo explique.
- En ningún caso escriba `Closes`/`Fixes`/`Resolves` en el título del PR.

### Regla 4 — Solo el PR punta de la cadena lleva `Closes #<issue>`; los intermedios llevan `Refs` + `chain:partial`, con rama `<tipo>/<N>-<slug>`

**Por qué costó un rojo.** Los gate deterministas (`issue-spec`) derivan la issue del nombre de rama y exigen el cierre en la punta; poner `Closes` en un tramo intermedio deja la issue cerrada antes de que la cadena termine (misma familia que #1138) y deja tramos sin su excepción declarada, en rojo.

**Procedimiento correcto.**

```bash
# Tramo intermedio (rama derivada de la issue de la cadena):
git checkout -b feat/1138-nombre-del-slice origin/main
# Cuerpo del PR intermedio: "Refs #<issue-cadena>" + etiqueta chain:partial
gh pr create --label chain:partial --title "..." --body "Refs #1138 ..."
# Tramo punta (último de la cadena):
# Cuerpo: "Closes #<issue-cadena>", sin chain:partial
```

El nombre de rama `<tipo>/<N>-<slug>` es lo que usa `check_issue_specs.py` para derivar la issue: no lo desvíe.

---

## CI EN VUELTA

### Regla 5 — Antes de cada push, ejecute el preflight completo; la suite de pytest no ejecuta los pasos de lint

**Por qué costó un rojo.** Tres PR (#1082, #1133 entre ellos) llegaron a CI con un fallo que la suite completa local no veía, porque los pasos del job `lint` de `ci.yml` no son tests y pytest no los ejecuta (fricción B3 de #935). El coste se pagó en rojos de CI hasta que #1145 materializó la paridad en `scripts/preflight.py`.

**Procedimiento correcto.**

```bash
uv run python scripts/preflight.py          # reproduce los pasos del job lint; verificado: 19 pasos
uv run python scripts/preflight.py --list   # lista los pasos sin ejecutarlos
```

Estado verificado el 2026-09-30 sobre `52fd1c5`: el preflight lista **19 pasos** y `actionlint` aún no está en el job `lint` de `ci.yml` (ni en local ni en origin/main `0c78ac9`; sin coincidencia al grep). El «20 pasos incluyendo actionlint» corresponde a la decisión 4 del handoff, todavía pendiente: cuando entre, serán 20.

### Regla 6 — Vulture con el intérprete del venv; `check_alantyle` sobre cada doc tocada, antes del push

**Por qué costó un rojo.** El `python3` del sistema no tiene `vulture` (a propósito, reproduce #1142): antes de que `check_vulture_guard` fallara en voz alta (#1143), el gate imprimía «OK (0 confirmed-dead)» sin haber comprobado nada — el único falso verde puro del CI (A9 de #935). Y `check_alantyle` rechazó un PR (#1133) por una palabra en mayúsculas sin defecto real detrás.

**Procedimiento correcto.**

```bash
.venv/bin/python -m vulture app scripts --min-confidence 80   # o como lo invoque el job lint; nunca el python del sistema
python3 scripts/check_alantyle.py docs/<docs-tocadas>.md       # ALL-CAPS de énfasis y "podría" son violaciones; PAT → "personal access token"
```

Mantenga el hábito del intérprete del venv aunque el guard hoy falle en voz alta.

### Regla 7 — Un job de Actions se detiene en el primer paso rojo: reproduzca también todos los pasos posteriores

**Por qué costó un rojo.** Al arreglar el primer paso fallido y empujar, el rojo reaparecía en un paso siguiente que nunca se había ejecutado. En el trabajo de #1119/#1145 los bucles manuales llegaron a tener 16 de los 19 pasos y aún así aparecieron fallos nuevos en pasos nunca vistos.

**Procedimiento correcto.** Tras corregir el primer paso, no empuje todavía: ejecute localmente los pasos restantes del job en orden (`uv run python scripts/preflight.py` los recorre todos secuencialmente). Solo empuje cuando la cadena completa pase.

---

## CLASIFICAR ROJOS

### Regla 8 — Clasifique un rojo solo después de identificar el paso que falla vía API; nunca por grep del log

**Por qué costó un rojo.** Los scripts del workflow hacen `echo` de cadenas alarmantes («Docker daemon is not answering») como encabezados propios del log: ese texto no es un diagnóstico. En PR #1114 se diagnosticó infra por el log, costó 3 runs desperdiciados y se abrió la issue #1130, que terminó cerrada como **misdiagnosis**. Recuerde además: el job `security` corre en GitHub-hosted `ubuntu-24.04`, **no** en la flota self-hosted.

**Procedimiento correcto.**

```bash
# 1. Identifique el run y el job:
gh run list --repo ardelperal/APAP_WEB --branch <rama> --limit 5
gh run view <run-id> --repo ardelperal/APAP_WEB --json jobs --jq '.jobs[] | {name, conclusion}'
# 2. Identifique el paso exacto que falló (fuente de la clasificación):
gh api repos/ardelperal/APAP_WEB/actions/jobs/<job-id> --jq '.steps[] | select(.conclusion=="failure") | .name'
# 3. Solo entonces clasifique: paso de código → fix y push; paso de infra/transitorio → regla 9.
```

### Regla 9 — `rerun --failed` solo para transitorios de etiqueta o infra; tras un push de corrección, la CI nueva se dispara sola

**Por qué costó un rojo.** `gh run rerun --failed` re-ejecuta el **SHA original** del head: si el arreglo exige un push, el rerun reproduce el mismo rojo y quema un ciclo de espera (~10 min, porque el reintento espera también a `test` e `integration` — fricción B12 de #935).

**Procedimiento correcto.**

```bash
# Fix que exige push: simplemente empuje; el nuevo run se dispara solo
git push origin <rama>
# Rerun legítimo (etiqueta aplicada tarde, flake de runner, paso sin log):
gh run rerun <run-id> --failed --repo ardelperal/APAP_WEB
```

### Regla 10 — Todo gate que toque producción se ejecuta de verdad antes de darlo por hecho

**Por qué costó un rojo.** `production_smoke.py` recibía 403 de Cloudflare por el `User-Agent` de `urllib`: solo lo cazó una ejecución real contra producción, no la suite local (fricción B1 de #935, resuelta en #1134 y #1135). Ninguna prueba de escritorio sustituye a la ejecución real de un gate que cruza la frontera de producción.

**Procedimiento correcto.** Antes de declarar terminado un gate con efecto en producción (smoke, batería e2e, flag de e2e), ejecútelo una vez real contra el entorno y verifique el resultado observado, no el esperado. Para la batería completa, regla 16 y 17.

---

## MERGE

### Regla 11 — Con `strict`, «required status checks are expected» significa que main se movió: actualice la rama o use auto-merge

**Por qué costó un rojo.** Con `strict: true` y 3 checks requeridos, cada merge de otro agente invalida los PR abiertos: el merge se rechaza con «3 of 3 required status checks are expected» y la CI hay que repetirla (ocurrió con #1141 justo antes de fusionarlo; fricción B2 de #935).

**Procedimiento correcto.**

```bash
# Estado verificado en vivo el 2026-09-30: allow_auto_merge=true, allow_update_branch=true, strict=true,
# contexts = branch-name, required, pr-size / pr-size.
gh api repos/ardelperal/APAP_WEB --jq '{allow_auto_merge, allow_update_branch}'

# Opción preferida: dejar que GitHub lo haga
gh pr merge <N> --auto --merge --repo ardelperal/APAP_WEB     # nunca --delete-branch

# Actualización manual. Secuencia DETERMINISTA (nunca espere-y-rece):
# 1. PUT update-branch → 202. Con token de USUARIO, SÍ dispara CI sobre el nuevo head
#    (verificado en vivo: PR #1166, run nuevo sobre el head actualizado segundos tras el 202).
#    El caveat de GITHUB_TOKEN solo aplica a updates disparados DESDE un workflow.
gh api -X PUT repos/ardelperal/APAP_WEB/pulls/<N>/update-branch
# 2. A T+2min, verifique que existe un run FRESCO sobre el NUEVO head SHA:
gh run list --branch <rama> --limit 3 --json headSha,createdAt,status
#    El createdAt del run debe ser posterior al 202 y el headSha debe coincidir.
# 3. Si NO hay run fresco → fallback:
gh workflow run ci.yml --ref <nuevo-head-sha>
#    workflow_dispatch re-ejecuta el mismo commit contra el workflow vigente: el único caso
#    en que un rerun-tras-fix es legítimo (complementa la regla 9).
# 4. mergeStateStatus=BLOCKED mientras corren los checks es lo ESPERADO, no un error:
#    el merge se dispara vía el auto-merge armado en el paso de la opción preferida
#    cuando todo queda verde.
```

Nota de verificación: el procedimiento y el estado de settings están verificados por API; la documentación del procedimiento en `docs/codebase/merge-workflow.md` **no se encontró** en origin/main a fecha de este playbook (el §15 llega a §15.7, sin mención de `update-branch`). Si el doc se actualiza después, prevalece el doc; hoy, prevalece la API verificada. Evidencia del sondeo del 2026-09-30 sobre el PR #1166: tras el PUT de las 20:12:59Z, los runs (36771058148 y siguientes) se crearon a las 20:13:06Z sobre el head actualizado — la secuencia determinista de arriba está verificada de extremo a extremo.

### Regla 12 — En cadenas apiladas, el aislamiento verde incluye los jobs CI-only, el fixture viaja con el slice y la baseline de vulture sube y baja dentro de la cadena

**Por qué costó un rojo.** En #1138 un slice verde en todas las matrices locales era rojo en el job `e2e` dockerizado (no corre en local) porque necesitaba un seed fixture que no llevaba (fricción A11 de #935). En #1137/#1138 la baseline de vulture de los slices aditivos tuvo que subir en los tramos que añadían helpers y bajar en el tramo que los consumía, para restaurar el ratchet en la punta.

**Procedimiento correcto.**

- Intermedios: `Refs #<issue>` + `chain:partial`; la punta lleva `Closes` (regla 4).
- Si el flip de un slice necesita un fixture, **el fixture viaja en ese slice**.
- Baseline de vulture: súbela en el slice aditivo (mismo PR) y bájala en el slice que empieza a usar los helpers. El ratchet queda restaurado en la punta de la cadena.
- Antes de pedir revisión del tramo, compruebe también los jobs que solo corren en CI (`e2e` dockerizado), aunque todas sus matrices locales estén verdes.

### Regla 13 — PR ≤ 400 líneas (adiciones + eliminaciones, sin lockfiles) y `size-exception-reason:` con formato exacto

**Por qué costó un rojo.** El gate `pr-size` y el contrato de #1141 exigen el motivo como **una sola línea al inicio de columna, exactamente una aparición**, sin texto pegado en la línea siguiente y sin dejar el marcador de la plantilla; los arreglos de tests e2e son prolijos: 17 fixes ocuparon ~415 líneas y obligaron a plantearse el troceado.

**Procedimiento correcto.**

```bash
git diff --stat origin/main...HEAD | tail -1        # estime el presupuesto ANTES de escribir código
```

- Si supera 400: parta por unidad de trabajo, luego encadene (regla 12); `size:exception` es el último recurso.
- En el cuerpo del PR, si aplica excepción, primera línea de su bloque:

```text
size-exception-reason: <por qué en una línea>
```

- Y en el propio diff: una línea por unidad de trabajo (commits convencionales, sin atribución de IA).

---

### Regla 14 — CERO VIGÍAS: ninguna IA mantiene procesos vivos esperando CI, merges o veredictos

**Por qué costó un rojo.** La sesión cerrada del 2026-09-29 dejó dos watchers zombis (PID 3786126, `watcher2.sh`, y PID 3217218) corriendo un día entero con autoridad de merge/close sobre el repo: actores no deterministas que podían actuar por sorpresa. Y en la sesión de este playbook, los bucles de sondeo de CI se estancaron 3 polls sin que nadie lo notara (adopción alantyle).

**Procedimiento correcto.**

a) Esperar CI → mergear: NUNCA sondear en vivo. Arme `gh pr merge <N> --auto --merge` y siga con otra cosa; GitHub espera (con `allow_auto_merge` + `allow_update_branch` en true, GitHub además actualiza la rama automáticamente cuando main se mueve — ver regla 11).
b) Si un paso necesita verificar el re-disparo de CI tras update-branch: UNA sonda a T+2min (ver regla 11), no un bucle.
c) Recordatorios o verificaciones periódicas: `schedule` workflows o `workflow_dispatch` que abren o actualizan issues — nunca un proceso vivo de sesión.
d) Si hereda un vigía de otra sesión: verifique qué hace (lea el script); cumplido su propósito → kill + shred del script; inesperado → STOP y reporte su contenido.
e) Emisión de progreso: un worker debe emitir una llamada visible por transición (merge, check rojo, cambio de fase) para que el orquestador detecte estancamiento sin sondear a ciegas.

Nota: esta regla es el antídoto del patrón watcher que la épica heredó (`watcher2.sh`); los zombis fueron eliminados el 2026-09-30.

### Regla 15 — ORDEN DE MERGE DETERMINISTA: con N PRs armados, el orden y las excepciones se declaran AL INICIO de la ola, no a mitad de cascada

**Por qué costó un rojo.** Épica #935 (2026-09-30): PR #1151 quedó CONFLICTING a mitad de cascada porque otros PRs tocaron sus ficheros después de que se cortara su rama; PR #1158 se bloqueó por `pr-size` (415/400) sin `size-exception-reason` pre-declarado; PR #1153 llegó al gate `issue-spec` con formato no canónico. Tres bloqueos que un orden declarado al inicio habría eliminado.

**Procedimiento correcto** (ola de merges con N PRs armados):

1. **Batch update-branch al inicio de la ola**: TODOS los PRs armados se actualizan contra el main vigente (PUT update-branch) ANTES del primer merge. Los conflictos se resuelven una vez, al inicio — no a mitad de cascada.
2. **Declarar el orden**: dependencias primero (la base antes que quien la consume), y los PRs que tocan los mismos ficheros en secuencia contigua. Declarar en el encargo del orquestador: "orden de merge: A → B → C".
3. **Pre-declarar las excepciones**: si algún PR supera el presupuesto de 400 líneas, su `size-exception-reason` se escribe en el body ANTES del primer merge (nunca a mitad, como ocurrió en #1158). Si alguna issue llega al gate con formato no canónico, se reformatea antes del primer merge.
4. **Sin merges ajenos durante la ola**: coordinar con otros actores (humanos o IAs) para que no fusionen a main mientras la ola corre; cada merge ajeno invalida la ola y fuerza re-empezar el paso 1.
5. **Conflicto real a mitad de ola**: si el rebase de un PR revela conflicto de contenido con otro PR de la ola (no con main), parar y escalar — la ola se cortó mal.

Nota: vivido en las cascadas #1113-#1117 y #1153-#1158 y en la ola Cadete #1150-#1167.

---

## PRODUCCIÓN

### Regla 16 — Nunca reinicie la aplicación build-pack de Coolify con `POST /applications/{uuid}/restart`; el flag se voltea con PATCH de envs + recreate del compose

**Por qué costó un rojo.** En la app con build-pack de docker, `restart` **redespliega el HEAD de main**: `ApplicationDeploymentJob` neutraliza `restart_only`, así que con main adelantado respecto a lo desplegado, un reinicio inocente despliega código sin pasar por el gate de evidencia. El procedimiento correcto tiene una ventana breve de 502 (~2-10 s) con imagen fijada.

**Procedimiento correcto.**

```bash
set -a; . ~/.config/opencode/secrets.env; set +a   # credenciales; no imprima valores

# 1. Voltee el flag por API (ejemplo: APAP_E2E_AUTH_ENABLED):
gh="" # (no aplica) — use la API de Coolify:
curl -s -X PATCH "${COOLIFY_BASE_URL}/api/v1/applications/cxm5x2f489eos8nr8e1qv1c6/envs" \
  -H "Authorization: Bearer ${COOLIFY_ACCESS_TOKEN}" -H "Content-Type: application/json" \
  -d '{"key":"APAP_E2E_AUTH_ENABLED","value":"true"}'

# 2. Refleje el valor en el .env del host y recrecie los contenedores con la imagen fijada:
sudo sed -i 's/^APAP_E2E_AUTH_ENABLED=.*/APAP_E2E_AUTH_ENABLED=true/' \
  /data/coolify/applications/cxm5x2f489eos8nr8e1qv1c6/.env
sudo docker compose -p cxm5x2f489eos8nr8e1qv1c6 \
  -f /data/coolify/applications/cxm5x2f489eos8nr8e1qv1c6/docker-compose.yaml up -d --force-recreate

# 3. Verifique siempre la revisión desplegada después:
curl -s https://apap.romancaba.com/healthz | jq .revision
```

**Invariante de la épica #909:** el flag `APAP_E2E_AUTH_ENABLED` se apaga al terminar, **pase lo que pase** (también si la batería falla o usted aborta). Reposo verificado: `/e2e/login` responde 404 y la variable no-preview vale `false` en Coolify.

### Regla 17 — Ejecute la batería de producción desde un worktree en la revisión desplegada y registre el veredicto con sus deselecciones documentadas

**Por qué costó un rojo.** Ejecutar los tests de `main` contra código desplegado anterior produjo 18 fallos falsos (test-vs-deploy skew): el fallo era del test nuevo, no del despliegue. Y en la vida real (#1152, arreglado en main vía #1155) un test de CSP hubo que deseleccionarlo con motivo documentado para poder registrar un veredicto honesto.

**Procedimiento correcto.**

```bash
REV=$(curl -s https://apap.romancaba.com/healthz | jq -r .revision)
git worktree add ../apap-app-worktrees/e2e-${REV:0:7} $REV
cd ../apap-app-worktrees/e2e-${REV:0:7} && uv sync    # dependencias de ESA revisión
# Ejecute solo las suites de la puerta (docs/runbooks/e2e-production.md), nunca todo tests/e2e/ (escriben datos).
```

- Si un test falla por skew, clasifíquelo primero (regla 8): nunca registre `failure` por desfase del lado del test.
- Si deselecciona tests con fallo conocido, registre el veredicto **con las deselecciones documentadas en la descripción**; jamás registre `success` con fallos vivos sin deselección.
- El veredicto se registra sobre el SHA de `/healthz`, nunca sobre origin/main:

```bash
gh api --method POST repos/ardelperal/APAP_WEB/statuses/<sha-de-healthz> \
  -f state=success -f context=release/e2e-production -f description="<qué se ejecutó>"
```

- Un solo mint de credenciales por ventana; al terminar, flag apagado + verificación de reposo (regla 16).

---

## ENTORNO Y RECURSOS

### Regla 18 — Nunca reutilice un `topic_key` de Engram para registros acumulativos; si el MCP se niega, use el CLI

**Por qué costó un rojo.** El upsert de Engram **sustituye** el contenido: el registro acumulado de fricciones #4368 perdió 10 de sus 11 entradas (recuperadas de `sync_mutations` como #4369-#4371). Además, el MCP falla con «multiple active runtime sessions» cuando hay ventanas abiertas, y las sesiones arrancadas fuera del directorio del proyecto se misdetectan de proyecto.

**Procedimiento correcto.**

```bash
# Registro acumulativo: una observación nueva por entrada, SIN topic_key:
engram save "<título>" "<texto>" --type discovery --project apap
```

- Si el MCP se niega por sesiones activas o proyecto equivocado, no bloquee: use el CLI de arriba y siga.
- Si una sesión fuera del directorio misdetecta el proyecto, informe del hecho al orquestador en lugar de forzar escrituras.

### Regla 19 — Conozca los quirks de la toolchain de GitHub instalada y confirme los cambios de settings leyendo de vuelta

**Por qué costó un rojo.** Tres fricciones silenciosas: `gh pr edit` falla (retirada de GraphQL Projects classic) y hay que ir a REST; `gh variable get` falla y hay que usar `gh variable list`; y un PATCH de settings de GitHub puede leer de vuelta un valor obsoleto durante segundos, lo que induce a concluir que el cambio falló cuando no es así.

**Procedimiento correcto.**

```bash
# Editar PR (base) y etiquetas: REST, no gh pr edit
gh api -X PATCH repos/ardelperal/APAP_WEB/pulls/<N> -f base=main
gh api -X POST repos/ardelperal/APAP_WEB/issues/<N>/labels -f 'labels[]=chain:partial'

# Variables de repo:
gh variable list --repo ardelperal/APAP_WEB

# Tras cualquier PATCH de settings: lea de vuelta antes de concluir
gh api repos/ardelperal/APAP_WEB --jq '{allow_auto_merge, allow_update_branch}'
```

Si una lectura de vuelta muestra el valor viejo, espere unos segundos y relea; no repita el PATCH en bucle.

### Regla 20 — ORQUESTACIÓN DETERMINISTA: ninguna espera es abierta; toda espera tiene deadline, verificación y fallback

**Por qué costó un rojo.** La épica #935 (2026-09-29/30) vivió tres estancamientos detectados por juicio del orquestador (contadores congelados entre polls): un worker cancelado y relanzado desde estado verificado, un vigía zombi de otra sesión corriendo un día entero con autoridad de merge, y bucles `--watch` que ocultaban progreso. Ninguno se detectó ni resolvió de forma determinista — cada uno costó tiempo de sesión. La lección de diseño es de jerarquía: el sistema NO debe depender de una IA mirando. Toda espera que se pueda codificar como mecanismo o script debe vivir en el mecanismo o el script; la IA es el último recurso, no el vigía por defecto.

**Procedimiento correcto.** Toda espera o vigilancia se diseña por esta jerarquía de preferencia — mécanismo > script > IA:

1. **MECANISMO PRIMERO.** Prefiera automatización nativa de GitHub que no necesita IA ni sesión viva:
   - `gh pr merge <N> --auto --merge` armado + `allow_update_branch` en true: GitHub espera, actualiza la rama y fusiona — nunca `--watch` (ver regla 11).
   - Required checks fail-closed: GitHub bloquea el merge; nadie tiene que vigilarlo.
   - `schedule` workflows y `workflow_dispatch` para recordatorios, auditorías y bumps de seguridad: abren issue/PR sin sesión viva (ver regla 14c).
   - Hooks post-commit para propagación (skills, tokens de skill).
   - Vivido: los PR de la épica se fusionaron con auto-merge armado, no con `--watch`; las issues de seguimiento (#1146, #1147) se cerraron con veredicto registrado en comentario, no con un vigía pendiente.
2. **SCRIPT SEGUNDO.** Donde no haya mecanismo nativo: un script versionado en el repo con deadline y fallback explícitos, que cualquier actor ejecuta — el determinismo vive en el script, no en el juicio de quien lo corre. Vivido: `scripts/preflight.py` y el guard de `actionlint`/`coverage-ratchet.sh` reproducen gates como código, no como pasos que una IA recuerda.
3. **IA ÚLTIMO.** Una IA solo para juicios: disposición de veredictos, resolución de conflictos de contenido, decisiones de gobierno. Y cuando una IA espera algo, lo hace bajo las restricciones a)-e) de abajo — pero el objetivo del diseño es que NADA quede esperando a una IA.

Restricciones a)-e) para el caso IA-como-último-recurso (toda espera de IA, y todo encargo delegado a un worker, las cumple):
a) Toda espera de CI se delega a GitHub: `gh pr merge <N> --auto --merge` armado + `allow_update_branch` en true — GitHub espera y fusiona; la sesión NO hace watch.
b) Toda tarea delegada lleva en su encargo: deadline explícito por fase, obligación de emitir una llamada visible por transición (issue creada, commit pusheado, check rojo), y la regla de auto-report: comando colgado >3 min → matarlo, registrar el error, continuar o parar.
c) Estancamiento se define por NÚMEROS: dos lecturas consecutivas del contador sin delta tras un mensaje de gobierno = cancelar y relanzar desde estado verificado (git/PR/issue — nunca desde memoria del worker). Sin juicio intermedio.
d) Toda recuperación arranca verificando el estado real (fetch, rev-parse, estado de PRs/issues) y REUTILIZA lo que exista (issues, ramas, worktrees, stashes) — el trabajo abandonado se reclama, no se duplica.
e) Los ficheros de estado (stash, worktrees, drafts) se seleccionan por identificador (tag_name, número, path), nunca por índice — vivido: `. [0]` apuntó a un draft viejo.

Nota: esta regla gobierna tanto a los orquestadores como a los workers; se aplica a toda delegación desde la épica #935.

---

## Fuentes vivas

- **Handoff de la sesión CI:** `odd/HANDOFF-ci-2026-09-30.md` (§6 «Lecciones que costaron rojos», 8 reglas originales) y `odd/skill-ci-portable/source-notes.md`.
- **Issue épica #935:** comentarios «Consolidación de fricciones del CI» (A1-A11, B1-B10) y «Nuevo hallazgo B11» (2026-09-30).
- **Issues #1146 y #1147:** seguimiento de fricciones del CI.
- **Engram (proyecto `apap`):** #4368 (registro perdido por upsert) y #4369-#4371 (fricciones recuperadas).

Este playbook devendrá asset de `references/` de la futura skill `ci-pattern` (véase `odd/HANDOFF-ci-2026-09-30.md` §8): las reglas aquí escritas son el catálogo de fricciones que la skill empaquetará con sus `assets/` parametrizados.

---

## Protocolo de mejora continua — qué hacer cuando aparece una fricción nueva

Las 20 reglas anteriores son el resultado congelado de un proceso vivo. Este protocolo es ese proceso: qué hacer cuando aparece una fricción que ninguna regla cubre. Es un bucle, no un paso: se repite cada vez que la realidad del pipeline contradice a la documentación.

1. **Detectar con evidencia.** Una fricción solo existe si tiene un incidente real citado (PR, issue, run, `fichero:línea`). Sin evidencia no es fricción, es opinión.
2. **Registrarla inmediatamente.** Issue en el tracker (formato canónico) o el catálogo de fricciones del proyecto; clasificada: bloqueante (fix ya, dentro del pipeline) o seguimiento (issue propia).
3. **Arreglarla por el pipeline normal.** Nunca un parche fuera del ciclo issue → worktree → PR → CI → merge; y nunca mezclada con otro cambio.
4. **Destilarla en regla.** Si la fricción costó un rojo, entra al playbook con su ternario completo (regla → rojo que la creó → procedimiento correcto). Sin ese paso, el mismo rojo vuelve con la próxima IA.
5. **Vigilar la recurrencia.** La segunda ocurrencia de la misma fricción ya no se arregla a mano: es candidata a automatización (gate, workflow programado, o cambio de diseño).
6. **Auditar periódicamente.** Una pasada (tipo «criterio 7») que compare cada afirmación de la doc contra la realidad de los workflows, corrija desvíos, y declare qué claims quedaron verificados.

### Antipatrones

| Síntoma | Antídoto |
|---|---|
| Se arregla pero no se registra | El rojo vuelve |
| Se registra sin evidencia | Ruido en el tracker |
| Se arregla mezclado | Review imposible |
| La regla vive en la conversación | Conocimiento tribal que muere con la sesión |
| Segunda ocurrencia arreglada a mano | Fricción permanente |

Este protocolo nació de la épica #935 (2026-09-29/30): 20+ fricciones detectadas, registradas en #4368/#935, arregladas por el pipeline, y destiladas en las 20 reglas de este playbook.
