---
name: skill-propagation
description: Trigger: propagación de skills, refrescar enlaces, reconciliar skills, hook posterior al commit, graduar skill, catálogo de skills, overlays de prosa, markers user-supplement:bootstrap, inyección en AGENTS.md o CLAUDE.md por agente. Codifica la fuente canónica, el ownership por destino, la reconciliación transaccional, los overlays de prosa y el gate de graduación de personal-skills.
license: MIT
metadata:
  author: ardelperal
  version: 0.3
  last_verified: 2026-09-14
  scope: ['universal', 'ops']
  auto_invoke: ['adding or moving a skill', 'running the reconciler']
  tiers: ['universal', 'ops']
---



# skill-propagation

Política LLM-first que codifica cómo se propagan las skills entre `personal-skills/` y los cinco destinos compartidos del sistema, y cómo se propagan los overlays de prosa a los archivos de instrucciones de cada agente (AGENTS.md / CLAUDE.md). Esta skill describe el contrato; el ejecutor real sigue siendo `testing/suites/refresh-personal-symlinks/refresh-personal-symlinks.sh` y el disparador real sigue siendo el hook `post-commit`. Ninguna lógica nueva vive en la skill.

---

## §1 Activación

Cargue esta skill cuando:

- Decida dónde debe vivir una skill nueva (semilla de proyecto, autoría personal o catálogo).
- Necesite entender por qué un symlink no se crea, queda huérfano o se rompe tras un commit.
- Vaya a promover una skill de `personal/ardelperal/` al catálogo `skills/`.
- Audite la coherencia entre los cinco destinos compartidos.
- Configure el hook `post-commit` en un nuevo clon de `personal-skills/`.
- Resuelva una disputa sobre cuál es el directorio canónico de skills.
- Vaya a crear o actualizar un overlay de prosa en el AGENTS.md o CLAUDE.md de un agente.
- Audite qué contenido de un AGENTS.md es gestionado por overlays, por gentle-ai o por dysflow.

No use esta skill para:

- Decidir el contenido técnico de una skill individual (eso es `skill-creator`).
- Auditar la calidad del cuerpo de una skill (eso es `skill-improver`).
- Refrescar el catálogo `.atl/skill-registry.md` (eso es `skill-registry`).
- Escribir la skill que será propagada (eso es la skill del dominio concreto).

---

## §2 Hard Rules

- **HR-1** — El repositorio `personal-skills/` MUST ser la única fuente canónica de skills. Dos subáreas son válidas: `personal-skills/skills/` (catálogo) y `personal-skills/personal/ardelperal/` (autoría). La ruta legacy `C:\Proyectos\skills\skills\` MUST NOT participar del contrato de propagación.
- **HR-2** — El ciclo de vida MUST seguir la dirección `semilla de proyecto → personal/ardelperal/ → skills/`. Una skill fresca MAY omitir la etapa de semilla; una vez en `personal/ardelperal/`, la promoción al catálogo MUST pasar el gate de graduación definido en HR-4.
- **HR-3** — El hook `post-commit` del repo `personal-skills/` MUST invocar `testing/suites/refresh-personal-symlinks/refresh-personal-symlinks.sh`. El script MUST aplicar preflight, lock, journal, rollback y publicación atómica del manifest. Ningún otro mecanismo MUST duplicar esa lógica.
- **HR-4** — Una skill en `personal/ardelperal/` MUST NOT graduarse a `skills/` salvo que las tres condiciones se cumplan simultáneamente: (a) calidad — pasa la auditoría de `skill-improver` con `status: "success"` y `failed_checks: []`; (b) estabilidad — sin ediciones materiales en los últimos catorce días naturales; (c) reuso — `grep -rIn "<nombre-skill>" C:\00repos\codigo\` retorna al menos un hit. Una sola condición fallida MUST bloquear la promoción.
- **HR-5** — El cuerpo de esta skill MUST ser single-language Castellano peninsular. Las keywords del campo `description` del frontmatter pueden estar en Castellano o inglés; los headings, las reglas y el contrato MUST estar en Castellano. Mezclar ambos idiomas en una misma sección MUST rechazarse.
- **HR-6** — Toda ruta de filesystem MUST aparecer en su forma Linux (`~/.config/opencode/skills/`) y en su forma Windows (`%USERPROFILE%\.config\opencode\skills\`). Un HR-N MUST NOT listar una sola forma cuando la ruta sea estructural.
- **HR-7** — Esta skill MUST NOT duplicar la lógica del script `refresh-personal-symlinks.sh`. La skill describe el contrato; el bash ejecuta el contrato. Si una operación aparece en ambos sitios, MUST eliminarse de la skill y dejar el script como única fuente de verdad.
- **HR-8** — La promoción de graduación MUST ser human-gated. El script `assets/graduation-helper.sh` (creado en T-3) MUST evaluar las tres condiciones y emitir el veredicto PASS o FAIL con la razón; el operador humano MUST decidir si ejecuta el movimiento de carpeta y el bump de versión. El script MUST NOT mover archivos ni modificar frontmatter sin confirmación humana explícita.
- **HR-9** — La condición de reuso MUST evaluarse con `grep -rIn "<nombre-skill>" C:\00repos\codigo\`. Esta skill MUST NOT introducir consultas a codegraph, manifiestos auxiliares o índices externos para la detección de reuso. Determinismo y portabilidad son contrato.
- **HR-10** — El directorio `~/.agents/skills/` (`%USERPROFILE%\.agents\skills\`) MUST ser una carpeta real y es la única copia real gestionada por el reconciliador. Los cuatro destinos de enlaces MUST apuntar exactamente a `~/.agents/skills/<n>` (nunca directamente al repo `personal-skills/skills/`), salvo las seis skills de HR-11. Pi también escanea la copia real de `~/.agents/skills/`.
- **HR-11** — El reconciliador MUST reconocer como ownership externo de Dysflow `access-form-ui-builder` y las cinco `dysflow-*` publicadas. MUST verificar esas 6 skills junto con las skills personales del catálogo en los cinco destinos compartidos, pero MUST NOT sustituirlas, podarlas ni copiar el origen personal sobre ellas.
- **HR-12** — El catálogo compartido MUST publicarse mediante enlaces en OpenCode principal, OpenCode alternativo, Claude y Codex, más la copia real de HR-10. `~/.pi/agent/skills/` (`%USERPROFILE%\.pi\agent\skills\`) MUST quedar reservado para skills exclusivas de Pi y MUST NOT recibir el catálogo compartido. Las 50 entradas obsoletas existentes en esa ruta MUST NOT considerarse gestionadas ni eliminarse mediante `sync`; requieren una limpieza dedicada posterior.

  | # | Forma Linux | Forma Windows | Tipo | Notas |
  | --- | --- | --- | --- | --- |
  | 1 | `~/.config/opencode/skills/<n>` | `%USERPROFILE%\.config\opencode\skills\<n>` | SymbolicLink | OpenCode principal. |
  | 2 | `~/.opencode/skills/<n>` | `%USERPROFILE%\.opencode\skills\<n>` | SymbolicLink | Variante OpenCode. |
  | 3 | `~/.claude/skills/<n>` | `%USERPROFILE%\.claude\skills\<n>` | SymbolicLink | Claude Code. |
  | 4 | `~/.codex/skills/<n>` | `%USERPROFILE%\.codex\skills\<n>` | SymbolicLink | Codex CLI. |
  | 5 | `~/.agents/skills/<n>/` | `%USERPROFILE%\.agents\skills\<n>\` | **REAL FOLDER** | Excepción HR-10. |

  El detalle extendido de cada fila vive en `references/5-dir-mapping.md` (creado en T-2).

- **HR-13** — Los overlays de prosa viven en `agents/<agente>/overlays/*.md` (Linux: `~/personal-skills/agents/<agente>/overlays/`; Windows: `%USERPROFILE%\personal-skills\agents\<agente>\overlays\`). El reconciliador los inyecta en el archivo de instrucciones de cada agente entre el par de markers `<!-- user-supplement:bootstrap:NAME -->` ... `<!-- /user-supplement:bootstrap:NAME -->`, donde `NAME` es el basename del overlay sin extensión. La inyección MUST tocar únicamente el contenido dentro de ese par de markers. Los markers `gentle-ai:*` y `user-supplement:dysflow:*` pertenecen a otros runtimes y MUST NOT modificarse mediante este mecanismo ni manualmente.

  Cuando el origen del overlay desaparece del repo, la fase de prune MUST retirar el bloque propiedad completo: la línea del marker de apertura, todas las líneas de contenido entre ambos markers, la línea del marker de cierre y el final de línea (`\n` o `\r\n`) adosado a cada marker. Bytes fuera del tramo retirado MUST preservarse tal cual, incluido el BOM, las secuencias LF, CRLF o mixtas y los bloques adyacentes `gentle-ai:*` o `user-supplement:dysflow:*`. Tras un prune exitoso NO pueden quedar markers del par afectado en el archivo destino.

  Destinos de inyección por agente:

  | Agente | Forma Linux | Forma Windows |
  | --- | --- | --- |
  | opencode | `~/.config/opencode/AGENTS.md` | `%USERPROFILE%\.config\opencode\AGENTS.md` |
  | codex | `~/.codex/AGENTS.md` | `%USERPROFILE%\.codex\AGENTS.md` |
  | claude | `~/.claude/CLAUDE.md` | `%USERPROFILE%\.claude\CLAUDE.md` |
  | pi | `~/.pi/agent/AGENTS.md` | `%USERPROFILE%\.pi\agent\AGENTS.md` |

- **HR-14** — El reconciliador MUST NOT adoptar, snapshotizar ni podar ninguna entrada ausente de su manifest previo (`managed-skills.tsv`). Solo las filas que el propio reconciliador emitió en una corrida anterior son candidatas de poda. Cualquier carpeta o symlink instalado por otro runtime (p. ej. `go-testing`, `issue-creation` o `judgment-day` de gentle-ai) MUST permanecer intacto aunque coincida por nombre con una skill que alguna vez estuvo gestionada; el reconciliador MUST NOT inferir ownership por convención de nombre ni por presencia en los destinos.

- **HR-15** — Los backups transaccionales MUST preservar la identidad del artefacto: bytes para archivos regulares, árbol de directorios y modos para carpetas, y para symlinks tanto la identidad de enlace como el destino exacto que resuelven. Un symlink roto (destino inexistente) MUST snapshotizarse como registro de texto `<nombre>.dangling-link` con su destino exacto; el rollback lo recrea cuando el sistema lo permite y, si no, emite `WARN` con el destino sin abortar la restauración. Los symlinks outward MUST apuntar a `~/.agents/skills/<name>` y MUST NOT apuntar al repo fuente. Cada candidato se snapshotiza según su tipo antes de cualquier mutación de la Fase B; ningún reemplazo atómico se ejecuta si el snapshot no está verificado. La Fase A solo realiza snapshots; la Fase B aplica mutaciones; un fallo de Fase B restaura en orden inverso estricto y el manifiesto previo permanece autoritativo (`mv -f tmp -> manifest` se ejecuta solo tras el éxito completo de Fase B).

---

## §3 Decision Gates

| Condición | Acción |
| --- | --- |
| Si la ruta canónica propuesta es `C:\Proyectos\skills\skills/` | Detener. Esa ruta MUST NOT usarse. Migrar primero a `personal-skills/skills/` o a `personal-skills/personal/ardelperal/`. |
| Si la skill nace en un repo de proyecto y debe entrar al catálogo | Promover primero a `personal/ardelperal/`. Una semilla MAY saltarse `personal/ardelperal/` solo si cumple HR-4 desde el primer commit. |
| Si las tres condiciones de HR-4 pasan | Operador humano ejecuta manualmente: mover la carpeta, bumpear `metadata.version` a `"1.0"`, ejecutar `refresh-personal-symlinks.sh full`. |
| Si el veredicto del helper es FAIL por `quality_failed` | Iterar la skill con `skill-improver` hasta `status: "success"` antes de reintentar el gate. |
| Si el veredicto del helper es FAIL por `stability_failed` | Esperar a que la skill cumpla los catorce días naturales desde la última edición material antes de reintentar. |
| Si el veredicto del helper es FAIL por `reuse_failed` | Documentar el uso en al menos un repo de proyecto, o reevaluar si la skill merece el catálogo. |
| Si un enlace gestionado quedó huérfano tras borrar una skill | Ejecutar `refresh-personal-symlinks.sh prune`; el elemento se mueve al backup transaccional. |
| Si falta una skill con ownership Dysflow | Detener antes de mutar. Reparar primero mediante Dysflow. |
| Si el directorio `~/.agents/skills/` se necesita como symlink | Detener. La excepción HR-10 es no negociable; symlinks fallan en runtime en esa ruta. |
| Si el cuerpo de una sección mezcla Castellano e inglés en prosa | Partir en dos secciones o reescribir en Castellano peninsular. Single-language es contrato (HR-5). |
| Si un bloque gestionado por overlays debe crearse o actualizarse | Editar `agents/<agente>/overlays/<name>.md` en el repo y ejecutar `refresh-personal-symlinks.sh overlays`. Nunca editar el marker gestionado directamente en el archivo destino. |
| Si el contenido a actualizar está dentro de markers `gentle-ai:*` o `user-supplement:dysflow:*` | Detener. Esos markers pertenecen a otros runtimes; el reconciliador no los toca y la edición manual también está prohibida (HR-13). |
| Si el contenido de un AGENTS.md está fuera de todo marker gestionado | Es contenido manual del archivo destino; edítelo directamente sin pasarlo por overlays. |
| Si `sync` deja huérfanos en `~/.config/opencode/skills/`, `~/.opencode/skills/`, `~/.claude/skills/` o `~/.codex/skills/` | Ejecutar `refresh-personal-symlinks.sh prune`; la fila del manifest v2 o v3 correspondiente dirige el backup transaccional y la limpieza (HR-13, HR-15). |
| Si un marker `<!-- user-supplement:bootstrap:NAME -->` queda en un AGENTS.md destino tras un prune | El reconcile falló HR-13. Inspeccionar `apply_overlay_removal` y re-ejecutar `sync`; el bloque propiedad completo (markers + contenido + finales de línea) debe desaparecer. |
| Si una entrada instalada por otro runtime (p. ej. gentle-ai) no aparece en el manifest previo | No tocarla. HR-14 prohíbe adoptar, snapshotizar o podar cualquier entrada ausente del manifest previo, sin importar el nombre. |
| Si la Fase A o la Fase B fallan a mitad de prune | El reconciliador restaura cada mutación aplicada en orden inverso estricto y conserva el manifest anterior como autoritativo. Inspeccionar el journal y re-ejecutar tras reparar la causa raíz; nunca usar `mv -f` fuera del helper `apply_overlay_removal`. |

---

## §4 Execution Steps

1. **Resolver el directorio canónico.** Toda decisión de propagación parte de `personal-skills/` (Linux: `~/personal-skills/`; Windows: `C:\Users\adm1\personal-skills\`). Si el origen propuesto es `C:\Proyectos\skills\skills/`, migrar primero. La migración es prerrequisito.
2. **Clasificar la skill en el ciclo de vida.** Identifique la etapa actual (`seedbed`, `authorship`, `catalog`) consultando el campo `metadata.version`. Versiones `0.x` indican autoría; `"1.0"` indica catálogo. Si no existe frontmatter, es semilla.
3. **Vincular el hook `post-commit`.** Verifique que `.git/hooks/post-commit` invoque únicamente `testing/suites/refresh-personal-symlinks/refresh-personal-symlinks.sh sync`. Si el hook no existe o contiene otra automatización, sustitúyalo por ese wrapper mínimo.
4. **Reconciliar los cinco destinos compartidos.** Tras cada commit, el hook ejecuta `sync`. Para una reparación integral, ejecute `full`. Para retirar huérfanos gestionados, ejecute `prune`. La semántica y el ownership viven en `references/5-dir-mapping.md`. Ningún modo limpia las entradas obsoletas de Pi descritas en HR-12. Para previsualizar mutaciones sin aplicarlas, agregue el flag `--dry-run` a cualquier modo (`bash refresh-personal-symlinks.sh sync --dry-run`); el reconciliador imprime cada `COPY`, `CREATE LINK`, `OVERLAY`, `BACKUP` y `WRITE MANIFEST` que realizaría, no toca los cinco destinos ni crea manifest ni backups, y sale con código 1 si detecta un conflicto que bloquearía la ejecución real.
5. **Propagar los overlays de prosa.** Para crear o actualizar un bloque en el AGENTS.md/CLAUDE.md de un agente, edite `agents/<agente>/overlays/<name>.md` y ejecute `refresh-personal-symlinks.sh overlays`. La acción es idempotente y transaccional (backup y rollback por run) y solo toca el contenido dentro del par de markers `<!-- user-supplement:bootstrap:NAME -->`. Los destinos por agente viven en HR-13.
6. **Evaluar el gate de graduación.** Antes de promover una skill desde `personal/ardelperal/` al catálogo `skills/`, ejecute `assets/graduation-helper.sh <nombre-skill>` (creado en T-3). El script evalúa las tres condiciones de HR-4 e imprime PASS o FAIL con la razón. No continúe si el veredicto es FAIL.
7. **Ejecutar la graduación.** Tras un veredicto PASS, el operador humano mueve la carpeta a `skills/<nombre>/`, actualiza `metadata.version` a `"1.0"` y ejecuta `refresh-personal-symlinks.sh full`.
8. **Refrescar el registro.** Tras añadir, mover o bumpear una skill, invoque la skill `skill-registry` para regenerar `.atl/skill-registry.md`. La fila de la skill en el registro MUST reflejar su nueva ruta y su nueva versión.
9. **Persistir el progreso.** Si la propagación es parte de un flujo SDD, persista el progreso en engram con `topic_key: sdd/skill-propagation/apply-progress` antes de retornar al orquestador.

---

## §5 Output Contract

Toda llamada a esta skill MUST retornar un objeto con las siete claves siguientes. La ausencia de una clave es violación de contrato (HR-9 de `skill-style-guide`).

| Key | Tipo | Descripción |
| --- | --- | --- |
| `status` | `"success" \| "blocked" \| "failed"` | Resultado de la fase de propagación evaluada. |
| `propagation_mode` | `"seedbed" \| "authorship" \| "catalog"` | Etapa del ciclo de vida en la que se encuentra la skill inspeccionada. |
| `affected_dirs` | string[] con anotación | Cinco destinos compartidos con tipo y owner. `~/.agents/skills/` lleva `real_folder: true`; las skills externas llevan `owner: dysflow`. |
| `graduation_eligible` | boolean | `true` si y solo si las tres condiciones de HR-4 pasan simultáneamente. |
| `graduation_reason` | `"all_pass" \| "quality_failed" \| "stability_failed" \| "reuse_failed" \| "none"` | Razón cuando `graduation_eligible` es `false`; `"all_pass"` cuando es `true`; `"none"` cuando no se evaluó gate. |
| `next_recommended` | `"commit" \| "promote" \| "graduate" \| "none"` | Siguiente acción recomendada del ciclo de vida: `commit` para cambios listos, `promote` para mover de semilla a autoría, `graduate` para pasar el gate y mover al catálogo, `none` cuando no aplica. |
| `paths` | object | Pares Linux + Windows de las rutas canónicas involucradas: `home`, `canonical_source`, `agents_global`. Cada par MUST contener ambas formas. |

---

## §6 Anti-patterns

| Síntoma | Fix |
| --- | --- |
| Una sección referencia `C:\Proyectos\skills\skills/` como canónica | Reescribir para usar `personal-skills/skills/` o `personal-skills/personal/ardelperal/`. La ruta legacy MUST NOT participar. |
| El hook `post-commit` ejecuta lógica nueva además de invocar el script | Mover toda lógica al script. El hook MUST ser un wrapper mínimo de una línea. |
| La skill duplica las opciones `sync/full/prune` con descripciones distintas de las del script | Citar el comportamiento del script por referencia, no reescribirlo. La skill MUST NOT parafrasear la lógica del bash. |
| El veredicto de graduación se ejecuta automáticamente sin acción humana | Mantener al operador humano en el loop. El helper MUST ser asesor, no actor. |
| La condición de reuso se evalúa con una consulta a codegraph | Sustituir por `grep -rIn "<nombre>" C:\00repos\codigo\`. Determinismo sobre inteligencia. |
| Una skill mezcla Castellano e inglés en una misma sección HR-N | Reescribir la sección en Castellano peninsular o dividirla. Single-language es contrato (HR-5). |
| Se omite la forma Windows de una ruta listada en HR-N | Añadir la forma Windows como segunda columna o segunda fila. Dual form es contrato (HR-6). |
| El catálogo `.atl/skill-registry.md` no se regenera tras un movimiento | Invocar `skill-registry` antes de cerrar la fase. El registro MUST reflejar la ruta y la versión nuevas. |
| Se crea un symlink hacia `~/.agents/skills/` | Detener. La excepción HR-10 exige carpeta real con archivos reales. |
| Se publica el catálogo compartido en `~/.pi/agent/skills/` | Detener. HR-12 reserva esa ruta para skills exclusivas de Pi. |
| Se espera que `sync` retire las 50 entradas obsoletas de Pi | Ejecutar una limpieza dedicada posterior; la ruta ya no está gestionada. |
| Se sustituye una skill administrada por Dysflow | Detener y restaurar. El reconciliador solo verifica su disponibilidad. |
| El campo `description` mezcla keywords Castellano e inglés | Elegir un solo idioma. Castellano es el contrato de esta skill. |
| Se edita a mano el contenido dentro de `<!-- user-supplement:bootstrap:* -->` en un AGENTS.md destino | Editar el overlay en `agents/<agente>/overlays/<name>.md` y re-propagar con `refresh-personal-symlinks.sh overlays`; la edición manual directa se pierde en la siguiente propagación. |
| Se edita o elimina contenido dentro de markers `gentle-ai:*` o `user-supplement:dysflow:*` | Detener. Esos markers pertenecen a otros runtimes (HR-13). |
| Tras un prune de overlay quedan markers `<!-- user-supplement:bootstrap:NAME -->` huérfanos en el destino | El reconcile falla HR-13: el bloque propiedad completo (markers + contenido + finales de línea) MUST haber sido retirado. Verificar la versión del helper Python de remoción y re-ejecutar `sync`. |
| El script publica un `migration-meta` en el manifest v3 | Detener. El manifest v3 contiene solo la cabecera `version<TAB>3` y filas con tres formas exactas; cualquier fila extra es violación de contrato. Eliminar la fila por script auxiliar y re-ejecutar `sync`. |
| Se ejecuta `sync` dos veces seguidas y la segunda corrida añade filas o mueve archivos | Detener. `sync` MUST ser idempotente byte-a-byte; dos corridas consecutivas deben dejar el estado idéntico. Capturar el diff con `find ... -printf '%P\|%y\|%l'` y revisar el orden del pipeline (`reconcile` antes de `prune`). |
| Se aplica `rm -rf` directo sobre un candidato de prune fuera del pipeline transaccional | Sustituir por `move_to_backup`; el reconciliador registra cada mutación en el journal para que un fallo restaure en orden inverso. `rm -rf` rompe la garantía HR-15. |
| El snapshot de un symlink guardado en backup deja de ser symlink (aparece como archivo copiado) | El helper de snapshot MUST usar `cp -P` para preservar la identidad del enlace y el destino. Si el destino era `~/.agents/skills/<name>`, el snapshot MUST resolver al mismo target y MUST NOT apuntar al repo fuente. |
| Se poda o adopta una entrada ausente del manifest previo | Detener. HR-14 limita la poda a filas que el reconciliador emitió en una corrida anterior; una entrada instalada por otro runtime MUST permanecer intacta sin importar coincidencia de nombre. |

---

## §7 Companion skills

| Skill | Cargar junto cuando |
| --- | --- |
| `skill-style-guide` | Se audite el formato de cualquier `SKILL.md` del catálogo, incluido este. Es el rubric que fija el frontmatter, las secciones canónicas y el Output Contract. |
| `skill-improver` | Se ejecute la condición de calidad del gate de graduación (HR-4.a). Audita una skill existente y emite `status: "success"` o lista `failed_checks`. |
| `skill-registry` | Se haya añadido, movido o bumpeado una skill. Regenera `.atl/skill-registry.md` para reflejar el cambio. |
| `skill-creator` | Se escriba una skill desde cero. Aplica el rubric de `skill-style-guide` durante la creación. |

---

> Esta skill codifica las cuatro decisiones base (Q1 fuente canónica, Q2 dirección del ciclo de vida, Q3 cadencia on-commit, Q4 gate de graduación) más cinco decisiones de diseño ratificadas (D1 single-language Castellano, D2 rutas duales, D3 bash como ejecutor sin duplicación, D4 gate human-gated con script asesor, D5 reuso por grep), el contrato de overlays de prosa con remoción completa del bloque (HR-13), el límite de poda al manifest previo sin adopción de entradas ajenas (HR-14) y los tipos de backup transaccional (HR-15). El ejecutor real sigue siendo `testing/suites/refresh-personal-symlinks/refresh-personal-symlinks.sh`; el disparador real sigue siendo `.git/hooks/post-commit`. La skill describe el contrato; el bash ejecuta el contrato.
