---
name: ci-pattern
description: "Trigger: CI perfecto, patrón CI, gates, preflight, issue-spec, ratchet, evidencia SHA, adoptar CI, aplicar el patrón en un repositorio nuevo, gate de adopción, porting guide, presupuesto de revisión, chain:partial. Distila el patrón de CI del repo (gates deterministas, presupuesto de revisión, evidencia por SHA, cadena de PRs encadenados y protocolo de mejora continua), gobierna su adopción en otro repositorio (GATE DE ADOPCIÓN STOP + references/porting-guide.md) y enseña a auditarlo."
license: Apache-2.0
metadata:
  author: ardelperal
  version: "0.4"
  last_verified: 2026-10-02
  based_on: "auditoría issue→merge de ardelperal/APAP_WEB (épica ardelperal/APAP_WEB#935, 2026-09-29/30)"
  scope: ['universal', 'ops']
  auto_invoke: ['adopt the CI pattern in another repo', 'apply the CI pattern in a new repo', 'audit a CI pipeline', 'deterministic quality gates', 'PR review budget', 'SHA evidence', 'CI adoption gate', 'porting guide']
  tiers: ['universal', 'ops']
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
destiló de la adopción fallida en Cadete (2026-09-30/10-01): se aplicó el
patrón SIN el checklist de pre-vuelo y produjo 18 fallos falsos de batería,
3 diagnósticos erróneos (issue ardelperal/APAP_WEB#1130 cerrada con
corrección), 5 prescripciones rotas, una premisa de propagación falsa y una
colisión de shared-checkout; el checklist fase por fase vive en
`references/porting-guide.md`. El catálogo destilado y el
veredicto de gates viven en `references/`; los parámetros portables, en
`assets/parameters.md`. La
ubicación actual de los scripts de implementación de referencia se declara en
`assets/parameters.md`.

**Frontera de alcance.** Este patrón cubre el gobierno de CI del repositorio:
gates deterministas, presupuesto de revisión, evidencia por SHA, cadena de
PRs, release y post-mortem. La autoridad de review —desarrollo dirigido por
recibos (RDD): linajes, recibos, rondas de jueces, sobres de consentimiento,
presupuestos de corrección y acknowledgement— es capacidad del harness
`gentle-ai`; este patrón la asume instalada y no la re-implementa ni la
documenta como propia. La memoria persistente es capacidad de `engram`. Son
los únicos dos harnesses externos que el patrón presupone.

## §1 Activation

### ⛔ GATE DE ADOPCIÓN (STOP)

Antes de aplicar este patrón en un repositorio NUEVO: completar
`references/porting-guide.md` fase por fase (inventario read-only → auditoría
del mecanismo de propagación REAL → aislamiento de entorno → gobierno viejo y
nuevo en el MISMO PR → contratos cableados → primer PR real como acceptance
test). Sin ese checklist completado y verificado: NO se lanza ningún worker,
NO se toca el repo destino, NO se abre PR. Excepción: ninguna.

Anclaje: la adopción en Cadete (2026-09-30/10-01) aplicó el patrón sin el
checklist y produjo 18 fallos falsos de batería, 3 diagnósticos erróneos
(issue ardelperal/APAP_WEB#1130 cerrada con corrección), 5 prescripciones
rotas, una premisa de propagación falsa y una colisión de shared-checkout
(post-mortem: `docs/postmortems/2026-09-30-ci-pattern-adoption-cadete.md` en
`ardelperal/APAP_WEB`). Este gate existe para que ese modo de fallo sea
estructuralmente imposible.

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

- Escriba tests de aplicación o decida su capa (eso es la skill local de testing
  del consumer, parámetro 12).
- Toque auth, CSRF o secretos de la aplicación (eso es la skill local de
  seguridad del consumer, parámetro 12).
- Ejecute la batería e2e de producción (eso es el runbook e2e del consumer,
  parámetro 11; esta skill solo gobierna cómo se registra el veredicto).

Fuentes normativas:

- `references/fricciones.md` — catálogo destilado con antídoto.
- `references/porting-guide.md` — checklist de pre-vuelo de la adopción, fase
  por fase; su cumplimiento es lo que el GATE DE ADOPCIÓN exige.
- `references/gate-verdicts.md` — veredicto por gate con evidencia.
- `references/benchmark-gentle-ai.md` — ideas contrastadas de otro CI.
- `assets/parameters.md` — los parámetros que se extraen por repo.
- `references/incidents.md` — ejemplo destilado de hotfix y
  post-mortem blameless sobre un incidente real.

## Uso desde una IA — CLI `assets/bin/ci-pattern`

El adoptador/verificador determinista del patrón vive en `assets/bin/ci-pattern`
(relativo a la raíz de la skill; se resuelve igual en el catálogo canónico
`DysTelefonica/team-skills` y en cualquier mirror). Su contrato normativo es
`references/cli-spec.md`; su salida está diseñada para ser leída por un agente
(terse, estructurada, accionable). Frases de disparo del usuario: «actualizá el
sistema de gobernanza», «adoptá el patrón en este repo», «verificá el
cumplimiento».

Flujo de 5 comandos (hoy entregados: 1, 2 y 5; `adopt`/`update` son la wave
siguiente, con las plantillas aún por extraer del origen):

```bash
# 1. Estado del repo destino: ¿hay manifiesto? ¿está limpio?
ci-pattern status <repo>

# 2. Validar los parámetros ANTES de escribir nada (cierra el hueco G3)
ci-pattern params validate ci-pattern.yaml

# 3. (wave siguiente) Plan de adopción sin escritura
ci-pattern adopt <repo> --dry-run

# 4. (wave siguiente) Adopción real: plantillas + manifiesto + PR
ci-pattern adopt <repo>

# 5. Verificación de cumplimiento tras cualquier cambio
ci-pattern verify <repo> --json
```

Códigos de salida: 0 limpio · 1 hallazgos · 2 uso · 3 recurso ausente · 4 wave
futura. La CLI nunca hace merge, push, ni toca producción, ni borra ficheros,
ni sobrescribe un fichero modificado localmente sin reportarlo como hallazgo;
los valores de los parámetros, los conflictos de contenido y la disposición de
los veredictos siguen siendo juicio humano/IA (§8 de `references/cli-spec.md`).

## §2 Hard Rules

- **HR-1 — Los gates `MUST` leer datos estructurados** (nombre de rama, etiquetas,
  campos de la API, campos del cuerpo del PR) y `MUST NOT` deducir nada de prosa,
  gestos ni etiquetas aplicadas tarde. (evidencia: R2; fricciones F-004, B4)
- **HR-2 — Todo gate nuevo que toque producción `MUST` ejecutarse una vez real**
  contra el entorno antes de darlo por terminado; ninguna prueba de escritorio lo
  sustituye. (evidencia: R3; fricción B1)
- **HR-3 — Un gate `MUST` fallar en voz alta cuando no ha medido** y `MUST NOT`
  imprimir «OK» sin ejecución real detrás. (evidencia: R4; fricción A9)
- **HR-4 — Todo lo que el CI ejecuta `MUST` reproducirse en local con un solo
  comando** (paridad de preflight), y el autor `MUST` ejecutarlo completo antes de
  cada push; la suite de tests local del consumer (parámetro 13) no ejecuta los
  pasos de lint. (evidencia: R5; F-001, B3)
- **HR-5 — Tras corregir el primer paso rojo de un job, el autor `MUST` reproducir
  también todos los pasos posteriores** antes de empujar: el runner se detiene en
  el primer fallo y los pasos posteriores nunca se han visto verdes. (R12; playbook regla 7)
- **HR-6 — Las etiquetas del PR `MUST` aplicarse en el comando de creación**
  (higiene del autor): aplicadas tarde, alguien tiene que reejecutar o empujar
  para que el gate lea el dato nuevo, y esa higiene `MUST NOT` tratarse como
  evaluación del gate — lo que se evaluó fue el PR sin las etiquetas (HR-31).
  (playbook regla 2)
- **HR-7 — Solo el PR punta de una cadena `MUST` llevar `Closes #<issue>`**; los
  intermedios llevan `Refs` más la etiqueta de cadena, la rama se nombra
  `<tipo>/<N>-<slug>`, el autor `MUST` verificar `closingIssuesReferences` tras
  crear el PR y `MUST NOT` escribir palabras de cierre en el título. (R2; B11; playbook reglas 3-4)
- **HR-8 — Toda excepción de presupuesto `MUST` declararse como campo de datos**
  en el cuerpo del PR (`size-exception-reason:`, una sola línea, una sola
  aparición, sin marcador de plantilla). El campo del cuerpo es el invariante:
  sin él, la excepción no existe. Una etiqueta adicional como `size:exception`
  es mecanismo opcional del consumer (parámetro 3) que `MUST NOT` sustituir al
  campo. (ardelperal/APAP_WEB#1141; R2)
- **HR-9 — Ningún agente `MUST NOT` mantener procesos vivos sondeando CI**: arme
  auto-merge y siga con otra cosa; para verificar el re-disparo tras actualizar
  la rama use una sonda a los dos minutos, nunca un bucle. (R14; vigías zombis del 2026-09-29)
- **HR-10 — La evidencia de deploy o batería `MUST` registrarse sobre el SHA de la
  revisión desplegada** (estado de commit por SHA) y `MUST NOT` colgar de una
  variable global ni de la rama por defecto. (R6; ardelperal/APAP_WEB#1082)
- **HR-11 — Toda fricción `MUST` registrarse con evidencia (PR, issue, run o
  `fichero:línea`)**, arreglarse por el pipeline normal y destilarse en regla con
  su ternario completo; la segunda ocurrencia `MUST` disparar automatización, no
  otro arreglo manual. (R14; protocolo de mejora continua)
- **HR-12 — Los registros acumulativos de varias sesiones `MUST` guardarse sin
  clave de upsert** (una observación nueva por entrada): el upsert sustituye el
  contenido y destruye el histórico. (R9; pérdida del registro acumulativo de
  Engram por upsert; `references/fricciones.md`)
- **HR-13 — Los mensajes de un gate `MUST` describir la causa real** y, cuando el
  fallo depende de un dato que el autor no puede corregir, `MUST` decirlo y ofrecer
  una vía manual auditable. (R10; B4, B11)
- **HR-14 — Los commits `MUST` ser conventional y sin atribución de IA** (sin
  `Co-Authored-By` ni equivalentes). (COL3; regla del repo)
- **HR-15 — Los ratchets `MUST` ser shrink-only** (rechazan lo nuevo, aceptan el
  inventario actual, regeneran baseline con un comando). Toda entrada de gate
  que un PR puede editar (baseline, policy file, allowlist) `MUST` compararse
  contra la copia de la rama base, y toda relajación — una cifra que sube, una
  entrada añadida, `enforcing` → `dormant` — `MUST` llevar un campo de datos
  explícito con motivo y referencia, validado por el propio gate, y `MUST NOT`
  aceptarse sin él; en cadenas, la baseline sube en el slice aditivo y baja en
  el que consume, el slice aditivo lleva el mismo campo de relajación, y el
  fixture que un slice necesita `MUST` viajar en ese slice. (T2; playbook
  regla 12; team-skills#135; fricciones D3)
- **HR-16 — Las huellas de secretos y las baselines de gates `MUST` anclarse a
  identificadores estables** (SHA de contenido o ruta), nunca a números de línea
  mutables que rompen el gate en el primer reordenado. (seguimiento
  ardelperal/APAP_WEB#1112)
- **HR-17 — La actualización de rama `MUST` seguir la secuencia determinista**
  (PUT `update-branch`, verificar run fresco sobre el nuevo SHA a los dos
  minutos, fallback `workflow_dispatch` sobre el SHA), y tras cualquier PATCH de
  settings `MUST` leerse de vuelta antes de concluir; el fallback manual `MUST`
  resolver el PR a partir del SHA y evaluarlo completo, o `MUST NOT` publicar
  nombres de checks requeridos (HR-30). (playbook reglas 11 y 18)
- **HR-18 — Un gate que pierde su justificación se duerme, no se retira**: se
  deja tras un policy file con el motor construido y probado
  (`enforcement: "dormant"`, snapshot de activación inmutable) y la
  re-activación es un cambio de datos del policy file que pasa por review; el
  candado construido `MUST NOT` borrarse. `dormant` `MUST` suprimir únicamente
  el código de salida que el gate documenta como «hallazgos»: cualquier otro
  código (fallo de ejecución, herramienta ausente, gate no ejecutado) `MUST`
  propagarse — un gate dormido que revienta es un rojo, no un skip (HR-3).
  Re-armar un gate a `enforcing` `MUST` dejar la suite en verde: los tests del
  policy file `MUST` cubrir ambos estados de `enforcement` con fixtures y
  `MUST NOT` fijar el valor vigente. (R15; benchmark T1;
  `references/gate-verdicts.md`; team-skills#135; fricciones D4, D5)
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
  blameless** en la ruta de post-mortems del consumer (parámetro 9;
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
- **HR-29 — El agregador de jobs requeridos `MUST` verificar la paridad de los
  tres conjuntos que lo sostienen**: `jobs(workflow) − {agregador}`, el `needs`
  del agregador y el conjunto conocido por el evaluador `MUST` ser iguales; una
  clave de `needs` que el evaluador no conozca `MUST` contarse como violación y
  `MUST NOT` ignorarse, y un job excluido a propósito del agregado se declara
  como dato con su motivo, nunca por omisión. Al añadir, renombrar o eliminar un
  job, los tres conjuntos se actualizan en el mismo PR: un job cableado en
  `needs` y ausente del conjunto conocido, o añadido al workflow sin cablear,
  queda fuera de todo veredicto y el agregador sale limpio con un fallo real
  dentro. (team-skills#133; derivada de la lectura del código del agregador de
  origen, 2026-10-01; fricciones D1)
- **HR-30 — Un nombre de check requerido `MUST` publicarse solo desde un evento
  que evalúa el PR**; en cualquier otro evento (`push`, `workflow_dispatch`,
  `schedule`) el job `MUST` publicar bajo otro nombre de contexto o fallar, y
  `MUST NOT` emitir éxito sin haber evaluado el PR: un verde requerido que no
  evaluó es un falso verde indistinguible del bueno y anula la protección de
  rama. (team-skills#134; derivada de la lectura del código de origen,
  2026-10-01; fricciones D2)
- **HR-31 — Un gate que lee datos mutables del PR o de la issue enlazada
  (cuerpo del PR, etiquetas, estado y etiquetas de la issue) `MUST` reejecutarse
  cuando esos datos cambian**, o su verde `MUST` invalidarse reevaluando el gate
  en el momento del merge. Límite honesto: un cambio en la issue enlazada no
  dispara eventos del PR en el host, así que para ese dato la reevaluación en el
  merge no es opcional — la regla `MUST NOT` prometer un disparador que no
  existe. Un verde que sobrevive a la edición del cuerpo o de una etiqueta no
  certifica nada. (team-skills#134; derivada de la lectura del código de origen,
  2026-10-01)
- **HR-32 — Todo control —gate, auditoría, workflow programado o control
  compensatorio— `MUST` tener un test de comportamiento que ejecute su lógica
  contra un fixture que viola la regla y observe el veredicto de fallo**; un
  test que solo comprueba subcadenas del fuente de un workflow o de un script
  `MUST NOT` contarse como evidencia del control, y un control compensatorio
  de una carencia del host `MUST` cumplir el mismo baremo que un gate. Los
  tests de cableado de workflow no se prohíben: dejan de contar como prueba
  del control. Extiende a los controles fuera del harness la exigencia de
  `deterministic-quality-harness` de observar cada gate saliendo con `1` ante
  una violación real; no la sustituye ni la copia. (team-skills#136; derivada
  de la lectura del código de origen, 2026-10-01; fricciones D7)
- **HR-33 — Toda exención de gate `MUST` concederse por identidad verificable**
  — actor verificado por el host **y** origen de la rama en el mismo
  repositorio que el gate juzga — y `MUST NOT` concederse por un prefijo de
  texto del nombre de rama ni por cualquier otro dato que el autor elige:
  nombrar la rama con el prefijo exento no puede bastar para saltarse el gate.
  Las ramas generadas por la plataforma (reversión, bots de actualización de
  dependencias, ramas de propagación) son un caso de la regla, no una excepción:
  se admiten porque actor y origen constan en la lista de datos del parámetro
  16, y la exención que un prefijo concede sin mirar el actor es una brecha, no
  una exención. La regla no nombra prefijos, bots ni ecosistemas concretos: son
  datos del parámetro 16. (team-skills#137; derivada de la lectura del código
  de origen, 2026-10-01; fricciones D8)
- **HR-34 — Toda regla de gobierno declarada en la documentación —etiqueta,
  nombre de check requerido, método de merge, ruleset y flag de protección—
  `MUST` contrastarse contra la API del host mediante un drift check de solo
  lectura y `MUST` clasificarse como `host-enforced` o `documented-only`**;
  la regla sin enforcement en el host es `documented-only` y `MUST NOT`
  describirse como gate. El check compara el contrato declarado con
  instantáneas JSON de las respuestas de la API (la red queda fuera del
  ejecutable), nunca muta el host ni prueba una escritura para descubrir
  permisos, y ante instantánea ausente o ilegible falla en voz alta (HR-3).
  Los principios de clasificación y verificación en vivo son de
  `repository-delivery-governance`; esta skill aporta el paso de adopción y
  el ejecutable (`assets/host-readback/`). (team-skills#138; API del host
  de origen, 2026-10-01; fricciones D9)
- **HR-35 — El nombre de rama `MUST` generarse, nunca prescribirse de
  memoria**: toda rama de una unidad de trabajo se produce y valida con
  `assets/branch-name.sh` contra la regex del gate del repo (parámetro 1)
  antes del `checkout -b`; un nombre que el gate rechaza se regenera con el
  generador, nunca se reescribe a mano, y el slug se normaliza de forma
  determinista (minúsculas, sin acentos, guiones). (5 renombres de rama en
  una sesión por nombres prescritos sin el número de issue, 2026-10-02;
  hueco G11 del inventario de activos portable)
- **HR-36 — Toda delegación `MUST` usar `references/delegation-template.md`,
  y toda prescripción `MUST` llevar su comando de verificación**: el
  orquestador llena cada bloque de la plantilla (repo, base y tip, worktree,
  superficies editables, hechos en vivo) desde una lectura en vivo con el
  comando y la salida estampados junto al dato y un `verified_at` en UTC; lo
  que no tiene comando es hipótesis, y el worker la trata como tal: reporta
  el desajuste y se detiene, nunca se adapta en silencio (HR-25). (repo
  equivocado en un encargo y superficies prescritas de memoria, 2026-10-02;
  hueco G10 del inventario de activos portable)
- **HR-37 — Con un único mantenedor y cero aprobaciones requeridas, un diff
  que toca rutas de alto riesgo —lista de globs mantenida como dato con la
  misma forma del parámetro 5 («rutas sensibles»); la regla no nombra
  rutas— `MUST` llevar en el cuerpo del PR un campo estructurado de evidencia
  de revisión —lente, veredicto y referencia; el nombre del campo es dato del
  parámetro 19—, validado por un gate, y `MUST NOT` aceptarse prosa libre
  como evidencia**: sin segunda persona, la lente de revisión exigida por la
  documentación es prosa que ningún gate lee, exactamente lo que HR-1
  prohíbe. La regla no introduce aprobación obligatoria de una segunda
  persona ni cambia el presupuesto de 400 líneas; la autoridad del
  presupuesto y su excepción es de `repository-delivery-governance` (HR-10)
  y se referencia, no se copia. (auditoría issue→merge del consumer de
  origen, solo lectura, 2026-10-01: de los últimos 60 PRs fusionados, 60 de
  60 con autor y quien fusiona en la misma cuenta, 3 de 60 con alguna
  revisión registrada y 0 aprobaciones requeridas;
  DysTelefonica/team-skills#139; fricciones D10)
- **HR-38 — El presupuesto de revisión `MUST` tener una métrica de salud**:
  la tasa de excepciones (`size-exception-reason:`) sobre los últimos N PRs
  fusionados (ventana, dato del parámetro 20) con el umbral declarado como
  dato (parámetro 21); superar el umbral `MUST` abrir el re-troceado del
  intake —partir por unidad de trabajo, encadenar PRs— y `MUST NOT`
  resolverse con más excepciones: una excepción habitual delata un mal
  troceado del issue, no un presupuesto por relajar. Esta regla aporta la
  medida y el disparador, no la excepción. (auditoría issue→merge del
  consumer de origen, solo lectura, 2026-10-01: 20 de 60 PRs sobre
  presupuesto y 14 de 60 con `size:exception` — salvedad: los totales de la
  API incluyen lockfiles que el gate del consumer excluye;
  DysTelefonica/team-skills#139; fricciones D10)

## §3 Decision Gates

| Condición | Acción |
|---|---|
| Va a adoptar el patrón en un repo nuevo | ⛔ GATE DE ADOPCIÓN del §1: complete `references/porting-guide.md` fase por fase y verifique cada gate de salida antes de lanzar workers, tocar el repo destino o abrir PR. Sin checklist: nada. |
| El diff supera el presupuesto de líneas | Parta por unidad de trabajo; después encadene PRs; `size-exception-reason:` en el cuerpo es el último recurso. |
| Va a abrir un PR intermedio de una cadena (`chain:partial`) | Palabras de cierre (`Closes`, `Fixes`, `Resolves`) NUNCA en el título ni en el cuerpo del intermedio: solo el PR punta cierra la issue. Intermedios con `Refs #<N>` + etiqueta de cadena; verifique `closingIssuesReferences` tras crear (HR-7). |
| GitHub no registró `closingIssuesReferences` tras crear el PR | Etiqueta de cadena más excepción declarada en el cuerpo; cierre la issue a mano tras el merge con comentario que lo documente. |
| El rojo exige un push de corrección | Empuje y deje que la CI se dispare sola; `rerun --failed` solo para transitorios, `workflow_dispatch` solo cuando el workflow cambió y bajo el límite de HR-17: si publica checks requeridos, resuelva el PR desde el SHA y evalúelo completo. |
| Va a disparar un evento manual o programado sobre la rama de un PR | Solo si el job evalúa el PR completo; si no, publique bajo otro nombre de contexto o falle — nunca un check requerido en verde sin evaluación (HR-30). |
| El cuerpo del PR, sus etiquetas o la issue enlazada cambian después del verde | Reejecute el gate si el host dispara algún evento para ese dato; si no lo dispara (cambio en la issue enlazada), reevalúe en el momento del merge antes de dar el verde por válido (HR-31). |
| Va a declarar un control —gate, auditoría, workflow programado o compensatorio | Primero el fixture violador: sin test de comportamiento que observe su veredicto de fallo no se declara como control; se clasifica `documented-only` hasta tenerlo (HR-32). |
| Llega un PR de reversión creado por la plataforma (el botón Revert genera su propia rama) | Admítalo por identidad verificable — actor y origen en el mismo repositorio, según el parámetro 16 — nunca por el patrón de su nombre; su trazabilidad es el PR que revierte, no una issue nueva: el PR de reversión referencia ese PR (HR-33). |
| Llega una rama de propagación o de bot (actualización de dependencias, propagación del catálogo) | Admítala por identidad verificable — actor exento Y rama del mismo repositorio, según el parámetro 16; su trazabilidad es el manifiesto o registro que la rama actualiza — y exija que esa identidad se pueda verificar en el consumer; el patrón del nombre por sí solo no admite ni rechaza (HR-33). |
| Falla un paso del job de lint | Ejecute el preflight completo antes de empujar, no solo el paso roto (HR-5). |
| Va a añadir, renombrar o eliminar un job del workflow | Actualice los tres conjuntos en el mismo PR — jobs del workflow, `needs` del agregador y conjunto conocido por el evaluador; una clave de `needs` desconocida es violación, no se ignora (HR-29). |
| Aparece una fricción que ninguna regla cubre | Aplique el protocolo de HR-11: registrar con evidencia, arreglar por el pipeline, destilar en regla. |
| Un gate acumula baseline creciente sin defecto real cazado | Duerma el gate tras su policy file (`enforcement: "dormant"`), no lo retire; la re-activación es un cambio de datos con review (HR-18). |
| El PR sube una baseline o duerme un gate | El gate compara la entrada contra la copia de la rama base; la relajación solo pasa con su campo de datos de motivo y referencia, validado por el propio gate (HR-15). |
| Va a dejar un gate como informativo sin policy file | No lo haga: informativo sin policy pierde el candado construido; muévalo a dormant (R15). |
| Va a guardar un registro acumulativo entre sesiones | Sin clave de upsert: una observación nueva por entrada (HR-12). |
| Debe reiniciar la aplicación de producción | Use el procedimiento del runbook de deploy; el reinicio directo redespliega el HEAD de la rama por defecto sin gate de evidencia. |
| Hereda un proceso vivo (vigía) de otra sesión | Verifique qué hace leyendo su script; cumplido su propósito, termínelo; inesperado, deténgase y reporte su contenido. |
| Se declara un incidente de producción | Hotfix: issue `type:bug` → fix en main → deploy inmediato → release PATCH → post-mortem blameless con action items como issues (HR-20, HR-21). |
| Va a esperar un resultado de CI o de otro actor | Aplique la jerarquía de HR-23: auto-merge armado, `allow_update_branch`, required checks o workflow programado; solo si no hay mecanismo, un script versionado con deadline y fallback; nunca un vigía IA. |
| Va a delegar una tarea que correrá en paralelo con otra | Asígnele worktree y rama propios en el encargo (HR-24); nunca dos actores sobre el mismo working tree. |
| Va a crear la rama de una unidad de trabajo | Genere el nombre con `assets/branch-name.sh` (issue + tipo + slug) y valídelo contra la regex del repo antes del `checkout -b`; nunca lo escriba de memoria (HR-35). |
| Va a emitir un encargo de delegación | Llene `references/delegation-template.md` bloque a bloque desde lectura en vivo, con comando, salida y `verified_at`; una prescripción sin comando es hipótesis, no hecho (HR-36, HR-25). |
| Recibe SHA, conteos, rutas o superficies prescritos por el orquestador | Verifíquelos en vivo antes de ejecutar y reutilice lo que exista (HR-25). |
| Va a comparar una medición local contra un baseline o gate de CI | Mida con la toolchain pineada del juez o re-mida con ella; sin pin no hay comparación válida (HR-26). |
| Un PATCH de settings respondió 200 pero el read-back no muestra el valor | Lea de vuelta dos veces con delay y verifique el plan de la org: el campo puede ser paywalled y descartarse en silencio (HR-27). |
| Tests rojos solo en local y verdes en CI | Sospeche del `.env` local filtrando variables a `Settings`; aísle el entorno de tests o registre el rojo como ambiental (HR-28). |
| Va a cortar un release | Tag semver anotado + GitHub Release `Latest` + notas concisas + playbook `RELEASE-<TAG>.md` con imagen de rollback capturada antes de desplegar (HR-19, HR-22). |
| El diff toca rutas de alto riesgo (parámetro 18) y no hay segundo revisor | El cuerpo del PR lleva el campo de evidencia de revisión (parámetro 19) con lente, veredicto y referencia, validado por el gate; la prosa libre no cuenta como evidencia (HR-35). |
| La tasa de excepciones sobre la ventana (parámetro 20) supera el umbral (parámetro 21) | Abra el re-troceado del intake —partir por unidad de trabajo, encadenar PRs—; nunca resuelva la tasa con más excepciones (HR-36). |

## §4 Execution Steps

### Adopción del patrón en un repo

1. **Audite.** Inventaríe cada control del CI —gate, auditoría, workflow
   programado o compensatorio— con su veredicto (se queda, se refuerza, se
   duerme, se retira), la evidencia que lo sostiene y el test que lo ve
   fallar; un control sin fixture violador se registra como
   `documented-only`, no como control (HR-32). Contraste cada afirmación de
   la documentación contra los workflows reales; corrija los desvíos en la
   misma sesión. Modelo de salida: `references/gate-verdicts.md`.
2. **Lea de vuelta el host.** Capture con GETs de solo lectura las
   respuestas de la API —etiquetas, settings de merge, protección de la
   rama, rulesets— en instantáneas JSON y contrástelas con el contrato
   declarado mediante `assets/host-readback/check_host_drift.py`: cada
   regla queda clasificada `host-enforced` o `documented-only`, y la que
   no tiene enforcement en el host `MUST NOT` describirse como gate
   (HR-34). El check nunca muta el host ni prueba una escritura para
   descubrir permisos; instantánea ausente o ilegible es un rojo, no un
   skip (HR-3).
3. **Mida.** Presupuesto real por PR, duración de la CI, falsos verdes conocidos,
   pasos de CI que nadie ejecuta en local. Sin cifra no hay decisión de gates.
4. **Instale.** Extraiga los parámetros del repo (`assets/parameters.md`,
   incluido el policy file de gates dormibles), adapte los scripts de
   referencia (ubicación declarada en `assets/parameters.md`), configure la
   protección de rama (checks requeridos, `strict`, sin force-push) y el
   preflight canónico que lee los pasos del job de lint del propio workflow.
   Los tests del policy file cubren ambos estados de `enforcement` con
   fixtures y no fijan el valor vigente, de modo que re-armar un gate a
   `enforcing` deje la suite en verde (HR-18).
5. **Valide en real.** Ejecute de verdad cada gate que toque producción (HR-2) y
   complete una cadena de PRs encadenados de extremo a extremo con CI en cada
   tramo antes de declarar el patrón adoptado.

### Operación por unidad de trabajo

1. Issue con el contrato canónico completo (secciones exactas que el gate lee) y
   etiqueta de aprobación aplicada **al crearla**: el gate lee la issue remota,
   no su copia local.
2. Worktree dedicado y rama generada con `assets/branch-name.sh`
   (`<tipo>/<N>-<slug>`, HR-35); el gate deriva la issue del nombre de rama.
   Cuando la tarea corre en paralelo con otro actor, el worktree es propio y
   exclusivo (HR-24). El encargo al worker se llena con
   `references/delegation-template.md` (HR-36).
3. Preflight completo en local antes de cada push (HR-4, HR-5).
4. PR con todas las etiquetas en el comando de creación; `Closes #<issue>` solo
   en la punta de la cadena (HR-6, HR-7).
5. Verifique `closingIssuesReferences` tras crear el PR; si no aparece, declare
   la excepción en el cuerpo y cierre a mano tras el merge (HR-7).
6. CI en vuelta: clasifique rojos solo tras identificar el paso que falla vía
   API; empuje los fixes; rerun solo para transitorios (HR-9, gates del §3).
7. Merge con auto-merge y commit de fusión, sin borrar la rama remota; con
   `strict`, actualice la rama con la secuencia determinista de HR-17.
8. Deploy: registre el veredicto de la batería sobre la URL de salud del
   parámetro 6 de la revisión desplegada (HR-10); apague cualquier flag de
   prueba al terminar, también si la batería falla.

**Ramas generadas por la plataforma.**

El botón Revert crea su propia rama de reversión, y cada ecosistema de
actualización de dependencias habilitado en el repositorio abre las suyas;
ninguna casa con el patrón canónico (parámetro 1), y un prefijo de texto no
puede conceder la exención (HR-33). Para cada fuente de ramas de plataforma,
con los actores y patrones concretos como datos del parámetro 16:

1. **Admisión por identidad.** El gate de nombre y el gate de trazabilidad
   admiten la rama solo cuando el actor figura en la lista de actores exentos
   y la rama pertenece al mismo repositorio que el gate juzga; un prefijo
   exento con actor no exento, o un actor exento con rama de otro repositorio,
   es una violación ordinaria. Las ramas de propagación del catálogo
   (`skill-fleet/<consumer>`) se rigen igual: su identidad debe poder
   verificarse en el consumer, no presumirse del nombre.
2. **Trazabilidad.** El PR de reversión no abre issue: su trazabilidad es el
   PR que revierte, al que referencia. Las ramas de un ecosistema de
   actualización trazan contra el manifiesto o registro que la rama actualiza,
   que es el cambio verificable de la unidad de trabajo; el gate de issue-spec
   evalúa eso en lugar del contrato issue-first, nunca lo omite en silencio.

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
5. Escriba el post-mortem blameless en la ruta de post-mortems del consumer
   (parámetro 9) con secciones Timeline (UTC) / Impact / Root cause / What
   worked / What failed; causas de sistema, nunca personas (HR-21).
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
| `review_budget_health` | object | `{window, exceptions, rate, threshold}`: métrica de salud del presupuesto sobre los últimos N PRs fusionados — ventana medida, excepciones contadas, tasa resultante y umbral declarado (HR-36). |
| `preflight_command` | string | Comando canónico ejecutado antes del último push. |
| `hr_traceability` | array | Pares `{rule, evidence}` que trazan cada HR-N aplicada a su fricción de origen. |
| `risks` | string[] | Riesgos abiertos (gates sin medir, contradicciones doc-workflow pendientes). |
| `next_recommended` | `"fix_violations" \| "register_in_catalog" \| "none"` | Siguiente acción. |

## §6 Anti-patterns

| Síntoma | Fix |
|---|---|
| Etiquetas aplicadas después de crear el PR y el gate queda rojo | Etiquete en `gh pr create --label`; si ya creó el PR, use la API REST y espere rerun o push. |
| `Closes` en el título o en un tramo intermedio cierra la issue antes de tiempo | Palabras de cierre solo en el cuerpo del PR punta; intermedios con `Refs` y etiqueta de cadena (#1138). |
| Verde en local y rojo en CI por un paso de lint que el runner de tests local no ejecuta (parámetro 13) | Preflight canónico que reproduce el job completo; ejecútelo antes de cada push. |
| Gate que imprime «`OK (0 hallazgos)`» sin haber corrido el herramienta | Fail-loud: el gate falla si el herramienta no está instalado o no midió (HR-3). |
| Un rojo de raíz enmascarado como N fallos en el agregador | El agregador separa causa raíz de skips en cascada y agrupa las consecuencias. |
| Job cableado en `needs` y ausente del conjunto conocido falla sin que el agregador lo note | Paridad three-way verificada: `jobs(workflow) − {agregador}` = `needs` = conjunto conocido; una clave de `needs` desconocida cuenta como violación y no se ignora (HR-29). |
| Un check requerido sale en verde desde un evento manual o programado que nunca evaluó el PR | Nombres requeridos solo desde el evento que evalúa; en cualquier otro, otro nombre de contexto o fallo — nunca éxito sin evaluación (HR-30). |
| El verde sobrevive a la edición del cuerpo del PR o a un cambio de etiquetas de la issue enlazada | Disparador para el dato mutable donde exista y reevaluación en el merge donde no; un gate sin relectura del dato no certifica nada (HR-31). |
| Test que «prueba» el control afirmando subcadenas del fuente del script o del workflow | Ejecute la lógica del control contra un fixture que viola la regla y observe el veredicto de fallo; la prueba de subcadenas no cuenta como evidencia (HR-32). |
| Exención de gate concedida por un prefijo del nombre de rama: renombrar la rama basta para saltarse el gate | Exención solo por identidad verificable — actor exento Y origen en el mismo repositorio, como datos del parámetro 16; el prefijo del nombre no es identidad y la exención que concede solo es una brecha (HR-33). |
| PR de reversión de la plataforma bloqueado por el gate de nombre en el momento de más prisa | El botón Revert genera su propia rama: admítala por identidad verificable según el parámetro 16, con el PR revertido como trazabilidad; exigirle el patrón canónico bloquea el revert sin proteger nada (HR-33). |
| Control compensatorio documentado y nunca visto fallar | Mismo baremo que un gate: fixture violador y veredicto de fallo observado; sin eso es `documented-only`, no control (HR-32). |
| Etiqueta documentada que no existe en el host: la doc ordena aplicarla y ningún gate la encontrará jamás | Contraste con la API del host mediante el drift check de solo lectura (`assets/host-readback/`); la etiqueta que el host no tiene se crea o se borra de la doc en la misma sesión (HR-34). |
| Política de merge documentada (solo commit de fusión) con squash o rebase habilitados en el host | Readback del host: todo método habilitado se declara en el contrato; sin enforcement, la regla es `documented-only` y `MUST NOT` describirse como gate (HR-34). |
| Bucle de sondeo de CI o vigía que sobrevive a la sesión | Auto-merge más una sonda única a los dos minutos; sin procesos vivos (HR-9). |
| Variable global que aprueba o bloquea deploys para siempre | Estado de commit por SHA; la evidencia viaja con la revisión (HR-10). |
| Fix de fricción aplicado a mano sin registrar | El rojo vuelve con la próxima sesión; registre con evidencia y destile en regla. |
| Registro acumulativo guardado con upsert por clave | Una observación nueva por entrada; el upsert sustituye el contenido (HR-12). |
| Rerun de un run cuyo SHA ya está corregido en local | Empuje; el rerun reproduce el SHA original y quema un ciclo de espera. |
| Batería ejecutada con los tests de la rama por defecto contra un deploy anterior | Worktree en la revisión desplegada; los fallos por desfase se clasifican, no se registran como fallo del deploy. |
| Gate retirado por perder su justificación | Duerma el gate tras un policy file con el motor probado; retirarlo destruye el candado y la re-activación futura exige reconstruirlo (HR-18). |
| Baseline de un ratchet editada a mano en cada reducción | Comando de regeneración de baseline; el gate solo rechaza entradas nuevas (HR-15). |
| El mismo PR que el gate juzga sube la baseline o añade una entrada a la allowlist | El gate compara cada entrada editable contra la copia de la rama base; la relajación exige su campo de datos con motivo y referencia (HR-15). |
| Un gate dormido revienta (o su herramienta falta) y el run sale en verde | `dormant` suprime solo el código de «hallazgos»; fallo de ejecución, herramienta ausente o gate no ejecutado se propagan como rojo (HR-18, HR-3). |
| Re-armar un gate a `enforcing` deja la suite en rojo | Los tests del policy file cubren ambos estados de `enforcement` con fixtures y no fijan el valor vigente; el re-armado es solo el cambio de datos del policy file (HR-18). |
| Causa raíz enterrada en las notas de release o en el cuerpo del PR | Notas concisas con enlace; el post-mortem vive en su doc dedicado (HR-19, HR-21). |
| Fix de incidente viviendo solo en una rama paralela esperando el release regular | Hotfix aterriza en main, deploy inmediato y release PATCH (HR-20). |
| Post-mortem que nombra personas como causa | Blameless: causas de sistema; falló el proceso, no la persona (HR-21). |
| Deploy sin imagen de rollback capturada | Capture la imagen de rollback en el playbook antes de aplicar (HR-22). |
| Bucle `--watch`, watcher de sesión o vigía IA esperando CI | Mecanismo primero: auto-merge armado más `allow_update_branch`; donde no hay mecanismo, script versionado con deadline y fallback (HR-23). |
| Dos workers sobre el mismo working tree | Un worktree por actor concurrente; el síntoma es el commit sobre la rama ajena a mitad de vuelo (HR-24). |
| Prescripción del orquestador ejecutada sin verificarla | El snapshot puede ser stale: verifique SHA, conteos y rutas en vivo y reutilice lo existente (HR-25). |
| Rama prescrita de memoria que el gate de nombre rechaza (5× en una sesión) | Genere el nombre con `assets/branch-name.sh` y valídelo antes de crear la rama; el renombre posterior paga CI doble (HR-35). |
| Encargo que nombra repo, superficies o SHAs sin comando de verificación | Use `references/delegation-template.md`: cada dato con comando y salida en vivo; el worker reporta el desajuste en vez de adaptarse (HR-36, HR-25). |
| Medición local comparada contra el juez de CI sin toolchain pineada | Pin de versiones en la stack de medición o re-medición por la toolchain del juez (HR-26). |
| PATCH de settings dado por bueno por su 200 OK | Read-back doble con delay y verificación del plan: paywalled se descarta sin error (HR-27). |
| Suite que solo pasa con el `.env` del desarrollador delante | Aísle el entorno de tests del `.env` local y documente los rojos ambientales conocidos (HR-28). |
| Rojo de CI diagnosticado grepeando logs del runner en vez de pedir la evidencia por paso | `gh api repos/<org>/<repo>/actions/jobs/<id>` separa el paso que falla; el log del runner equivocado (hosted frente a self-hosted) fabricó el diagnóstico «Docker daemon» ×3 (C2 del porting-guide). |
| Premisa de propagación o de gobernanza del destino tomada de su documentación | Audite el mecanismo real en vivo (hooks, reconciliador, markers, manifest) antes de depender de él; la premisa falsa dejó espejos stale medio tramo (C4 del porting-guide). |
| Adopción del patrón lanzada sin el checklist de pre-vuelo | GATE DE ADOPCIÓN del §1: sin `references/porting-guide.md` completado no hay workers, ni toques al repo destino, ni PR (anclaje: Cadete, 2026-09-30/10-01). |
| Re-implementar autoridad de review en el patrón (linajes, recibos, rondas de jueces, consentimientos como reglas de CI) | Es capacidad del harness (`gentle-ai`); el patrón la asume instalada, no la duplica ni la documenta como propia. |
| Lente de revisión exigida solo en prosa (ningún gate la lee) | Para diffs de alto riesgo, campo estructurado de evidencia (lente, veredicto, referencia) en el cuerpo del PR, validado por un gate; la prosa libre no es evidencia (HR-35). |
| Excepción de tamaño convertida en costumbre | Métrica de salud del presupuesto: tasa de excepciones sobre los últimos N PRs fusionados con umbral en datos; superarla abre el re-troceado del intake, nunca más excepciones (HR-36). |

## §7 Companion skills

| Skill | Qué posee | Cargar junto cuando |
|---|---|---|
| `repository-delivery-governance` | Auditoría genérica del repositorio y matriz de enforcement (policy documentado, validado en local, CI, host, manual) | Vaya a auditar o cambiar la protección de rama, checks requeridos o política de merge. |
| `deterministic-quality-harness` | Ratchets, identidad estable de hallazgos y assets de gates (p. ej. `check_pr_size.py`, policy files) | Vaya a instalar o ajustar el motor de un gate. El qué y cuándo de la operación es esta skill. |
| `ci-pattern` (esta skill) | Operación por unidad de trabajo, evidencia por SHA, cadena de PRs y release | — |
| `branch-pr` | Ciclo de apertura y fusión del PR | Vaya a abrir o fusionar el PR de una unidad de trabajo bajo este patrón. |
| `chained-pr` | Encadenado de PRs cuando el diff supera el presupuesto | El diff supera el presupuesto y va a encadenar PRs. |
| `work-unit-commits` | Partición de commits por unidad de trabajo | Vaya a planificar los commits del PR por unidad de trabajo. |
| `documentation-alan-style` | Documentación que refleja el código real | Vaya a actualizar la documentación del CI para que refleje el código. |

Frontera con `deterministic-quality-harness`: su asset `check_pr_size.py` exige
la etiqueta `size:exception` además del campo del cuerpo. Eso es una
instanciación consumer que añade el mecanismo opcional de HR-8, no una
contradicción: el campo `size-exception-reason:` del cuerpo sigue siendo el
invariante obligatorio (coherente con `slices/partials/web.md` del catálogo
`DysTelefonica/team-skills` — referencia al catálogo, no a una ruta de esta
skill —, donde el campo
es obligatorio y la etiqueta es mecanismo opcional por consumer).

## §8 References

- `assets/required-jobs/` — primer asset ejecutable de la skill: agregador
  fail-closed de jobs requeridos con política externa (sin nombres de jobs,
  eventos ni skips en el código), política de ejemplo y suite con test de
  paridad workflow↔política; el `README.md` del asset documenta el destino
  en el consumer y el cableado de `toJSON(needs)`.
- `assets/host-readback/` — asset de readback del host: contrato de
  ejemplo (`host-contract.example.json`), drift check de solo lectura
  (`check_host_drift.py`, stdlib, sin red) y suite de tests; clasifica
  cada regla `host-enforced` o `documented-only` (HR-34) contrastando el
  contrato declarado con instantáneas JSON de las respuestas de la API.
- `assets/parameters.md` — los parámetros que se extraen por repo, con los
  valores del consumer de origen como ejemplo, el policy file de gates dormibles
  (HR-18) y la ubicación de los scripts de referencia.
- `assets/branch-name.sh` — generador y validador determinista del nombre de
  rama `<tipo>/<N>-<slug>` (HR-35): slugificación determinista, validación
  contra la regex del gate del destino (leída del `check_branch_name.py` del
  repo con `--gate-script` o pasada por `--pattern`) y auto-test ejecutable
  sin el repo destino (`self-test`).
- `references/delegation-template.md` — plantilla canónica de encargo de
  delegación (HR-36): repo verificado en vivo, base y tip, worktree y rama
  generada, superficies editables verificadas, hechos en vivo a confirmar por
  el worker, condiciones de parada y plazo con reporte por transición.
- `references/fricciones.md` — catálogo destilado: fricción, antídoto y evidencia.
- `references/porting-guide.md` — checklist de pre-vuelo de la adopción fase
  por fase; cada gate cita el incidente real de Cadete (2026-09-30/10-01) que
  lo justifica. Exigido por el GATE DE ADOPCIÓN del §1.
- `references/gate-verdicts.md` — veredicto de cada gate del inventario con su base.
- `references/benchmark-gentle-ai.md` — ideas transferibles y rechazadas de otro CI.
- `references/incidents.md` — ejemplo destilado de hotfix, post-mortem y
  release sobre un incidente real de pérdida de datos.
- `references/cli-spec.md` — contrato normativo de la CLI `assets/bin/ci-pattern`:
  comandos, códigos de salida, manifiesto, idempotencia y frontera honesta.
- `references/asset-inventory.md` — inventario de extracción de los activos y
  parámetros del patrón (62 activos, P01-P48, huecos G1-G12) tomado del origen
  verificado; fuente de las citas de `assets/parameters.schema.json`,
  `assets/branch-name.sh` y `assets/templates/`.
- Implementación de referencia del resto del patrón: versionada hoy en
  `ardelperal/APAP_WEB` (`scripts/preflight.py`, `scripts/check_issue_specs.py`,
  `scripts/check_release_evidence.py`, `scripts/check_release_e2e_required.py`,
  `scripts/production_smoke.py` y `.github/release-e2e-paths.txt`), pendiente
  de publicarse como asset portátil de esta skill; el agregador de jobs
  requeridos ya vive aquí (`assets/required-jobs/`). Detalles en
  `assets/parameters.md`.
