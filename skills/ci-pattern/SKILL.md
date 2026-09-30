---
name: ci-pattern
description: "Trigger: CI perfecto, patrón CI, gates, preflight, issue-spec, ratchet, evidencia SHA, adoptar CI, presupuesto de revisión, chain:partial. Distila el patrón de CI del repo (gates deterministas, presupuesto de revisión, evidencia por SHA, cadena de PRs encadenados y protocolo de mejora continua) y enseña a adoptarlo o auditarlo en otro repositorio."
license: Apache-2.0
metadata:
  author: ardelperal
  version: "0.1"
  last_verified: 2026-09-30
  based_on: "odd/skill-ci-portable/ @ ardelperal/APAP_WEB (épica #935, 2026-09-29/30)"
---

# Patrón de CI — gates deterministas y evidencia por SHA

El patrón combina cuatro piezas sobre un mismo repositorio:

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

El patrón nació de una épica de fricciones reales (18 reglas, cada una pagada con
un rojo de CI). El catálogo destilado y el veredicto de gates viven en
`references/`; los parámetros portables, en `assets/parameters.md`. Los scripts de
implementación de referencia están versionados en este repo bajo `scripts/`.

## §1 Activation

Cargue esta skill cuando:

- Vaya a **adoptar o auditar este patrón de CI en otro repositorio** (inventario
  de gates, medición, instalación, validación real).
- Abra, espere o revise **PRs bajo este patrón**: etiquetas al crear, presupuesto,
  cadena de PRs, cierre de issue, merge con evidencia.
- Deba **clasificar un rojo de CI** o decidir entre push, rerun o dispatch.
- Toque **evidencia de deploy**: estados por SHA, smoke de producción, baterías.
- Vaya a **destilar una fricción nueva** en regla del playbook.

No la cargue cuando:

- Escriba tests de aplicación o decida su capa (eso es `apap-testing-strategy`).
- Toque auth, CSRF o secretos de la aplicación (eso es `apap-security`).
- Ejecute la batería e2e de producción (eso es `docs/runbooks/e2e-production.md`;
  esta skill solo gobierna cómo se registra el veredicto).

Fuentes normativas:

- `skills/ci-pattern/references/fricciones.md` — catálogo destilado con antídoto.
- `skills/ci-pattern/references/gate-verdicts.md` — veredicto por gate con evidencia.
- `skills/ci-pattern/references/benchmark-gentle-ai.md` — ideas contrastadas de otro CI.
- `skills/ci-pattern/assets/parameters.md` — los parámetros que se extraen por repo.

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

## §3 Decision Gates

| Condición | Acción |
|---|---|
| Va a adoptar el patrón en un repo nuevo | Ejecute los cuatro pasos de adopción del §4: auditar, medir, instalar, validar en real. |
| El diff supera el presupuesto de líneas | Parta por unidad de trabajo; después encadene PRs; `size-exception-reason:` en el cuerpo es el último recurso. |
| GitHub no registró `closingIssuesReferences` tras crear el PR | Etiqueta de cadena más excepción declarada en el cuerpo; cierre la issue a mano tras el merge con comentario que lo documente. |
| El rojo exige un push de corrección | Empuje y deje que la CI se dispare sola; `rerun --failed` solo para transitorios, `workflow_dispatch` solo cuando el workflow cambió. |
| Falla un paso del job de lint | Ejecute el preflight completo antes de empujar, no solo el paso roto (HR-5). |
| Aparece una fricción que ninguna regla cubre | Aplique el protocolo de HR-11: registrar con evidencia, arreglar por el pipeline, destilar en regla. |
| Un gate acumula baseline creciente sin defecto real cazado | Duerma el gate tras su policy file (`enforcement: "dormant"`), no lo retire; la re-activación es un cambio de datos con review (HR-18). |
| Va a dejar un gate como informativo sin policy file | No lo haga: informativo sin policy pierde el candado construido; muévalo a dormant (R15). |
| Va a guardar un registro acumulativo entre sesiones | Sin clave de upsert: una observación nueva por entrada (HR-12). |
| Debe reiniciar la aplicación de producción | Use el procedimiento del runbook de deploy; el reinicio directo redespliega el HEAD de la rama por defecto sin gate de evidencia. |
| Hereda un proceso vivo (vigía) de otra sesión | Verifique qué hace leyendo su script; cumplido su propósito, termínelo; inesperado, deténgase y reporte su contenido. |

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
   nombre de rama.
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
| `Closes` en el título o en un tramo intermedio cierra la issue antes de tiempo | Palabras de cierre solo en el cuerpo del PR punta; intermedios con `Refs` y etiqueta de cadena. |
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
- `references/gate-verdicts.md` — veredicto de cada gate del inventario con su base.
- `references/benchmark-gentle-ai.md` — ideas transferibles y rechazadas de otro CI.
- Implementación de referencia versionada en este repo: `scripts/preflight.py`,
  `scripts/check_pr_size.py`, `scripts/check_issue_specs.py`,
  `scripts/check_required_jobs.py`, `scripts/check_release_evidence.py`,
  `scripts/check_release_e2e_required.py`, `scripts/production_smoke.py` y
  `.github/release-e2e-paths.txt`.
