# HANDOFF — mejora del CI de APAP_WEB (sesión 2026-09-29/30)

> ## ⚠️ INSTRUCCIÓN DEL USUARIO PARA LA IA QUE ESTÁ EJECUTANDO LA BATERÍA e2e (2026-09-30 ~15:15 UTC)
>
> **Apaga el flag `APAP_E2E_AUTH_ENABLED` de producción cuando termines, pase lo que pase** (también si las pruebas fallan o abortas). El usuario lo ha pedido expresamente.
>
> 1. Apagar: `PATCH ${COOLIFY_BASE_URL}/api/v1/applications/cxm5x2f489eos8nr8e1qv1c6/envs` con `{"key":"APAP_E2E_AUTH_ENABLED","value":"false"}` y luego `POST …/applications/cxm5x2f489eos8nr8e1qv1c6/restart` (credenciales: `set -a; . ~/.config/opencode/secrets.env; set +a`; no imprima valores). Se detectó encendido a las 15:09:23 UTC.
> 2. Verificar el reposo: `curl -s -o /dev/null -w '%{http_code}' https://apap.romancaba.com/e2e/login` debe dar **404**, y la variable no-preview del entorno de la app debe valer `false`.
> 3. Registrar el resultado real sobre `2d5024a1dd87b33c5b7f33016d66fd3c1abdf4e6` (`release/e2e-production`, `success` o `failure`) y borrar `.auth/state.json`.
> 4. Contexto y advertencias (tests de `main` contra código anterior a #1073, worktree `e2e-2d5024a` preparado): sección 3.1 más abajo.
>
> La sesión de Claude que escribió esto **no ejecutó la batería, no tocó el flag ni Coolify** y ya está cerrada; no hay nadie más operando el flag.


Léalo entero antes de tocar nada. Está escrito para retomar sin esta conversación. **Actualizado tras fusionar #1145 (2026-09-30 14:54 UTC).** Repositorio real: `ardelperal/APAP_WEB` (el directorio local se llama `apap-app`). Fecha de corte: 2026-09-30, `main` = `52fd1c5`.

## 0. Objetivo y órdenes vigentes del usuario

- **Objetivo final:** dejar el CI «perfecto» y **al final convertirlo en una skill portable** (nombre propuesto `ci-pattern`). El usuario pidió sacar toda la información para ello. Premisa del patrón: **dos ramas en paralelo sobre el mismo repo, en worktrees separados y con superficies que no se solapan.**
- **Decisiones ya tomadas por el usuario:** validar `2d5024a` con la batería autenticada (1a), aplicar la opción B de `strict` (2, la aplica la otra IA, sección 3.2.1) y pasar `check_alantyle` a informativo (3). **Autorización vigente:** «estás autorizado a lo que necesites toda la sesión» (dado el 29/09) y «toma el control de todo esto». Aun así, decisiones de gobernanza/producción se le consultan (ver sección 3).
- **Reglas del usuario** (`~/.claude/CLAUDE.md`): commits convencionales **sin atribución de IA**; usar `bat/fd/rg/sd/eza` y no `cat/grep/find/sed/ls`; respuestas cortas, **una pregunta a la vez y esperar**; verificar antes de dar la razón; en español rioplatense con el usuario, artefactos técnicos en inglés y docs del repo en castellano formal («usted»); el merge es `--merge` (commit de fusión), **nunca borrar la rama remota**.
- **Definición de «hecho» para escribir la skill** (sección 8): 7 criterios, 4 ya cumplidos.

## 1. Qué está hecho (fusionado en `main`)

| PR | Qué | Issues |
|---|---|---|
| #962 | `ci.yml` y CodeQL corren en PR con cualquier base | cierra #933 |
| #1110 | `release-e2e-gate` ligado a la revisión (estado por SHA) | cierra #1082 |
| #1111 | `issue-spec` determinista (rama + `chain:partial` + `closingIssuesReferences`) | cierra #956 |
| #1132, #1133 | evaluador `--context`, selector de rutas sensibles, `production-smoke`, gate con dos estados | cierra #1131 |
| #1135 | smoke con `User-Agent` propio (Cloudflare daba 403), host de la redirección, reintentos | cierra #1134 |
| #1141 | `size:exception` pasa a campo `size-exception-reason:` del cuerpo del PR | cierra #1121, #941, #896 |
| #1143 | `check_vulture_guard` falla en voz alta si vulture no corrió | cierra #1142 |
| #1145 | `scripts/preflight.py`: reproduce los 19 pasos del job `lint` en ~30 s | cierra #1119 (a mano, ver B11) |

Además: 6 alertas CodeQL de #1038 descartadas como falso positivo con justificación; producción salió de `460c56f1` a `2d5024a` tras el arranque del gate.

## 2. En vuelo AHORA

**Nada en vuelo.** El PR #1145 (preflight canónico `scripts/preflight.py`) se fusionó el 2026-09-30 a las 14:54 UTC (`52fd1c5f`) y #1119 se cerró a mano. #1144 quedó cerrado, sustituido por #1145. GitHub no registró nunca el `Closes #1119` (fricción **B11**, en #935, Engram #4424 y las notas de la skill), y por eso el PR llevó `chain:partial` como excepción declarada. El preflight funciona desde `main`: `uv run python scripts/preflight.py` pasa 19 de 19 pasos en unos 30 s.

El deploy que disparó ese merge falló en `release-e2e-gate`, como todos los anteriores, por el e2e pendiente de `2d5024a` (sección 3, punto 1).

## 3. Decisiones del usuario (estado a 2026-09-30, tras preguntarle)

| # | Decisión | Estado |
|---|---|---|
| 1 | e2e de `2d5024a` (bloquea todos los deploys) | **DECIDIDO: opción (a), validar con la batería autenticada.** Nadie la ha ejecutado aún |
| 2 | `strict` sin cola de fusión (#958) | **DECIDIDO: opción B, aprobada por el usuario. LA APLICA LA OTRA IA** (la sesión que escribe esto no ha tocado el repositorio). Pasos exactos en 3.2.1 |
| 3 | `check_alantyle` bloqueante | **DECIDIDO: pasarlo a informativo** (aceptó la recomendación). Sin implementar |
| 4 | `actionlint` en el `lint` | **Sin respuesta.** Recomendación: sí. No abrir la issue sin preguntarle |

### 3.1 Decisión 1 — cómo ejecutar la validación de `2d5024a`

- Producción sigue en `2d5024a1dd87b33c5b7f33016d66fd3c1abdf4e6` con `release/smoke-production=success` (real) y `release/e2e-production=pending`.
- Seguir `docs/runbooks/e2e-production.md`: encender el flag `APAP_E2E_AUTH_ENABLED` vía Coolify, ejecutar **solo** las suites de la puerta (nunca todo `tests/e2e/`: escriben datos), y **apagar el flag al terminar, sea cual sea el resultado** (invariante de la épica #909). Después registrar el resultado real: `gh api --method POST repos/ardelperal/APAP_WEB/statuses/2d5024a1dd87b33c5b7f33016d66fd3c1abdf4e6 -f state=success|failure -f context=release/e2e-production -f description="<qué se ejecutó>"`. Con `failure`, rollback por `docs/runbooks/deploy-rollback.md`.
- **Requiere credenciales que la sesión anterior no tenía:** la API de Coolify y el secreto `APAP_E2E_AUTH_SECRET` en el entorno (el propio runbook lo dice). Lo ejecuta el usuario o una sesión que las tenga.
- **Efecto siguiente:** hay 64 commits sin desplegar y entre ellos rutas sensibles (`csrf.py`, `config.py`, `e2e_auth.py`, `magic_link.py`). Al validar `2d5024a` se desbloquea el próximo deploy, y **ese deploy dejará su propio `release/e2e-production=pending`**, que exigirá otra validación antes del siguiente. Es el diseño (#1131), no un fallo.

#### Acceso a Coolify desde este VPS (comprobado el 2026-09-30, **no se ejecutó la batería**)

- El **MCP de Coolify** no aparece en las herramientas de la sesión de Claude porque está configurado en **opencode**: `~/.config/opencode/opencode.json` → `mcp.coolify` = `npx -y @masonator/coolify-mcp@latest`, con `COOLIFY_ACCESS_TOKEN` y `COOLIFY_BASE_URL` leídos de `~/.config/opencode/secrets.env` (no lo imprima; cargue las variables con `set -a; . ~/.config/opencode/secrets.env; set +a`).
- Instancia: `panel.romancaba.com`. Lectura de prueba `GET /api/v1/version` → **HTTP 200, versión 4.3.23**. Es decir, la API es alcanzable con esas credenciales desde este mismo VPS.
- Permisos: el usuario del sistema es `ubuntu` (uid 1001) con **`sudo` sin contraseña** y grupo `docker`; equivale a root cuando hace falta.
- **El secreto de la batería** (`APAP_E2E_AUTH_SECRET`, 64 hex) no está en `secrets.env`: según el runbook existe en el entorno de la app en Coolify y como secreto de GitHub Actions. Obtenerlo por la API de Coolify (lectura del entorno de la app `APAP_COOLIFY_APP_UUID`) y exportarlo solo en la shell que ejecuta la batería; **nunca en argv, en logs ni en ficheros del repo**.
- Los pasos completos (encender el flag, ejecutar solo las suites de la puerta, apagar el flag, registrar el estado) están en `docs/runbooks/e2e-production.md`. Riesgo a tener presente: mientras el flag está encendido, la ruta `/e2e/login` de producción está activa (por eso la épica #909 la limita a una ventana y exige apagarla siempre); tras #1136-#1140 tiene suelo de longitud del secreto y lista de permitidos, pero **debe apagarse aunque las pruebas fallen**.
- **El usuario aún no ha dicho que la sesión anterior la ejecute.** La sesión que escribe esto se detuvo antes de tocar producción; quien la ejecute debe tener su OK explícito para la ventana de producción.

#### AVISO 2026-09-30 15:10 UTC: la batería ya la está ejecutando otra sesión

- El usuario me autorizó a ejecutar la batería con el flag apagado al terminar. Al preparar la ejecución encontré que **otra sesión (casi seguro la otra IA) ya la había lanzado**: `APAP_E2E_AUTH_ENABLED` de producción se actualizó a `true` a las **15:09:23 UTC** (`updated_at` en Coolify; en reposo debe ser `false`), `/e2e/login` respondía 401 (flag encendido) y había un proceso `pytest` de las suites de la puerta con `APAP_E2E_BASE_URL=https://apap.romancaba.com` corriendo desde `/home/ubuntu/repos/apap-app`. **Detuve mi ejecución y no toqué el flag, Coolify ni el estado de la revisión** para no cortar la suya.
- **Quien lo esté ejecutando debe dejar el flag en `false` pase lo que pase.** Verificación de reposo: `curl -s -o /dev/null -w '%{http_code}' https://apap.romancaba.com/e2e/login` debe dar **404**, y en Coolify (`GET /api/v1/applications/cxm5x2f489eos8nr8e1qv1c6/envs`) la variable no-preview `APAP_E2E_AUTH_ENABLED` debe valer `false`. Mientras esté encendido, producción expone la ruta con el código anterior a las correcciones de #1073.
- **Detalle que puede falsear el resultado:** producción corre `2d5024a`, que **no incluye** ninguno de los commits de las correcciones de #1073 (`803bc4d`, `09e4729`, `af06bc5`, `f0b3ecb`, `af03d0c`). La ejecución en curso usa los tests de `main` (más nuevos que el código desplegado): un fallo puede ser del test nuevo y no del despliegue. Si la batería falla, **repetirla con los tests de la misma revisión**: dejé preparado el worktree `/home/ubuntu/repos/apap-app-worktrees/e2e-2d5024a` (desacoplado en `2d5024a`, dependencias sincronizadas, Chromium funcionando, 119 tests recogidos, lista de suites de ese runbook en el `scratchpad` de la sesión y en `git show 2d5024a:docs/runbooks/e2e-production.md`). Retirar ese worktree al acabar (`git worktree remove --force … && git worktree prune`).
- **La aplicación en Coolify** es `apap-web`, UUID `cxm5x2f489eos8nr8e1qv1c6`, estado `running:healthy`. Hay entradas de entorno duplicadas con `is_preview=true` (valor `false`, sin tocar); la que importa es la de `is_preview=false`.
- **Cuando termine la batería:** registrar el resultado real sobre `2d5024a1dd87b33c5b7f33016d66fd3c1abdf4e6` (`release/e2e-production`, `success` o `failure`, con descripción de lo ejecutado) y limpiar `.auth/state.json`. Si falla, no hacer rollback sin el usuario.

### 3.2 Decisión 2 — consejo experto sobre `strict` (#958)

Hechos verificados: el repo es público y de una **cuenta de usuario** (no organización), así que la merge queue no está disponible (según #958; no se contrastó con la documentación de GitHub); `strict: true`; la CI de un PR tarda **10-12 min** (615-739 s en los últimos 8 runs verdes); y **`deploy.yml` (job `evidence`, líneas 46-68) exige que el árbol de la fusión sea idéntico al del PR revisado** («main moved: merged tree differs from the reviewed branch tree» y se niega a desplegar).

Ese último hecho **no está en #958 y cambia la ecuación:** `strict` no es solo comodidad, es lo que hace sólida la evidencia del deploy (el CI verde del PR prueba exactamente el árbol que aterriza). Consecuencias por opción de #958:

- **C (`strict: false` + CI en `push`) — no recomendada.** Cualquier fusión no equivalente dejaría el deploy sin evidencia y lo bloquearía, y además permitiría que una combinación rota llegue a `main` y dispare un deploy automático. Exigiría rediseñar el `evidence` (usar el CI del push como prueba), que es trabajo y riesgo grandes.
- **A (migrar a organización + merge queue) — la mejor a largo plazo**, solo si hay otros motivos para mover el repo (URLs, runners, secretos, Coolify).
- **B (`allow_update_branch` + `allow_auto_merge`) — recomendada ahora.** Mantiene `strict` y la solidez del deploy, es un ajuste reversible, y quita el trabajo manual de «actualizar la rama y esperar». **Límite honesto:** con `strict`, si `main` vuelve a moverse mientras espera, el auto-merge se detiene hasta que alguien actualice la rama; y una actualización hecha con `GITHUB_TOKEN` **no dispara CI** (comportamiento conocido de GitHub, no probado aquí), así que automatizarla del todo exigiría un PAT o una GitHub App (decisión de seguridad aparte). Sin eso, la actualización la hace el agente con `gh api -X PUT repos/ardelperal/APAP_WEB/pulls/<N>/update-branch`.
- **Lo que de verdad reduce el coste es bajar la CI:** el camino crítico son `pr-size → lint → test (~350 s) → build → e2e → required`. Repartir `test` en shards (#939) y ahorrar la caché lo llevaría hacia ~6 min, y con ello cada repetición por `strict` duele la mitad.
- **Disciplina para dos ramas en paralelo:** fusionar de una en una y actualizar la otra rama **inmediatamente**, sin esperar; con superficies disjuntas la actualización no tiene conflictos.

**Recomendación: B + shards de `test` (#939); A solo si el repo cambia a organización; C descartada mientras el deploy dependa de la identidad de árboles.** Aplicar B es `gh api -X PATCH repos/ardelperal/APAP_WEB -f allow_auto_merge=true -f allow_update_branch=true` (ajuste del repositorio: pedir el OK del usuario y documentarlo en `docs/codebase/merge-workflow.md` y `CONTRIBUTING.md`).

### 3.2.1 Aplicar la opción B (APROBADA por el usuario; la ejecuta la otra IA, no la sesión que escribió esto)

Estado al escribir: **no aplicada.** `allow_auto_merge` y `allow_update_branch` están en `false`, `strict` en `true`. El usuario dijo «sí, aplica la B» y pidió que quedara en el traspaso para la otra IA, así que es una autorización explícita para este ajuste concreto y **para nada más** del repositorio.

1. Comprobar el estado actual: `gh api repos/ardelperal/APAP_WEB --jq '{allow_auto_merge,allow_update_branch}'` y `gh api repos/ardelperal/APAP_WEB/branches/main/protection --jq '.required_status_checks|{strict,contexts}'` (esperado: `false`, `false`, `strict:true`, checks `branch-name`, `required`, `pr-size / pr-size`).
2. Aplicar: `gh api -X PATCH repos/ardelperal/APAP_WEB -f allow_auto_merge=true -f allow_update_branch=true`. Si la API rechaza el campo, no insistir: informar al usuario con el mensaje de error.
3. **Leer de vuelta** (regla de la skill de gobernanza): repetir el paso 1 y comprobar `true`/`true` y que `strict` y los tres checks requeridos **no han cambiado**. No tocar `enforce_admins`, `required_conversation_resolution` ni ninguna otra protección.
4. Probar que funciona con un PR real en cuanto haya uno abierto y desactualizado: `gh api -X PUT repos/ardelperal/APAP_WEB/pulls/<N>/update-branch` debe devolver 202, y el PR debe reejecutar CI (aviso: una actualización hecha con `GITHUB_TOKEN` en un workflow no dispara CI; hecha con el token del usuario por `gh api` sí). Auto-merge de un PR: `gh pr merge <N> --auto --merge` (nunca `--delete-branch`).
5. Documentarlo en `docs/codebase/merge-workflow.md` y en la sección de fusión de `CONTRIBUTING.md` (castellano formal; cargar antes `documentation-alan-style`; evitar palabras en mayúsculas fuera de la lista de acrónimos, `check_alantyle` las rechaza): qué se activó, cómo usar `update-branch` y `--auto`, y el límite honesto (si `main` se mueve mientras espera, el auto-merge se detiene hasta actualizar la rama).
6. Ese cambio de documentación va en un PR normal con su issue (formato `###` + criterios de aceptación) y la revisión nativa si `assess` la marca como debida. Antes de empezar, anotar en #958 un comentario con la decisión y la fecha. No cerrar #958 hasta haber verificado el paso 4.
7. Siguen siendo del usuario, y no forman parte de esta autorización: pasar a la opción A (organización) y cualquier uso de un PAT o una GitHub App para automatizar la actualización de ramas.

### 3.3 Decisión 3 — `check_alantyle` informativo (decidido)

Implementar en un PR con issue propia (formato `###` + criterios de aceptación): que el paso siga ejecutándose y **muestre** las violaciones (anotaciones o salida), pero **no falle el job**; conservar el detector como guía de revisión de docs (`AGENTS.md` dice que una doc sin `documentation-alan-style` se rechaza en revisión). Tocar: el paso del job `lint` en `ci.yml`, sus pines en `tests/test_ci_workflow.py`, `docs/quality/ci-gate-inventory.md` y `docs/codebase/quality-gates.md`, y comprobar el efecto sobre `scripts/preflight.py` y sobre la matriz del agregador `required`. Evidencia de que no detectaba un defecto real: falló por `BOTH` en mayúsculas (ALAN003) en #1133.

### 3.4 Decisión 4 — `actionlint` (pendiente)

Cazó `services.minio.command`, una clave inexistente en Actions (`ci.yml:1251`, relacionada con #894/PR #900), más 6 avisos de `shellcheck` y 5 de etiquetas de runners propios (se resuelven con un `.github/actionlint.yaml`). Cuesta segundos. Recomendación: añadirlo al job `lint` (el preflight lo recoge solo) y arreglar o declarar los hallazgos. **Preguntar al usuario antes de abrir la issue.** Nota: el usuario pidió expresamente que `actionlint` estuviera instalado y lo está en todo el sistema (ver sección 5).

## 4. Trabajo pendiente, por prioridad

1. **#1118** (root cause en el agregador `required`) y **#1120** (auto lock-in de ratchets): tienen worktrees de otra ola con trabajo **abandonado sin commits** (3 ficheros cada uno). Procedimiento probado con #1121 y #1119: comprobar procesos vivos con `ss`/`ps` (nunca `pgrep -f`), comentar la reclamación en la issue, **arreglar el formato de la issue** si usa `##` en vez de `###` o le falta «Criterios de aceptación» (si no, `issue-spec` falla con un mensaje engañoso), y lanzar un escritor que adopte el trabajo en su propio commit, fusione `main` y corrija en otro.
2. **Una issue única con los seguimientos no bloqueantes de las revisiones nativas** (no están creadas):
   - preflight: un `lint` sin pasos imprime `PASSED (0/0 steps)` (falso verde); pasos con `working-directory`/`env`/`shell`/`if` se ignoran en silencio; sin timeout por paso; pasos sin `name:` se confunden; los humos reales son opt-in.
   - vulture: proteger `find_spec`, test del `find_spec` real, aserción estricta del límite de stderr, hallazgos con stderr no vacío.
   - `production_smoke`/`deploy.yml`: reintento del POST de estado, no distinguir fallo previo al smoke del fallo del smoke, sección del runbook en español dentro de un doc en inglés, el evaluador dice «e2e» también para el contexto del smoke.
   - `size-exception-reason`: mensaje que distinga el motivo del rechazo, no volcar el motivo sin acotar en el log, nombrar por separado la obtención del cuerpo y la comprobación.
3. **Mejorar el mensaje de `issue-spec`** (B4 y B11): decir el nivel de encabezado esperado y que GitHub no registra un cierre existente.
4. **A9 y B3 cerrados; siguen abiertos** A2, A3 (#1112), A4, A5, A7 (runners), A10, A11, B2 (#958), B7, B8, B10. Lista completa con estado en los comentarios de #935 («Consolidación…» y «Nuevo hallazgo…»).
5. **Tramo 5 de la auditoría:** #1087-#1093 (versión única de Python, `make install` con uv, script de detección de UI, trivy y `.trivyignore`, `size:exception` sin motivo, guard de labels sin cablear, comentarios falsos) y #1112 (huellas de gitleaks ancladas a línea).
6. **Una cadena real de PR encadenados con `chain:partial` y CI en cada tramo**, de extremo a extremo: sigue sin probarse (criterio 4 de «hecho»).
7. **Al final: escribir la skill** (sección 8).

## 5. Estado del entorno (cosas que cambié y que conviene conocer)

- **Engram:** daemon gestionado `systemctl --user … engram.service` con drop-in `~/.config/systemd/user/engram.service.d/autosync.conf` → `~/.config/engram/autosync.env` (`ENGRAM_CLOUD_AUTOSYNC=1`, allowlist `access2web-blueprint,gentle-ai,apap,gestion_riesgos`); symlink `~/.local/bin/engram → ~/go/bin/engram`; binario en `2.2.2-…3284dcc` instalado con `go install github.com/Gentleman-Programming/engram/v2/cmd/engram@main` (**¡con `/v2`!**; sin él instala la línea v1 antigua); copia de seguridad `~/go/bin/engram.prev-c556cca`; cursor global de pull adelantado al final del flujo por un defecto upstream (sesiones con `directory` en blanco). Plugin de Claude actualizado a 0.1.4 (**se aplica al reiniciar**). Un agente `pi` relanza `engram serve` si el puerto 7437 queda libre.
- **Engram, escritura:** el MCP falla con «multiple active runtime sessions» cuando hay ventanas abiertas: use `engram save "<título>" "<texto>" --type … --project apap` (CLI, crea una observación nueva). **Nunca use `topic_key` en registros acumulativos** (el upsert sustituye): #4368 perdió 10 de 11 entradas; recuperadas de `sync_mutations` como #4369-#4371.
- **Herramientas instaladas:** `actionlint` 1.7.12 y `shellcheck` 0.11.0 (brew) **enlazadas en `/usr/local/bin` para todo el sistema** con `sudo ln -sf` (cualquier usuario y agente las encuentra), `fd` (brew); `bat` y `eza` (binarios en `~/.local/bin`; el prefijo de Homebrew es de otro usuario y `brew upgrade` falla por permisos). **No** hay `vulture` en el `python3` del sistema, a propósito (reproduce #1142).
- **`gh`:** `gh pr edit` y `gh variable get` no sirven en esta versión; use `gh api` REST (PATCH `/pulls/N`, POST `/issues/N/labels`) y `gh variable list`.
- **Worktrees vivos:** `1004-login-csrf`, `894-e2e-minio` (PR #900 abierto), `1118-…` y `1120-…` (otra ola, trabajo abandonado sin commits). Los demás se retiraron tras fusionar.

## 6. Cómo se trabaja (procedimiento probado; sígalo)

**Ciclo por unidad de trabajo:** issue aprobada con formato válido → worktree `../apap-app-worktrees/<N>-<slug>` desde `origin/main` con rama `<tipo>/<N>-<slug>` → documento `odd/tasks/<N>-….md` (sin seguimiento) → **escritor delegado** (subagente `general-purpose`, con superficies permitidas, TDD, suite completa, RED/GREEN, comprobación real y un commit) → **verificación propia** (repetir lo crítico, sobre todo la prueba real) → revisión nativa → push y PR → CI → fusión.

**Lecciones que costaron rojos (aplique siempre):**
1. Un gate que toca producción se **ejecuta de verdad** antes de darlo por hecho (el 403 de Cloudflare por `User-Agent`).
2. La suite completa **no** ejecuta los pasos de `lint` (no son tests). Antes de empujar: los 19 pasos del job `lint`. Desde que se fusione #1145: `uv run python scripts/preflight.py` (27 s). Hasta entonces, los pasos están en `.github/workflows/ci.yml` (job `lint`); mis bucles manuales llegaron a tener 16 de 19.
3. Un job de Actions se detiene en el primer paso rojo: reproduzca **todos** los pasos posteriores.
4. Etiquete **al crear el PR** (`gh pr create --label …`); etiquetar después no relanza `issue-spec`.
5. `closingIssuesReferences` se rellena unos segundos después de crear el PR (y en B11 nunca).
6. `strict`: si otro fusiona mientras espera, la fusión falla con «3 of 3 required status checks are expected»: fusione `origin/main` en la rama, empuje y espere la CI otra vez.
7. Un fallo transitorio del runner (paso de Python de `issue-spec` sin log) se distingue **mirando el paso que falla**; `gh run rerun --failed` solo con el run completo.
8. `size-exception-reason:` en el cuerpo: **una sola línea**, exactamente una aparición al inicio de línea (forma llana o con el nombre entre acentos graves), sin texto pegado en la línea siguiente y sin dejar el marcador de la plantilla; la etiqueta `size:exception` es opcional.

**Revisión nativa (Gentle AI), pasos exactos:**
1. `gentle-ai review status --cwd <wt> --contract gentle-ai.review-integration/v2 --agent claude-code --next-transition --base-ref origin/main --committed-only` (si pide selección de ficheros sin seguimiento, repita con `--untracked-scope exclude --expected-untracked-inventory <sha256>`) → ejecutar el `next_transition.execute.command` (START) → devuelve el **sobre de consentimiento**: preséntelo al usuario con `AskUserQuestion` (2 opciones, `granted`/`declined`) y ejecute **solo** la invocación elegida (`declined` una sola vez).
2. Con `granted`: **aparte el documento ODD sin seguimiento** fuera del worktree (si no, el STATUS pide una selección), ejecute el comando de STATUS que devolvió el START (**con su `base-ref` fijado a un SHA**, no `origin/main`, que se mueve) y lance las capturas en paralelo con los tokens `arguments[].token` de cada entrada. Si una lente da `correction_required`: continuación del proveedor → `capture-correction-plan --correction-lines=N` → STATUS (`corrected_candidate_unavailable`) → **commit de la corrección** → `capture-validation`. Con `approved`: ejecutar el `next_transition.execute.command` que devuelve el STATUS (`review.acknowledge-approved`). Restaurar el documento.
3. Los hallazgos están en `.git/gentle-ai/review-transactions/v2/<lineage>/review-state.json` (`.state.fix_finding_ids`, `.state.admitted_role_results[].value.result.findings`). Solo los `fix_finding_ids` obligan a corregir; el resto son seguimientos.

## 7. Dónde está cada cosa

- **Este fichero:** `/home/ubuntu/repos/apap-app/odd/HANDOFF-ci-2026-09-30.md`. **Notas de la skill:** `odd/skill-ci-portable/source-notes.md` (12+1 reglas de diseño con evidencia, arquitectura, piezas reutilizables, catálogo de fricciones, reglas de trabajo en paralelo, esquema de la skill). **Documentos de tareas:** `odd/tasks/` (sin seguimiento, como los demás).
- **GitHub:** épica **#935** (comentarios «Fricción observada al abrir el PR de #1082», «…primer uso real de `production_smoke.py`», «Consolidación de fricciones del CI», «Nuevo hallazgo… (B11)»); umbrella **#1065**; épica de producción **#909** (excluye ejecutar la batería autenticada en CI: no lo reabra sin decisión).
- **Engram (proyecto `apap`):** #4344 y #4342 (sync de engram), #4366 (decisión del smoke), #4369-#4371 (fricciones recuperadas), #4372 (convención de registros), #4373 (plan de la skill), #4424 (B11), y el traspaso (ver abajo).
- **Scripts del patrón** (candidatos a `assets/` de la skill): `check_release_evidence.py`, `check_release_e2e_required.py` + `.github/release-e2e-paths.txt`, `production_smoke.py`, `check_pr_size.py`, `check_issue_specs.py`, `check_required_jobs.py`, y (tras #1145) `preflight.py`.

## 8. Definición de «hecho» para escribir la skill (estado)

1. Sin falsos verdes conocidos — **hecho** (A9, #1143); queda el `0/0 steps` del preflight (seguimiento).
2. Paridad de preflight (#1119) — **hecho** (#1145); queda el `0/0 steps` como seguimiento.
3. `strict`/cola de fusión (#958) resuelto o su coste aceptado — **pendiente, decisión del usuario**.
4. Una cadena real de PR encadenados con CI en cada tramo — **pendiente**.
5. Gates sin evidencia de defecto real simplificados o retirados — **pendiente** (`check_alantyle`, `check_mutation_sites`, `check_crap`, docstrings informativos, `test_ci_workflow.py`).
6. Deploy con evidencia automática por revisión — **hecho** salvo el trámite manual de rutas sensibles (que es el diseño).
7. Docs alineadas con los workflows — **pendiente** (8 contradicciones de la auditoría inicial, ver #935 y la conversación; una parte ya se corrigió en #1141/#1135).

Al escribir la skill: `skills/ci-pattern/SKILL.md` versionada en el repo, siguiendo `skill-creator` y `skill-style-guide`, con `assets/` parametrizados (regex de rama, presupuesto, etiquetas, contextos de estado, rutas sensibles, URL de salud, `User-Agent`) y `references/` con el catálogo de fricciones y el veredicto de gates. Cargue `documentation-alan-style` para cualquier doc del repo.

## 9. Primeros pasos recomendados para la sesión nueva

```bash
cd /home/ubuntu/repos/apap-app && git pull --ff-only origin main
bat odd/HANDOFF-ci-2026-09-30.md odd/skill-ci-portable/source-notes.md
curl -s https://apap.romancaba.com/healthz | jq .revision        # producción: ¿sigue en 2d5024a1?
gh api repos/ardelperal/APAP_WEB/commits/2d5024a1dd87b33c5b7f33016d66fd3c1abdf4e6/status --jq '[.statuses[]|select(.context|startswith("release/"))|"\(.context)=\(.state)"]'
```

Luego: preguntar al usuario las decisiones de la sección 3 (**una a la vez**) y continuar con la sección 4.
