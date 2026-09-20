---
name: intake-roadmap-loop
description: Trigger: intake, sprint intake, client meeting, requirements doc, acta de requisitos, fuente de intake, tasks.md del SDD, features nuevas, fixes a arreglar, qué entra en este sprint, qué quedó pendiente, roadmap activo, qué va después, ciclo intake a UAT, governance sprint, owner del ciclo, ADR discipline, retomemos el ciclo, sigue con el ciclo, dónde quedamos, qué ciclo tengo abierto, cycle recovery fallback, worktree aislado por cambio, issue + PR + CI, trazabilidad por PR. Owner del ciclo completo intake → ADR → dev → UAT → archive para sprints con puesta en producción y validación por el cliente. Cada cambio de código del ciclo se ejecuta en un worktree aislado con el ciclo completo (HR-14): issue → worktree → PR con CI → merge → close → borrado → trazabilidad. Para cada pregunta del ciclo, una sola fuente es autoritativa (HR-15): issue tracker para ¿está hecho?, engram para notas explícitas, ADR para decisiones, roadmap vivo para estado+motivo. El roadmap vivo es un mapa al estado, no un duplicado; las decisiones arquitectónicas viven en archivos planos por tema; el ciclo se ancla en engram con un topic_key estable para sobrevivir entre sesiones. La sección Session start ritual define el prompt estándar de apertura y la cadena de fallback para cuando el usuario no recuerda el cycle-id.
license: Apache-2.0
metadata:
  author: Gentleman AI Contributors
  version: 1.4
  language: es-ES
  last_verified: 2026-08-28
  references: 
  - "https: //github.com/Gentleman-Programming/gentle-ai/tree/main/docs/architecture
  scope: ['universal']
  auto_invoke: ['running the intake/roadmap cycle']
  tiers: ['universal']
---



# intake-roadmap-loop

> **Proposito.** Esta skill gobierna el ciclo completo de un sprint con puesta en producción y validación por el cliente: desde la entrega inicial de requisitos (Excel, DOC, correo o transcripción) hasta el archivado del roadmap tras la firma de UAT. Tres principios sostienen la skill: (1) el roadmap vivo es un **mapa** al estado, no un duplicado; (2) las decisiones arquitectónicas son **archivos planos por tema**, no ADRs numerados; (3) el ciclo se ancla en engram con un `topic_key` estable para sobrevivir entre sesiones.

## Activation

Cargue esta skill cuando el usuario pronuncie cualquiera de las formas siguientes:

- "intake", "sprint intake", "client meeting", "reunión con cliente".
- "acta de requisitos", "fuente de intake", "lista de requisitos", "tasks.md del SDD", "funcionalidades nuevas", "fixes a arreglar", "kickoff con cliente".
- "qué entra en este sprint", "qué quedó pendiente del ciclo anterior", "qué va después".
- "roadmap activo", "actualizar el roadmap", "el roadmap vivo".
- "ADR", "decisión irreversible", "architecture decision record".
- "ciclo intake a UAT", "puesta en UAT", "preparar para UAT", "firma de UAT".
- "governance sprint", "owner del ciclo".

No la cargue para:

- Tareas one-shot sin ciclo (un solo fix, una sola PR sin contrato con cliente).
- Documentación interna que no entra en un sprint firmado.
- Generación de criterios de aceptación (esa labor es de la skill de UAT del proyecto).
- Investigación read-only sin entrega pactada.

## Session start ritual

La skill se invoca mediante un prompt estándar de apertura y una cadena de fallback para recuperación de ciclo. Ambos aplican una vez la skill está cargada, con o sin `cycle-id` conocido.

### Trigger phrases (sin cycle-id)

- "retomemos el ciclo", "sigue con el ciclo", "qué quedó pendiente".
- "el ciclo actual", "el ciclo en el que estábamos", "dónde quedamos".
- "qué ciclo tengo abierto", "mostrame los ciclos activos".
- "actualizar el roadmap", "archivar el ciclo".

Si el usuario nombra el `cycle-id`, el prompt estándar de apertura aplica directamente. Si no, la cadena de fallback aplica.

### Prompt estándar de apertura

Pegue al iniciar sesión para retomar un ciclo conocido:

```text
Retomemos el ciclo <cycle-id>.
- Gate actual: <gate>
- Topic key pineada: <topic_key> (#<observation-id>)
- Próximo paso: <next_recommended pendiente>

Aplicá HR-13 primero (mem_search) y mostrame el estado antes de proponer nada (HR-12).
```

El orquestador completa los placeholders desde la observación de intake pineada. El usuario confirma el próximo paso antes de que el orquestador avance (HR-12).

### Cycle recovery fallback chain

Cuando el usuario abre una sesión sin nombrar el `cycle-id`, el orquestador aplica esta cadena:

| Paso | Operación | Resultado esperado |
|---|---|---|
| 1 | `mem_context` | Historial reciente, incluye observaciones pineadas. |
| 2 | `mem_search` por topic_keys pineadas | Recupera la observación de intake con el `cycle-id`. |
| 3 | `mem_search` por "ciclo activo" | Encuentra ciclos abiertos sin pinear. |
| 4 | Un único ciclo activo | Aplicar HR-13 con ese `cycle-id` y proceder. |
| 5 | Múltiples ciclos activos | Preguntar al usuario cuál retomar. Nunca fabricar un `cycle-id`. |

Pinear la observación de intake (`mem_pin(id=<intake-observation-id>)`) en cada apertura de ciclo acelera el paso 2 sin alterar la lógica.

### Complemento a HR-13

HR-13 obliga a `mem_search query="topic_key=<cycle-id>"` al abrir sesión y asume el `cycle-id` conocido. La cadena de fallback cubre el caso contrario y eleva la amnesia de `cycle-id` a compromiso observable: la IA no improvisa, recupera.

## Hard Rules

> **HR-1.** Cada evento de intake produce una observación engram con `topic_key` estable de la forma `<cycle-id>/<gate>`. Reutilizar el mismo `cycle-id` a lo largo de todas las iteraciones del ciclo es obligatorio.

> **HR-2.** Las decisiones arquitectónicas viven en archivos planos por tema en `docs/<project>/architecture/<topic-slug>.md`. Un archivo por decisión. Estado: `proposed` → `accepted` o `superseded`. Una vez `accepted`, no se edita; cualquier refinamiento abre un archivo nuevo que `superseded` al previo. **No se usa numeración** (`adr-001-...md`): la gente busca decisiones por tema, no por orden cronológico. Referencia: la carpeta `docs/architecture/` del repo de Gentleman-Programming/gentle-ai.

> **HR-3.** El roadmap vivo es un único archivo Markdown en `docs/<project>/roadmap.md` y funciona como **mapa al estado, no como duplicado**. El estado vive en: (a) la observación de `topic_key` en engram, (b) los archivos de arquitectura en `docs/<project>/architecture/`, (c) el issue tracker del proyecto. Las snapshots puntuales para informes de gestión se generan con la skill de snapshot del proyecto y se archivan con fecha en `archive/`; son derivadas, nunca autoritativas.

> **HR-4.** En la firma de UAT, el roadmap vivo se archiva como `archive/<cycle-id>-final-<YYYY-MM-DD>.md` y los archivos de arquitectura del ciclo se mueven a `archive/<cycle-id>/architecture/`. Se abre un roadmap vivo nuevo en el siguiente intake. Los archivos archivados son inmutables.

> **HR-5.** Cada referencia a una decisión en el roadmap vivo usa un path relativo (`../architecture/<topic-slug>.md`) y cada archivo de arquitectura es localizable desde el roadmap vivo por nombre. La trazabilidad bidireccional es obligatoria. Sin links relativos, la trazabilidad se rompe cuando se archiva.

> **HR-6.** Cada item del intake se clasifica en dos ejes independientes antes de empezar la especificación:
- **origen**: `requested` (lo pidió el cliente) | `derived` (apareció durante el trabajo).
- **validador**: `user` (validable por el cliente vía UI) | `dev` (infra; solo desarrollo valida).

> **HR-7.** Se reutiliza la skill de snapshots del proyecto para los informes periódicos de gestión. Esta skill orquesta el ciclo, no la mecánica de snapshots. Las snapshots viven en `archive/` con sufijo de fecha.

> **HR-8.** La UAT del ciclo se construye durante la compuerta `mid_sprint`, de forma progresiva conforme cada item pasa a verde. Para cada item verde, se invoca la skill de UAT designada por el proyecto — por defecto `feature-acceptance-uat` — para generar o ampliar la acceptance web (`usuario` o `desarrollo` según el eje `validador` del item) con criterios DADO/CUANDO/ENTONCES y `pasos` reproducibles. La skill de UAT NO duplica criterios; este arnés monitoriza la firma acumulada al cierre del ciclo y la entrelaza en el roadmap al cerrar la compuerta `uat_handoff`. Sin firma de UAT en los ejes aplicables de todos los items, el ciclo no avanza a `uat_handoff` ni a producción.

> **HR-9.** Cuando el estilo documental del proyecto prescribe castellano peninsular formal (por ejemplo, la skill `documentation-alan-style`), esta skill produce los artefactos humanos en 3ª persona, con tratamiento de usted y sin voseo. Ajuste `metadata.language` si el proyecto requiere otra lengua.

> **HR-10.** Nunca se inventa un item que no figure en la fuente de intake. Si el intake menciona N items, el roadmap vivo los referencia (no los duplica) más cualquier item `derived` descubierto durante el ciclo.

> **HR-11.** Cada cambio de estado lleva una cadena `motivo` de una línea. Un estado sin motivo es reject.

> **HR-12.** En cada compuerta (`intake`, `mid_sprint`, `uat_handoff`, `archive`), esta skill emite una acción `next_recommended` y se detiene hasta que el usuario confirme.

> **HR-13.** Toda sesión que abra un ciclo existente empieza por `mem_search query="topic_key=<cycle-id>"`. La recuperación del contexto es obligatoria.

> **HR-14.** Cada cambio de código del ciclo — fix, feature, refactor, helper, átomo, test, o actualización de fuente VBA — se ejecuta en un worktree aislado dedicado (rama propia) con el ciclo completo: issue en GitHub (nuevo si el cambio no tiene) o referencia explícita al id del acta → worktree desde `origin/staging` siguiendo la skill `worktree-reorg-per-project` → implementación → PR con `Refs #NNN` o `Closes #NNN` → gate CI verde → merge a `staging` → close del issue → borrado del worktree local → actualización del planning con motivo (HR-11). El commit directo a `staging` está prohibido para cambios de código.

> **HR-15.** Para cada pregunta del ciclo, una sola fuente es autoritativa; las demás son proyecciones. **Precedencia ante drift:** (a) GH Issue cerrado + CI verde + PR mergeado autoriza "¿está hecho?" — las tres condiciones se exigen simultáneas, no una sola; (b) observación engram con `topic_key=<cycle-id>/<gate>` gana sobre el roadmap cuando hay nota explícita (HR-13); (c) `docs/<project>/architecture/<topic-slug>.md` con estado `accepted` autoriza "¿por qué decidimos X?" pero sigue siendo **advisory para estado operativo** (snapshot pinned a SHA, jamás live authority); (d) `docs/<project>/roadmap.md` autoriza "¿en qué estado está y por qué?" y carga `motivo` por cada transición (HR-11), pero nunca autoriza "¿está hecho?". El roadmap es legible por humanos, **no por el agente**: el agente infiere estado solo del issue tracker y de engram, nunca del texto libre del roadmap.

> **HR-16.** Si una fila del roadmap vivo contradice el issue tracker, primero repro (re-leer el estado actual del issue desde GitHub) y luego actualizar el roadmap con `motivo` (HR-11). Nunca editar el roadmap sin repro. Si la contradicción es del roadmap, corregir; si es del issue tracker, escalarla al maintainer antes de tocar el roadmap.

> **HR-17.** Ante cualquier cambio de estado operacional de un item del ciclo que NO provenga de un commit al repo del proyecto — CI pasa de rojo a verde, CI runner reparado, dependencia externa cambia, infra recuperada, observación del cliente por canal externo, issue externo cambia, decisión de un stakeholder que no toca código, etc. — el agente DEBE: (a) emitir un commit `docs(roadmap)` con la cadena `motivo` correspondiente en la misma sesión donde detectó el cambio, sin esperar a que el usuario lo pida; (b) esperar el CI del propio commit antes de continuar; (c) NO emitir un `next_recommended` ni avanzar al siguiente paso del usuario (`/sdd-continue`, `/sdd-apply`, opciones múltiples sobre qué atacar, etc.) hasta que el commit `docs(roadmap)` haya pasado CI. La intuición: el roadmap es la **proyección viva** del estado del ciclo; cualquier evento — interno o externo, con commit o sin él — que mueva un item entre estados debe quedar registrado en el mismo turno, antes de proponer el siguiente paso. Caso conocido de violación: el agente repara el CI runner, CI pasa a verde, y en lugar de commitear `docs(roadmap)` con `motivo: CI verde tras fix del runner (Refs #NNN)` pregunta al usuario "¿qué atacamos?". El roadmap queda stale hasta que el usuario lo note y lo pida.

## Decision Gates

| Condición | Acción |
|---|---|
| La fuente de intake falta o es ilegible | Detener. Pedir al usuario que la proporcione. No inventar items. |
| El `cycle-id` ya tiene un roadmap vivo abierto | Reanudar leyendo el roadmap vivo actual. No crear duplicado. |
| Un item del intake está cubierto por una decisión ya aceptada | Citar el archivo de arquitectura por `<topic-slug>.md`. No crear un registro de decisión paralelo. |
| El ciclo entra en fase UAT | Pasar el testigo a la skill de UAT del proyecto. Esta skill solo monitoriza la firma. |
| Items verde sin UAT generada en su eje aplicable | Bloquear el avance a `uat_handoff`. Invocar `feature-acceptance-uat` antes. |
| UAT firma todos los ejes en verde | Archivar el roadmap vivo y los archivos de arquitectura del ciclo. Abrir uno nuevo en el siguiente intake. |
| Una decisión mid-sprint contradice una decisión previamente aceptada | Abrir un archivo nuevo con estado `superseded` para el previo. Nunca editar en silencio un archivo `accepted`. |
| Item sin etiquetas `origen` y `validador` | Bloquear clasificación antes de empezar la especificación. |
| El usuario pide una snapshot de gestión | Invocar la skill de snapshot del proyecto contra el roadmap vivo. No escribir la snapshot a mano. |
| Cambio de código sin worktree aislado | Detener. Crear worktree desde `origin/staging` siguiendo `worktree-reorg-per-project` antes de implementar. Sin PR no hay gate CI; sin worktree no hay rollback limpio. |
| Cambio de estado operacional sin commit `docs(roadmap)` previo (CI pasa a verde, runner reparado, infra recuperada, etc.) | Detener. Emitir commit `docs(roadmap)` con la cadena `motivo` correspondiente antes de avanzar al siguiente paso del usuario. El roadmap stale es violation de HR-17. |
| Roadmap contradice el estado operacional real (CI en verde pero la fila dice "pendiente CI verde") | Re-leer el estado desde el issue tracker y desde CI, luego emitir commit `docs(roadmap)` correctivo con `motivo` explícito (HR-11 + HR-17). |

## Execution Steps

### 0 Compuerta de intake

Validar la fuente de intake en cualquier formato (ver `references/intake-source-formats.md` para los más comunes). Guardar una copia inmutable en el repositorio documental del proyecto. Extraer items. Etiquetar cada item en los dos ejes (`origen`, `validador`). El gate de intake produce clasificaciones + observaciones + roadmap vivo; el código va en gates posteriores (`mid_sprint`). El intake puede cerrarse sin producir código.

### 1 Apertura de ciclo

Asignar `cycle-id`. Registrar `topic_key` engram con la observación de intake. Crear el roadmap vivo en `docs/<project>/roadmap.md` a partir de `assets/roadmap.template.md`. Pinear la observación en engram.

### 2 Bucle de decisiones

En cada decisión irreversible, escribir el archivo en `docs/<project>/architecture/<topic-slug>.md` con su rationale. Referenciar el archivo desde el item afectado en el roadmap vivo (HR-5). No esperar al merge para escribirlo.

### 3 Mid-sprint

Actualizar el roadmap vivo en cada commit que afecte a un item, **y ante cada cambio de estado operacional** que no provenga de un commit (HR-17): CI pasa de rojo a verde, runner reparado, infra recuperada, dependencia externa cambia, observación del cliente por canal externo, etc. En todos los casos, emitir un commit `docs(roadmap)` con la cadena `motivo` (HR-11) en la misma sesión donde se detecta el cambio, sin esperar a que el usuario lo pida. Conforme cada item pasa a verde, invocar `feature-acceptance-uat` para acumular el item en la acceptance web del ciclo (HR-8); la skill de UAT genera los criterios DADO/CUANDO/ENTONCES y los `pasos` reproducibles por item. Usar la skill de snapshot del proyecto para informes periódicos de gestión; la snapshot se archiva en `archive/<cycle-id>-<YYYY-MM-DD>.<formato-de-snapshot>` (HR-7, formato definido por la skill de snapshot del proyecto).

### 4 Handoff a UAT

Durante la compuerta `mid_sprint`, conforme cada item pasa a verde, invocar `feature-acceptance-uat` (o la equivalente del proyecto) para acumular la acceptance web. Para cada item: (1) clasificar en `validador` + `origen`; (2) añadir al web acumulado los criterios DADO/CUANDO/ENTONCES y `pasos`; (3) recoger firma del item (por item o por batch al cierre). Al cerrar `mid_sprint`, invocar `feature-acceptance-uat` con `audience:"usuario"` y o `audience:"desarrollo"` para presentar la web acumulada al firmante. Esta skill monitoriza la firma, la archiva en el ledger del capability doc §5, y la entrelaza en el roadmap al cerrar la compuerta `uat_handoff` (HR-8).

### 5 Archivado

En la firma de UAT, congelar el roadmap vivo y los archivos de arquitectura del ciclo a `archive/<cycle-id>-final-<YYYY-MM-DD>.md` y `archive/<cycle-id>/architecture/` respectivamente. Abrir un roadmap vivo nuevo en el siguiente intake. Los archivos archivados son inmutables (HR-4).

## Output Contract

| Key | Tipo | Descripción |
|---|---|---|
| `status` | `success \| blocked \| failed` | Resultado de la fase de la skill. |
| `cycle_id` | string | Identificador estable del ciclo activo. |
| `topic_key` | string | Ancla engram del ciclo activo (formato `<cycle-id>/<gate>`). |
| `living_roadmap_path` | path | Ruta absoluta al roadmap vivo Markdown. |
| `architecture_dir` | path | Ruta absoluta a `docs/<project>/architecture/` del ciclo. |
| `intake_source_path` | path \| null | Ruta a la fuente de intake persistida, o null si el usuario declinó. |
| `items` | array | Items del ciclo, cada uno con `id`, `title`, `origin`, `validator`, `status`, `motivo`, `decision_refs` (paths), `issue_refs`, `last_move`. |
| `decisions_log` | array | `<topic-slug>.md` de los archivos de arquitectura tocados en este ciclo. |
| `snapshots_taken` | array | Rutas a snapshots puntuales en `archive/`. |
| `next_recommended` | string | Acción recomendada al usuario en esta compuerta. |
| `gate` | enum | `intake \| mid_sprint \| uat_handoff \| uat_signed_off \| archived`. |
| `risks` | array | Riesgos abiertos del ciclo. |
| `skill_resolution` | enum | `paths-injected \| fallback-registry \| none`. |

Devolver todas las keys, incluso cuando el valor es array vacío, null o `"none"`.

## Anti-patterns

| Síntoma | Fix |
|---|---|
| Roadmap vivo creado sin `topic_key` en engram | Añadir la observación engram; sin ella, el roadmap es indetectable entre sesiones. |
| Decisión escrita tras el merge | Rechazar el merge sin archivo de arquitectura. La decisión retroactiva no es válida. |
| Snapshot editada a mano para "corregir" el roadmap vivo | Regenerar la snapshot desde el roadmap vivo. La snapshot es derivada, no autoritativa. |
| Item sin etiquetas `origin` y `validator` | Bloquear la clasificación antes de empezar la especificación. |
| Roadmap vivo editado tras archivarlo | Abrir un roadmap vivo nuevo para el siguiente ciclo. Los archivados son inmutables. |
| Numeración estilo `adr-NNNN-...md` | Usar `<topic-slug>.md`. La gente busca decisiones por tema, no por orden cronológico. |
| `cycle-id` reutilizado entre intakes con items no relacionados | Forzar un `cycle-id` nuevo. Un ciclo = un conjunto coherente de items. |
| Items del intake perdidos entre sesiones | Toda sesión empieza por `mem_search query="topic_key=<cycle-id>"`. La recuperación es obligatoria. |
| Decisiones tomadas en chat que nunca llegan a archivo de arquitectura | Cerrar el ciclo solo cuando todas las decisiones tienen su archivo escrito. |
| Snapshot de gestión con HTML inline del roadmap | Usar la skill de snapshot del proyecto contra el roadmap Markdown; nunca duplicar el formato. |
| Commit directo a `staging` para cambio de código | Abrir issue (o vincular al id del acta) → crear worktree dedicado → PR con CI → merge → close → borrar worktree → actualizar planning con motivo (HR-11). HR-14. |
| Cambio de estado operacional registrado tarde | El agentee repara el CI runner o cierra un issue externo y no emite commit `docs(roadmap)` con la cadena `motivo` en el mismo turno. El roadmap queda stale hasta que el usuario lo nota. | Emitir commit `docs(roadmap)` con `motivo` en la misma sesión donde se detecta el cambio operacional, antes de proponer el siguiente paso. HR-17. |
| Roadmap contradice el estado real después de un fix operacional | El agentee commitea el fix y deja la fila del item con la cadena `motivo` previa, sin actualizarla al nuevo estado. | Después de cualquier commit operacional que mueva un item entre estados, abrir el roadmap, actualizar la fila afectada con la cadena `motivo` nueva y emitir commit `docs(roadmap)` antes de avanzar. HR-11 + HR-17. |

## Files

| Archivo | Propósito |
|---|---|
| `assets/roadmap.template.md` | Plantilla del roadmap vivo Markdown. Replicar a `docs/<project>/roadmap.md` al abrir el primer ciclo. Inspirada en `docs/community-roadmap.md` del repo de Gentleman-Programming. |
| `assets/architecture-decision.template.md` | Esqueleto de decisión arquitectónica. Replicar a `docs/<project>/architecture/<topic-slug>.md` por cada decisión irreversible. |
| `references/cycle-checklist.md` | Checklists operativas por compuerta (intake, mid-sprint, UAT handoff, UAT firmado, archivado). |
| `references/intake-source-formats.md` | Cómo extraer items de cada formato de intake (lista no cerrada; ver intro del archivo). |

## Companion skills

| Skill | Cargar junto cuando |
|---|---|
| `documentation-alan-style` | La skill rige el contenido humano. Esta skill es su consumer técnico. |
| `estado-planificacion-update` | Mecánica de snapshots puntuales de gestión (HTML). Complementa, no sustituye: esta skill es Markdown; esa es HTML. |
| `feature-acceptance-uat` | Cierre de cada compuerta `mid_sprint` (HR-8). Genera webs `usuario`/`desarrollo`; este arnés NO duplica criterios. Si el proyecto usa otra skill de UAT, sustituir. |
| `sdd-*` | Cuando un item del ciclo requiere flujo SDD completo (proposal → spec → design → tasks → apply → verify → archive). |
| `engram-protocol` | Siempre. La disciplina de `topic_key` y `mem_session_summary` vive en engram. |
| `skill-style-guide` | Al auditar o extender esta skill. |
| `worktree-reorg-per-project` | Cada cambio de código abre un worktree aislado (HR-14). Esta skill es el contrato del layout `main` + `<project>-worktrees/<wt>/`. |

## Referencias externas

- `https://github.com/Gentleman-Programming/gentle-ai/blob/main/docs/community-roadmap.md` — el modelo de roadmap como mapa, no como state tracker.
- `https://github.com/Gentleman-Programming/gentle-ai/tree/main/docs/architecture` — el patrón de decisiones arquitectónicas como archivos planos por tema.
- `https://github.com/Gentleman-Programming/gentle-ai/blob/main/docs/architecture.md` — el overview que enlaza el roadmap con la arquitectura.

## Self-compliance

Esta skill cumple su propio rubric:

- Frontmatter declara los seis campos obligatorios (`name`, `description`, `license`, `metadata.author`, `metadata.version`, `metadata.last_verified`).
- `description` arranca con `Trigger:` y mezcla keywords razonables para discovery.
- 14 HR-N numeradas con verbos observables.
- Decision Gates en tabla.
- Anti-patterns en tabla.
- Output Contract con tabla de keys.
- Body budget target ≤ 450 líneas.
- Castellano peninsular formal, 3ª persona, usted.
- Cross-references via paths relativos en lugar de numeración rígida.

Verificación mecánica:

```bash
wc -l SKILL.md
grep -cE 'HR-[0-9]+' SKILL.md
grep -q 'Trigger:' <(head -3 SKILL.md)
```

Esta skill es agnóstica del proyecto concreto: cubre cualquier trabajo con ciclo intake → dev → UAT → archive, sea VBA, web, infraestructura o producto.