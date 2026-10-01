---
name: ci-pattern
description: "Trigger: CI perfecto, patrón CI, gates, preflight, issue-spec, ratchet, evidencia SHA, adoptar CI, aplicar el patrón en un repositorio nuevo, gate de adopción, porting guide, presupuesto de revisión, chain:partial. Distila el patrón de CI del repo (gates deterministas, presupuesto de revisión, evidencia por SHA, cadena de PRs encadenados y protocolo de mejora continua), gobierna su adopción en otro repositorio (GATE DE ADOPCIÓN STOP + porting guide) y enseña a auditarlo."
license: Apache-2.0
metadata:
  author: ardelperal
  version: "0.2"
  last_verified: 2026-10-01
  based_on: "odd/skill-ci-portable/ @ ardelperal/APAP_WEB (épica #935, 2026-09-29/30)"
---

# Patrón de CI — gates deterministas y evidencia por SHA

El patrón combina siete piezas sobre un mismo repositorio:

1. **Gates deterministas** que leen datos estructurados (rama, etiquetas, campos de
   la API, campos del cuerpo del PR), nunca prosa ni gestos.
2. **Presupuesto de revisión** por PR (adiciones + eliminaciones), con excepción
   declarada como campo de datos y PRs encadenados cuando el trabajo no cabe.
3. **Evidencia ligada a una revisión**: cada deploy y cada batería de producción
   registran su veredicto como estado de commit sobre el SHA desplegado.
4. **Política dormida, no retirada**: un gate que pierde su justificación no se
   elimina; se duerme tras un policy file (`enforcement: "dormant"`) y su
   re-activación es un cambio de datos que pasa por review (HR-18).
5. **Protocolo de mejora continua**: toda fricción se registra con evidencia, se
   arregla por el pipeline y se destila en regla; la recurrencia dispara
   automatización.
6. **Release con evidencia**: releases como tags semver anotados, hotfix con
   bump de PATCH y deploy inmediato, y post-mortem blameless tras todo
   incidente de producción (HR-19 a HR-22).
7. **Gobernanza de orquestación**: esperas resueltas por la jerarquía
   determinista (mecanismo > script > IA), un worktree por actor concurrente,
   prescripciones del orquestador verificadas en vivo, toolchains pineadas
   para medir, read-back doble de settings y suite aislada del entorno local
   (HR-23 a HR-28).

El patrón nació de una épica de fricciones reales (19 reglas en el playbook de
origen, cada una pagada con evidencia). La capa de release y post-mortem se
destiló sobre un incidente real de pérdida de datos
(`references/incidents.md`). La capa de gobernanza de orquestación (HR-23 a
HR-28) se destiló del tramo final de la misma épica (2026-10-01): watch de
sesión, colisión de shared-checkout, prescripciones obsoletas, toolchain sin
pinear, settings paywalled y el `.env` local. El GATE DE ADOPCIÓN del §1 se
destiló de la adopción fallida del patrón en Cadete (2026-09-30/10-01): se
aplicó sin el checklist de pre-vuelo y produjo 18 fallos falsos de batería,
3 diagnósticos erróneos (issue #1130 cerrada con corrección), 5 prescripciones
rotas, una premisa de propagación falsa y una colisión de shared-checkout.
El catálogo destilado y el veredicto de gates viven en
`references/`; los parámetros portables, en `assets/parameters.md`. Los scripts de
implementación de referencia están versionados en este repo bajo `scripts/`.

## §1 Activation

### ⛔ GATE DE ADOPCIÓN (STOP)

Antes de aplicar este patrón en un repositorio NUEVO: completar
`references/porting-guide.md` fase por fase: inventario read-only →
auditoría del mecanismo de propagación REAL → aislamiento de entorno →
gobierno viejo y nuevo en el MISMO PR → contratos cableados → primer PR real
como acceptance test. Sin ese checklist completado y verificado: NO se lanza
ningún worker, NO se toca el repo destino, NO se abre PR. Excepción: ninguna.

Anclaje: la adopción en Cadete (2026-09-30/10-01) aplicó el patrón sin el
checklist y produjo 18 fallos falsos de batería, 3 diagnósticos erróneos
(issue #1130 cerrada con corrección), 5 prescripciones rotas, una premisa de
propagación falsa y una colisión de shared-checkout (post-mortem:
`docs/postmortems/2026-09-30-ci-pattern-adoption-cadete.md`). Este gate
existe para que ese modo de fallo sea estructuralmente imposible.

Cargue esta skill cuando:

- Vaya a **adoptar o auditar este patrón de CI en otro repositorio** (inventario
  de gates, medición, instalación, validación real).
- Abra, espere o revise **PRs bajo este patrón**: etiquetas al crear, presupuesto,
  cadena de PRs, cierre de issue, merge con evidencia.
- Deba **clasificar un rojo de CI** o decidir entre push, rerun o dispatch.
- Toque **evidencia de deploy**: estados por SHA, smoke de producción, baterías.
- Vaya a **destilar una fricción nueva** en regla del playbook.
- Deba **delegar u orquestar trabajo concurrente** entre actores (worktrees por
  actor, esperas de CI, verificación en vivo de prescripciones).
- Deba **cortar un release o un hotfix** (tag semver, notas de release,
  playbook de deploy por release).
- Toque un **incidente de producción** (issue, fix, deploy inmediato,
  post-mortem blameless, action items como issues).

No la cargue cuando:

- Escriba tests de aplicación o decida su capa (eso es `apap-testing-strategy`).
- Toque auth, CSRF o secretos de la aplicación (eso es `apap-security`).
- Ejecute la batería e2e de producción (eso es `docs/runbooks/e2e-production.md`;
  esta skill solo gobierna cómo se registra el veredicto).

Fuentes normativas:

- `skills/ci-pattern/references/fricciones.md` — catálogo destilado con antídoto.
- Porting guide de la adopción (`references/porting-guide.md`; canónico en el
  catálogo DysTelefonica/team-skills) — checklist de pre-vuelo fase por fase;
  su cumplimiento es lo que el GATE DE ADOPCIÓN exige.
- `skills/ci-pattern/references/gate-verdicts.md` — veredicto por gate con evidencia.
- `skills/ci-pattern/references/benchmark-gentle-ai.md` — ideas contrastadas de otro CI.
- `skills/ci-pattern/assets/parameters.md` — los parámetros que se extraen por repo.
- `skills/ci-pattern/references/incidents.md` — ejemplo destilado de hotfix y
  post-mortem blameless sobre un incidente real.

## §2 Hard Rules

- **HR-1 — Los gates `MUST` leer datos estructurados** (nombre de rama, etiquetas,
  campos de la API, campos del cuerpo del PR) y ``MUST NOT` deducir nada de prosa,
  gestos ni etiquetas aplicadas tarde. (evidencia: R2; fricciones F-004, B4)
- **HR-2 — Todo gate nuevo que toque producción `MUST` ejecutarse una vez real**
  contra el entorno antes de darlo por terminado; ninguna prueba de escritorio lo
  sustituye. (evidencia: R3; fricción B1)
- **HR-3 — Un gate `MUST` fallar en voz alta cuando no ha medido** y ``MUST NOT`
  imprimir «OK» sin ejecución real detrás. (evidencia: R4; fricción A9)
- **HR-4 — Todo lo que el CI ejecuta `MUST` reproducirse en local con un solo
  comando** (paridad de preflight), y el autor `MUST` ejecutarlo completo antes de
  cada push; la suite de pytest no ejecuta los pasos de lint. (evidencia: R5; F-001, B3)
- **HR-5 — Tras corregir el primer paso rojo de un job, el autor `MUST` reproducir
  también todos los pasos posteriores** antes de empujar: el runner se detiene en
  el primer fallo y los pasos posteriores nunca se han visto verdes. (R12; playbook regla 7)
- **HR-6 — Las etiquetas del PR `MUST` aplicarse en el comando de creación**;
  etiquetar después no reevalúa un gate sin disparador `labeled`. (playbook regla 2)
- **HR-7 — Solo el PR punta de una cadena `MUST` llevar `Closes #<issue>`**; los
  intermedios llevan `Refs` más la etiqueta de cadena, la rama se nombra
  `<tipo>/<N>-<slug>`, el autor `MUST` verificar `closingIssuesReferences` tras
  crear el PR y ``MUST NOT` escribir palabras de cierre en el título. (R2; B11; playbook reglas 3-4)
- **HR-8 — Toda excepción de presupuesto `MUST` declararse como campo de datos**
  en el cuerpo del PR (`size-exception-reason:`, una sola línea, una sola
  aparición, sin marcador de plantilla) y ``MUST NOT` depender de etiquetas. (#1141; R2)
- **HR-9 — Ningún agente ``MUST NOT` mantener procesos vivos sondeando CI**: arme
  auto-merge y siga con otra cosa; para verificar el re-disparo tras actualizar
  la rama use una sonda a los dos minutos, nunca un bucle. (R14; vigías zombis del 2026-09-29)
- **HR-10 — La evidencia de deploy o batería `MUST` registrarse sobre el SHA de la
  revisión desplegada** (estado de commit por SHA) y ``MUST NOT` colgar de una
  variable global ni de la rama por defecto. (R6; #1082)
- **HR-11 — Toda fricción `MUST` registrarse con evidencia (PR, issue, run o
  `fichero:línea`)**, arreglarse por el pipeline normal y destilarse en regla con
  su ternario completo; la segunda ocurrencia `MUST` disparar automatización, no
  otro arreglo manual. (R14; protocolo de mejora continua)
- **HR-12 — Los registros acumulativos de varias sesiones `MUST` guardarse sin
  clave de upsert** (una observación nueva por entrada): el upsert sustituye el
  contenido y destruye el histórico. (R9; pérdida de #4368)
- **HR-13 — Los mensajes de un gate `MUST` describir la causa real** y, cuando el
  fallo depende de un dato que el autor no puede corregir, `MUST` decirlo y ofrecer
  una vía manual auditable. (R10; B4, B11)
- **HR-14 — Los commits `MUST` ser conventional y sin atribución de IA** (sin
  `Co-Authored-By` ni equivalentes). (COL3; regla del repo)
- **HR-15 — Los ratchets `MUST` ser shrink-only** (rechazan lo nuevo, aceptan el
  inventario actual, regeneran baseline con un comando); en cadenas, la baseline
  sube en el slice aditivo y baja en el que consume, y el fixture que un slice
  necesita `MUST` viajar en ese slice. (T2; playbook regla 12)
- **HR-16 — Las huellas de secretos y las baselines de gates `MUST` anclarse a
  identificadores estables** (SHA de contenido o ruta), nunca a números de línea
  mutables que rompen el gate en el primer reordenado. (seguimiento #1112)
- **HR-17 — La actualización de rama `MUST` seguir la secuencia determinista**
  (PUT `update-branch`, verificar run fresco sobre el nuevo SHA a los dos
  minutos, fallback `workflow_dispatch` sobre el SHA), y tras cualquier PATCH de
  settings `MUST` leerse de vuelta antes de concluir. (playbook reglas 11 y 18)
- **HR-18 — Un gate que pierde su justificación se duerme, no se retira**: se
  deja tras un policy file con el motor construido y probado
  (`enforcement: "dormant"`, snapshot de activación inmutable) y la
  re-activación es un cambio de datos del policy file que pasa por review; el
  candado construido `MUST NOT` borrarse. (R15; benchmark T1;
  `references/gate-verdicts.md`)
- **HR-19 — Todo release `MUST` ser un tag semver anotado** (`vMAJOR.MINOR.PATCH`)
  con GitHub Release asociada y marcada `Latest`; los prereleases
  (`vX.Y.Z-rc.N`) `MUST` quedar excluidos de la estable (`v*-*`), y las notas de
  release `MUST` ser concisas (qué cambió + enlace al issue o post-mortem), sin
  enterrar nunca la causa raíz del incidente. (incidente de pérdida de datos;
  `references/incidents.md`)
- **HR-20 — Todo hotfix `MUST` aterrizar primero en main** y salir como bump de
  PATCH con deploy inmediato tras el merge; el fix `MUST NOT` vivir solo en una
  rama paralela ni esperar al próximo release regular. (incidente de pérdida de
  datos; `references/incidents.md`)
- **HR-21 — Todo incidente de producción `MUST` cerrar con post-mortem
  blameless** en el doc dedicado del consumer (`docs/postmortems/<date>-<slug>.md`;
  secciones: Timeline UTC / Impact / Root cause / What worked / What failed),
  con causas de sistema y nunca de personas, y cada action item `MUST`
  abrirse como issue de GitHub con owner. (canon del sector, precedente GitLab
  2017; `references/incidents.md`)
- **HR-22 — Cada deploy `MUST` llevar su playbook por release**
  (`RELEASE-<TAG>.md`: build/push si aplica, apply, rollout, verificación y
  rollback), y la imagen de rollback `MUST` capturarse antes de desplegar.
  (incidente de pérdida de datos; `references/incidents.md`)
- **HR-23 — Toda espera `MUST` diseñarse por la jerarquía determinista
  mecanismo > script > IA**: el auto-merge armado espera el CI,
  `allow_update_branch` actualiza la rama, los required checks bloquean y los
  workflows programados recuerdan sin sesión viva; donde no hay mecanismo, un
  script versionado con deadline y fallback explícitos; la IA `MUST` reservarse
  para juicios (disposiciones, conflictos de contenido, gobierno) y `MUST NOT`
  actuar de vigía por defecto ni mantener procesos vivos de sondeo. (épica
  #935; playbook regla 19; vigías zombis de la sesión cerrada, 2026-09-29)
- **HR-24 — Todo actor concurrente `MUST` trabajar en su propio worktree**: dos
  workers `MUST NOT` compartir un working tree ni una rama; la tarea delegada
  lleva worktree y rama propios desde su encargo, y el trabajo abandonado se
  reclama desde el estado real (git, PR, issue), no desde la memoria de la
  sesión. (colisión de shared-checkout, 2026-10-01: un worker commiteó sobre
  la rama del otro a mitad de vuelo)
- **HR-25 — Las prescripciones del orquestador `MUST` verificarse en vivo antes
  de ejecutarse**: SHA, conteos de pasos, rutas de tests y superficies
  editables son hipótesis hasta que el worker las confirma contra el
  repositorio real (`rev-parse`, preflight, inventario de ficheros) y
  reutiliza lo que exista; `MUST NOT` ejecutarse un snapshot obsoleto ni
  duplicar trabajo ya verificable. (vivid cuatro veces en el tramo final de la
  épica: preflight con 19 vs 20 pasos, sección §15.8 inexistente, SHA de
  slice-2 distinto, ruta de tests inexistente)
- **HR-26 — Todo gate que compara números `MUST` medir con la toolchain
  versionada que lo juzga en CI** (pin de versiones en la stack de medición o
  re-medición por la toolchain del juez) y `MUST NOT` comparar una medición
  local con un baseline producido por otra versión: cobertura y baselines no
  son comparables entre toolchains. (baseline local 11503 vs runner 11559 por
  xdebug sin pinear)
- **HR-27 — Tras cualquier PATCH de settings el resultado `MUST` confirmarse
  con read-back doble con delay** y verificación del plan de la organización
  antes de concluir: el API puede responder 200 OK y descartar en silencio
  campos paywalled (`allow_auto_merge` en org free plan); un valor obsoleto en
  la primera lectura no autoriza a repetir el PATCH en bucle. (#1150;
  completa el read-back de HR-17)
- **HR-28 — El entorno de la suite `MUST` aislar del `.env` local del
  desarrollador**: un `.env` gitignored en la raíz filtra sus variables
  (p. ej. `APAP_*`) a `Settings` y rompe tests solo en local; si el
  aislamiento no existe todavía, los rojos ambientales `MUST` documentarse
  como fallo de entorno, nunca como defecto de código. (5 rojos ambientales
  locales por el `.env` de la raíz, 2026-10-01)

## §3 Decision Gates

| Condición | Acción |
|---|---|
| Va a adoptar el patrón en un repo nuevo | ⛔ GATE DE ADOPCIÓN del §1: complete el porting guide fase por fase y verifique cada gate de salida antes de lanzar workers, tocar el repo destino o abrir PR. Sin checklist: nada. |
| El diff supera el presupuesto de líneas | Parta por unidad de trabajo; después encadene PRs; `size-exception-reason:` en el cuerpo es el último recurso. |
| Va a abrir un PR intermedio de una cadena (`chain:partial`) | Palabras de cierre (`Closes`, `Fixes`, `Resolves`) NUNCA en el título ni en el cuerpo del intermedio: solo el PR punta cierra la issue. Intermedios con `Refs #<N>` + etiqueta de cadena; verifique `closingIssuesReferences` tras crear (HR-7). |
| GitHub no registró `closingIssuesReferences` tras crear el PR | Etiqueta de cadena más excepción declarada en el cuerpo; cierre la issue a mano tras el merge con comentario que lo documente. |
| El rojo exige un push de corrección | Empuje y deje que la CI se dispare sola; `rerun --failed` solo para transitorios, `workflow_dispatch` solo cuando el workflow cambió. |
| Falla un paso del job de lint | Ejecute el preflight completo antes de empujar, no solo el paso roto (HR-5). |
| Aparece una fricción que ninguna regla cubre | Aplique el protocolo de HR-11: registrar con evidencia, arreglar por el pipeline, destilar en regla. |
| Un gate acumula baseline creciente sin defecto real cazado | Duerma el gate tras su policy file (`enforcement: "dormant"`), no lo retire; la re-activación es un cambio de datos con review (HR-18). |
| Va a dejar un gate como informativo sin policy file | No lo haga: informativo sin policy pierde el candado construido; muévalo a dormant (R15). |
| Va a guardar un registro acumulativo entre sesiones | Sin clave de upsert: una observación nueva por entrada (HR-12). |
| Debe reiniciar la aplicación de producción | Use el procedimiento del runbook de deploy; el reinicio directo redespliega el HEAD de la rama por defecto sin gate de evidencia. |
| Hereda un proceso vivo (vigía) de otra sesión | Verifique qué hace leyendo su script; cumplido su propósito, termínelo; inesperado, deténgase y reporte su contenido. |
| Se declara un incidente de producción | Hotfix: issue `type:bug` → fix en main → deploy inmediato → release PATCH → post-mortem blameless con action items como issues (HR-20, HR-21). |
| Va a esperar un resultado de CI o de otro actor | Aplique la jerarquía de HR-23: auto-merge armado, `allow_update_branch`, required checks o workflow programado; solo si no hay mecanismo, un script versionado con deadline y fallback; nunca un vigía IA. |
| Va a delegar una tarea que correrá en paralelo con otra | Asígnele worktree y rama propios en el encargo (HR-24); nunca dos actores sobre el mismo working tree. |
| Recibe SHA, conteos, rutas o superficies prescritos por el orquestador | Verifíquelos en vivo antes de ejecutar y reutilice lo que exista (HR-25). |
| Va a comparar una medición local contra un baseline o gate de CI | Mida con la toolchain pineada del juez o re-mida con ella; sin pin no hay comparación válida (HR-26). |
| Un PATCH de settings respondió 200 pero el read-back no muestra el valor | Lea de vuelta dos veces con delay y verifique el plan de la org: el campo puede ser paywalled y descartarse en silencio (HR-27). |
| Tests rojos solo en local y verdes en CI | Sospeche del `.env` local filtrando variables a `Settings`; aísle el entorno de tests o registre el rojo como ambiental (HR-28). |
| Va a cortar un release | Tag semver anotado + GitHub Release `Latest` + notas concisas + playbook `RELEASE-<TAG>.md` con imagen de rollback capturada antes de desplegar (HR-19, HR-22). |

## §4 Execution Steps

### Adopción del patrón en un repo

1. **Audite.** Inventaríe cada gate del CI con su veredicto (se queda, se
   refuerza, se duerme, se retira) y la evidencia que lo sostiene. Contraste
   cada afirmación de la documentación contra los workflows reales; corrija los
   desvíos en la misma sesión. Modelo de salida: `references/gate-verdicts.md`.
2. **Mida.** Presupuesto real por PR, duración de la CI, falsos verdes conocidos,
   pasos de CI que nadie ejecuta en local. Sin cifra no hay decisión de gates.
3. **Instale.** Extraiga los parámetros del repo (`assets/parameters.md`,
   incluido el policy file de gates dormibles), adapte los scripts de
   referencia (`scripts/` de este repo), configure la
   protección de rama (checks requeridos, `strict`, sin force-push) y el
   preflight canónico que lee los pasos del job de lint del propio workflow.
4. **Valide en real.** Ejecute de verdad cada gate que toque producción (HR-2) y
   complete una cadena de PRs encadenados de extremo a extremo con CI en cada
   tramo antes de declarar el patrón adoptado.

### Operación por unidad de trabajo

1. Issue con el contrato canónico completo (secciones exactas que el gate lee) y
   etiqueta de aprobación aplicada **al crearla**: el gate lee la issue remota,
   no su copia local.
2. Worktree dedicado y rama `<tipo>/<N>-<slug>`; el gate deriva la issue del
   nombre de rama. Cuando la tarea corre en paralelo con otro actor, el
   worktree es propio y exclusivo (HR-24).
3. Preflight completo en local antes de cada push (HR-4, HR-5).
4. PR con todas las etiquetas en el comando de creación; `Closes #<issue>` solo
   en la punta de la cadena (HR-6, HR-7).
5. Verifique `closingIssuesReferences` tras crear el PR; si no aparece, declare
   la excepción en el cuerpo y cierre a mano tras el merge (HR-7).
6. CI en vuelta: clasifique rojos solo tras identificar el paso que falla vía
   API; empuje los fixes; rerun solo para transitorios (HR-9, gates del §3).
7. Merge con auto-merge y commit de fusión, sin borrar la rama remota; con
   `strict`, actualice la rama con la secuencia determinista de HR-17.
8. Deploy: registre el veredicto de la batería sobre el SHA de `/healthz` de la
   revisión desplegada (HR-10); apague cualquier flag de prueba al terminar,
   también si la batería falla.

### Release, hotfix y post-mortem

**Corte de release (semver, estilo gentle-ai).**

1. Confirme que main está verde contra la base actual y sin rebase pendiente;
   el verde contra una base obsoleta no autoriza el release.
2. Cree el tag anotado `vMAJOR.MINOR.PATCH` y la GitHub Release asociada
   marcada `Latest`; los prereleases usan `vX.Y.Z-rc.N` y quedan excluidos de
   la estable con el patrón `v*-*` (HR-19).
3. Escriba notas concisas: qué cambió y enlace al issue o post-mortem; la
   causa raíz completa vive en su doc dedicado, nunca dentro de las notas (HR-21).
4. Ejecute el playbook de deploy: `RELEASE-<TAG>.md` con build/push si aplica,
   apply, rollout, verificación y rollback; capture la imagen de rollback
   antes de desplegar (HR-22).

**Hotfix (incidente de producción).**

1. Abra la issue canónica (`type:bug`) con la evidencia del incidente.
2. Aterrice el fix en main por el pipeline normal (issue, worktree, PR, CI,
   merge); sin rutas paralelas ni fixes que vivan solo en una rama (HR-20).
3. Despliegue inmediatamente tras el merge y registre el veredicto sobre el
   SHA desplegado (HR-10).
4. Corte el release PATCH con notas que enlacen al issue (HR-19).
5. Escriba el post-mortem blameless en `docs/postmortems/<date>-<slug>.md` con
   secciones Timeline (UTC) / Impact / Root cause / What worked / What failed;
   causas de sistema, nunca personas (HR-21).
6. Abra cada action item como issue de GitHub con owner asignado y verifique
   que no queden solo en el doc (HR-21).

### Destilación de fricciones (protocolo de mejora continua)

1. Detecte con evidencia: sin incidente citado no es fricción, es opinión.
2. Regístrela inmediatamente en el tracker o el catálogo del proyecto,
   clasificada como bloqueante o de seguimiento.
3. Arregle por el pipeline normal (issue, worktree, PR, CI, merge), nunca
   mezclada con otro cambio.
4. Destile en regla con su ternario completo: regla, rojo que la creó,
   procedimiento correcto.
5. Vigile la recurrencia: la segunda ocurrencia se automatiza (gate, workflow
   programado o cambio de diseño), no se arregla a mano otra vez.
6. Audite periódicamente: una pasada que compare cada afirmación de la doc
   contra la realidad de los workflows y declare qué claims quedaron verificados.

## §5 Output Contract

| Key | Type | Description |
|---|---|---|
| `status` | `"success" \| "blocked" \| "failed"` | Resultado de la adopción, operación o auditoría. |
| `pattern_params` | object | Los parámetros del repo resueltos según `assets/parameters.md`. |
| `gate_verdicts` | array | `{gate, verdict, evidence}` por cada gate auditado. |
| `frictions_registered` | string[] | Fricciones registradas con su evidencia (issue, PR, run). |
| `frictions_distilled` | string[] | Reglas destiladas con su ternario completo. |
| `evidence_shas` | array | `{sha, context, state}`: estados de commit registrados por revisión. |
| `preflight_command` | string | Comando canónico ejecutado antes del último push. |
| `hr_traceability` | array | Pares `{rule, evidence}` que trazan cada HR-N aplicada a su fricción de origen. |
| `risks` | string[] | Riesgos abiertos (gates sin medir, contradicciones doc-workflow pendientes). |
| `next_recommended` | `"fix_violations" \| "register_in_catalog" \| "none"` | Siguiente acción. |

## §6 Anti-patterns

| Síntoma | Fix |
|---|---|
| Etiquetas aplicadas después de crear el PR y el gate queda rojo | Etiquete en `gh pr create --label`; si ya creó el PR, use la API REST y espere rerun o push. |
| `Closes` en el título o en un tramo intermedio cierra la issue antes de tiempo | Palabras de cierre solo en el cuerpo del PR punta; intermedios con `Refs` y etiqueta de cadena (#1138). |
| Verde en local y rojo en CI por un paso de lint que pytest no ejecuta | Preflight canónico que reproduce el job completo; ejecútelo antes de cada push. |
| Gate que imprime «`OK (0 hallazgos)`» sin haber corrido el herramienta | Fail-loud: el gate falla si el herramienta no está instalado o no midió (HR-3). |
| Un rojo de raíz enmascarado como N fallos en el agregador | El agregador separa causa raíz de skips en cascada y agrupa las consecuencias. |
| Bucle de sondeo de CI o vigía que sobrevive a la sesión | Auto-merge más una sonda única a los dos minutos; sin procesos vivos (HR-9). |
| Variable global que aprueba o bloquea deploys para siempre | Estado de commit por SHA; la evidencia viaja con la revisión (HR-10). |
| Fix de fricción aplicado a mano sin registrar | El rojo vuelve con la próxima sesión; registre con evidencia y destile en regla. |
| Registro acumulativo guardado con upsert por clave | Una observación nueva por entrada; el upsert sustituye el contenido (HR-12). |
| Rerun de un run cuyo SHA ya está corregido en local | Empuje; el rerun reproduce el SHA original y quema un ciclo de espera. |
| Batería ejecutada con los tests de la rama por defecto contra un deploy anterior | Worktree en la revisión desplegada; los fallos por desfase se clasifican, no se registran como fallo del deploy. |
| Gate retirado por perder su justificación | Duerma el gate tras un policy file con el motor probado; retirarlo destruye el candado y la re-activación futura exige reconstruirlo (HR-18). |
| Baseline de un ratchet editada a mano en cada reducción | Comando de regeneración de baseline; el gate solo rechaza entradas nuevas (HR-15). |
| Causa raíz enterrada en las notas de release o en el cuerpo del PR | Notas concisas con enlace; el post-mortem vive en su doc dedicado (HR-19, HR-21). |
| Fix de incidente viviendo solo en una rama paralela esperando el release regular | Hotfix aterriza en main, deploy inmediato y release PATCH (HR-20). |
| Post-mortem que nombra personas como causa | Blameless: causas de sistema; falló el proceso, no la persona (HR-21). |
| Rojo de CI diagnosticado grepeando logs del runner en vez de pedir la evidencia por paso | `gh api repos/<org>/<repo>/actions/jobs/<id>` separa el paso que falla; el log del runner equivocado (hosted frente a self-hosted) fabricó el diagnóstico «Docker daemon» ×3 en Cadete (C2 del porting guide). |
| Baseline o conteo medido con una toolchain distinta de la que juzga en CI | Pin de versiones en la stack de medición o re-medición por la toolchain del juez; cobertura local 11503 frente a runner 11559 por xdebug sin pinear (C7 del porting guide). |
| Prescripción del orquestador ejecutada de memoria, sin verificarla en vivo | SHA, conteos, rutas y superficies son hipótesis: verifíquelos contra el repo real y reutilice lo existente; las prescripciones rotas de Cadete (formato de issue, rama ilegal, ruta de tests inexistente) lo pagaron (C3 del porting guide). |
| Premisa de propagación o de gobernanza del destino tomada de su documentación | Audite el mecanismo real en vivo (hooks, reconciliador, markers, manifest) antes de depender de él; la premisa falsa dejó espejos stale medio tramo (C4 del porting guide). |
| Adopción del patrón lanzada sin el checklist de pre-vuelo | GATE DE ADOPCIÓN del §1: sin porting guide completado no hay workers, ni toques al repo destino, ni PR (anclaje: Cadete, 2026-09-30/10-01). |
| Deploy sin imagen de rollback capturada | Capture la imagen de rollback en el playbook antes de aplicar (HR-22). |
| Bucle `--watch`, watcher de sesión o vigía IA esperando CI | Mecanismo primero: auto-merge armado más `allow_update_branch`; donde no hay mecanismo, script versionado con deadline y fallback (HR-23). |
| Dos workers sobre el mismo working tree | Un worktree por actor concurrente; el síntoma es el commit sobre la rama ajena a mitad de vuelo (HR-24). |
| Prescripción del orquestador ejecutada sin verificarla | El snapshot puede ser stale: verifique SHA, conteos y rutas en vivo y reutilice lo existente (HR-25). |
| Medición local comparada contra el juez de CI sin toolchain pineada | Pin de versiones en la stack de medición o re-medición por la toolchain del juez (HR-26). |
| PATCH de settings dado por bueno por su 200 OK | Read-back doble con delay y verificación del plan: paywalled se descarta sin error (HR-27). |
| Suite que solo pasa con el `.env` del desarrollador delante | Aísle el entorno de tests del `.env` local y documente los rojos ambientales conocidos (HR-28). |

## §7 Companion skills

| Skill | Cargar junto cuando |
|---|---|
| `branch-pr` | Vaya a abrir o fusionar el PR de una unidad de trabajo bajo este patrón. |
| `chained-pr` | El diff supera el presupuesto y va a encadenar PRs. |
| `work-unit-commits` | Vaya a planificar los commits del PR por unidad de trabajo. |
| `repository-delivery-governance` | Vaya a auditar o cambiar la protección de rama, checks requeridos o política de merge. |
| `documentation-alan-style` | Vaya a actualizar la documentación del CI para que refleje el código (regla P3). |

## §8 References

- `assets/parameters.md` — los parámetros que se extraen por repo, con los
  valores de este repo como ejemplo, el policy file de gates dormibles (HR-18)
  y los scripts de referencia indicados.
- `references/fricciones.md` — catálogo destilado: fricción, antídoto y evidencia.
- `references/porting-guide.md` — checklist de pre-vuelo de la adopción fase
  por fase; cada fase declara hard gates y cita el incidente real de Cadete
  (2026-09-30/10-01) que lo justifica. Exigido por el GATE DE ADOPCIÓN del §1.
- `references/gate-verdicts.md` — veredicto de cada gate del inventario con su base.
- `references/benchmark-gentle-ai.md` — ideas transferibles y rechazadas de otro CI.
- `references/incidents.md` — ejemplo destilado de hotfix, post-mortem y
  release sobre un incidente real de pérdida de datos.
- Implementación de referencia versionada en este repo: `scripts/preflight.py`,
  `scripts/check_pr_size.py`, `scripts/check_issue_specs.py`,
  `scripts/check_required_jobs.py`, `scripts/check_release_evidence.py`,
  `scripts/check_release_e2e_required.py`, `scripts/production_smoke.py` y
  `.github/release-e2e-paths.txt`.
