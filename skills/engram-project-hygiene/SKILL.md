---
name: engram-project-hygiene
description: Trigger: salud de sincronización engram, están sincronizadas mis memorias, auditar engram cloud, proyectos duplicados en engram, normalizar nombres de proyectos, proyectos fragmentados, reasignar proyecto al canónico, engram projects consolidate, proyectos enrolados vs allowlist, cuántas memorias no suben a cloud. Audita la salud de sincronización local↔cloud de Engram proyecto por proyecto y normaliza los nombres de proyecto fragmentados reasignándolos a su canónico enrolado, con backup consistente y escritura nativa por node:sqlite.
license: Apache-2.0
metadata:
  author: Andrés Román
  version: 1.0
  last_verified: 2026-08-31
  tested_on: Windows 11 + Node 26.4.0 (node:sqlite) + engram 1.20.0 + engram.db 267MB/WAL
  scope: ['engram', 'runtime']
  auto_invoke: ['auditing engram project state']
  tiers: ['engram', 'runtime']
---



## §1 Activation

Cargue esta skill cuando el usuario pida:

- Saber si sus memorias están realmente sincronizadas con engram cloud, proyecto por proyecto.
- Auditar cuánto dato local no llega al cloud y por qué.
- Detectar proyectos duplicados o fragmentados (`gentle-ai` vs `c:\00repos\codigo\gentle-ai`).
- Normalizar nombres de proyecto reasignando fragmentos a su canónico enrolado.
- Entender el desajuste entre `sync_enrolled_projects` y `ENGRAM_CLOUD_ALLOWED_PROJECTS`.

**Do NOT load when:**

- La cola de push está atascada por mutaciones inválidas y solo se busca desatascarla: eso es `engram-sync-doctor`.
- Se quiere guardar o buscar una memoria concreta: use las herramientas `mem_*` directamente.
- El problema es que el daemon no arranca: eso es `engram-sync-doctor` §Phase 1.

Esta skill es el **auditor y normalizador**. `engram-sync-doctor` es el **reparador de cola**. Se complementan; esta añade lo que aquella no cubre: normalización de nombres, escritura nativa sin WSL, y reparación en la tabla origen.

## §2 Hard Rules

- **HR-1** — NUNCA ejecute `engram projects consolidate --apply`. Ejecute siempre `--dry-run` primero y descarte su propuesta. Verificado 2026-08-31: propuso fusionar 36 proyectos NO relacionados dentro de `dysflow`, incluidos `expedientes` (1621 obs), `no_conformidades` (2437) y `gestion_riesgos` (2215). Su heurística de similitud colapsa el inventario entero en un grupo.
- **HR-2** — MUST reparar la tabla ORIGEN antes de podar `sync_mutations`. Engram re-encola desde `observations` / `sessions` / `user_prompts`; borrar solo la cola hace reaparecer el bloqueo con un `seq` nuevo.
- **HR-3** — MUST respaldar con `VACUUM INTO '<destino>'`, NUNCA con `cp` ni `Copy-Item`. La DB está en modo WAL y una copia de archivo no es consistente. MUST validar el backup con `PRAGMA integrity_check` antes de mutar.
- **HR-4** — MUST escribir con `node:sqlite` (`DatabaseSync`) contra la DB viva. MUST NO copiar la DB a WSL, mutarla y sobrescribir el archivo: otros agentes (`codex`, `opencode`, `claude`) mantienen `engram.db` abierta y el reemplazo de archivo produce `database disk image is malformed (11)`.
- **HR-5** — MUST parar únicamente los procesos cuyo `CommandLine` contiene `serve`. NUNCA pare los `engram mcp`: pertenecen a sesiones de otros agentes.
- **HR-6** — MUST actualizar el campo `$.project` del JSON en `sync_mutations.payload` junto con la columna `project`. Actualizar solo la columna envía el nombre viejo al cloud.
- **HR-7** — MUST NO escribir en `observations_fts` ni `prompts_fts`. Son FTS5 external-content mantenidas por los triggers `obs_fts_update` / `prompt_fts_update`; tocarlas a mano rompe la búsqueda.
- **HR-8** — MUST determinar el canónico por EVIDENCIA de contenido (sesiones, títulos, prompts), NUNCA por parecido de nombre. Verificado: `00_vba_toolkit_bench` contiene trabajo de `team-skills`, no de `vba_toolkit_bench`.
- **HR-9** — MUST NO modificar `ENGRAM_CLOUD_ALLOWED_PROJECTS` sin aprobación explícita del usuario. La allowlist es curación deliberada: hay proyectos retirados a propósito.
- **HR-10** — MUST NO usar `last_sync_at` de `GET /sync/status` como indicador de salud del autosync. Devuelve vacío aun con el autosync funcionando. Use `acked_at` reciente en `sync_mutations` sin sync manual previo.
- **HR-11** — MUST preguntar antes de borrar filas de `observations`, `sessions` o `user_prompts`. Solo proceda sin preguntar cuando la fila tenga contenido de longitud 0 y el usuario haya mandado reparar.
- **HR-12** — MUST NO confiar en el check `allowlist.collision` de `engram-sync-doctor/assets/diagnose.ps1`. Reporta `[OK]` con 1022 filas fuera de la allowlist. Calcule la colisión con la consulta de §4.

## §3 Decision Gates

| Condition | Action |
|---|---|
| El usuario pregunta "¿está sincronizado?" | Corra `assets/audit.mjs` (read-only) y reporte la tabla. No mute nada. |
| `sync_state.cloud` en `degraded` con fallos | Es reparación de cola: derive a `engram-sync-doctor`, o aplique §4 paso 5. |
| Hay proyectos con nombre de ruta (`c:\...`) | Candidatos a normalización. Clasifique por evidencia (§4 paso 3). |
| El fragmento tiene canónico ENROLADO | Reasigne (§4 paso 4). Efecto inmediato: empieza a sincronizar. |
| El fragmento NO tiene canónico enrolado | Reporte y PARE. Consolidar no lo hace sincronizar; requiere decisión de allowlist. |
| El contenido no coincide con el nombre | NO reasigne por nombre. Reporte el conflicto al usuario y pare. |
| El proyecto es un cubo mezclado (varios proyectos dentro) | NO renombre en bloque. Reporte que requiere troceo por sesión. |
| `enrolled` > `allowlist` | Reporte el volumen bloqueado y PARE. La allowlist la edita el usuario. |
| El daemon reporta estado distinto al de `sync_state` | Estado cacheado en memoria: reinicie el daemon (HR-5). |

## §4 Execution Steps

1. **Inventariar** — Corra `assets/audit.mjs`. Es read-only y produce el Output Contract completo: cola por proyecto, gaps `last_enqueued_seq` vs `last_acked_seq`, mutaciones inválidas, enrolados vs allowlist, y grupos candidatos a normalización.

2. **Medir el bloqueo real** — Contraste `sync_enrolled_projects` contra `ENGRAM_CLOUD_ALLOWED_PROJECTS`:

   ```sql
   SELECT project, COUNT(*) c FROM sync_mutations
    WHERE acked_at IS NULL AND project NOT IN (<allowlist>)
    GROUP BY project ORDER BY c DESC;
   ```

   Reporte obs + prompts + sesiones de cada proyecto enrolado pero bloqueado. Ese es el dato que el usuario necesita para decidir la allowlist.

3. **Clasificar por evidencia** — Para cada candidato, lea su contenido antes de proponer canónico:

   ```sql
   SELECT id FROM sessions WHERE project = ? LIMIT 5;
   SELECT title FROM observations WHERE project = ? AND title <> '' LIMIT 3;
   SELECT substr(content,1,90) FROM user_prompts WHERE project = ? AND content <> '' LIMIT 2;
   ```

   Clasifique en: (a) canónico enrolado identificado, (b) canónico no enrolado, (c) cubo mezclado, (d) conflicto nombre/contenido. Solo (a) procede sin más preguntas.

4. **Normalizar** — Con el mapeo confirmado, respalde (HR-3) y actualice dentro de UNA transacción `BEGIN IMMEDIATE`:

   - Columna `project` en: `observations`, `sessions`, `user_prompts`, `prompt_tombstones`, `cloud_upgrade_state`.
   - En `sync_mutations`: la columna Y el payload, con `json_set(payload,'$.project', <canonico>)` (HR-6).
   - NUNCA `observations_fts` ni `prompts_fts` (HR-7).
   - NUNCA `sync_enrolled_projects` (es registro de enrolamiento, no datos).

   Cierre con `PRAGMA integrity_check` y verifique que el fragmento queda a 0 filas en todas las tablas.

   Patrón de escritura que cumple HR-3, HR-4 y HR-6:

   ```js
   import { DatabaseSync } from "node:sqlite";
   const db = new DatabaseSync("C:/Users/<user>/.engram/engram.db");

   // HR-3: backup consistente ANTES de mutar (nunca cp sobre una DB en WAL)
   db.exec(`VACUUM INTO '${backupPath}'`);

   db.exec("BEGIN IMMEDIATE");
   try {
     for (const t of ["observations", "sessions", "user_prompts",
                      "prompt_tombstones", "cloud_upgrade_state"]) {
       db.prepare(`UPDATE ${t} SET project = ? WHERE project = ?`).run(canonico, fragmento);
     }
     // HR-6: la columna Y el project embebido en el payload JSON
     db.prepare(`UPDATE sync_mutations
                    SET project = ?,
                        payload = CASE WHEN json_valid(payload)
                                    AND json_extract(payload,'$.project') IS NOT NULL
                                  THEN json_set(payload,'$.project', ?) ELSE payload END
                  WHERE project = ?`).run(canonico, canonico, fragmento);
     db.exec("COMMIT");
   } catch (e) {
     db.exec("ROLLBACK");
     throw e;
   }
   ```

5. **Desbloquear la cola si procede** — Si el push falla, identifique la clase por el código HTTP:

   | Error del cloud | Causa | Reparación |
   |---|---|---|
   | `500 ... prompt payload content is required` | Fila en `user_prompts` con `content=''` | Borre el ORIGEN con `engram delete prompt <id NUMÉRICO>`, luego la cola (HR-2) |
   | `400 mutation entries must specify a project` | Mutación con `project=''` | Verifique el origen; si ya está corregido, la fila en cola es una foto vieja: bórrela |
   | `entity='relation'` en cola | El esquema cloud no acepta relations | Borre esas filas de `sync_mutations` |

6. **Sincronizar y verificar** — `engram sync --cloud --project <P>` por cada proyecto de la allowlist. Verifique: 0 gaps, 0 pendientes, 0 inválidas, `sync_state.cloud` healthy, `engram doctor` en `ok`, `integrity_check` ok.

7. **Confirmar el autosync** — No mire `last_sync_at` (HR-10). Guarde una memoria, espere un ciclo (~5-6 min) y compruebe que su mutación queda `acked` sin sync manual:

   ```sql
   SELECT seq, entity, acked_at FROM sync_mutations
    WHERE project = ? AND acked_at IS NOT NULL ORDER BY seq DESC LIMIT 5;
   ```

## §5 Output Contract

Retorne un objeto con TODAS estas keys, incluso vacías:

| Key | Type | Description |
|---|---|---|
| `status` | `"success" \| "blocked" \| "failed"` | Resultado de la auditoría o normalización. |
| `mode` | `"audit" \| "normalize"` | Read-only, o auditoría más reasignación. |
| `enrolled_count` | number | Filas en `sync_enrolled_projects`. |
| `allowlist_count` | number | Entradas en `ENGRAM_CLOUD_ALLOWED_PROJECTS`. |
| `allowlisted_in_sync` | number | Proyectos de la allowlist con gap 0 y 0 pendientes. |
| `allowlisted_with_gap` | string[] | Proyectos de la allowlist con `last_enqueued_seq` != `last_acked_seq`. |
| `blocked_projects` | object[] | `{project, obs, prompts, sessions}` enrolados pero fuera de la allowlist. |
| `blocked_totals` | object | `{projects, obs, prompts, sessions}` agregados del bloqueo. |
| `invalid_mutations` | number | Mutaciones pendientes que el cloud rechazará. |
| `invalid_breakdown` | object[] | `{project, entity, reason, count}` por clase de invalidez. |
| `normalization_groups` | object[] | `{fragment, canonical, enrolled, evidence, rows}` candidatos. |
| `reassigned` | object[] | `{fragment, canonical, rows}` efectivamente movidos. Vacío en modo audit. |
| `backup_path` | string \| null | Ruta del backup `VACUUM INTO`, o null si no se mutó. |
| `integrity_check` | `"ok" \| string` | Resultado del `PRAGMA integrity_check` final. |
| `daemon_phase` | string | `phase` reportado por el daemon. |
| `autosync_verified` | boolean | `true` solo si se observó un `acked_at` sin sync manual. |
| `requires_user_decision` | string[] | Decisiones que la skill NO puede tomar (allowlist, cubos mezclados, conflictos). |
| `next_recommended` | `"edit_allowlist" \| "split_mixed_buckets" \| "run_sync_doctor" \| "none"` | Siguiente acción. |
| `risks` | string[] | Riesgos abiertos detectados. |

## §6 Anti-patterns

| Symptom | Fix |
|---|---|
| Ejecutar `engram projects consolidate --apply` para normalizar | NUNCA. Fusiona proyectos no relacionados. Mapee a mano tras un `--dry-run` descartado (HR-1). |
| Borrar filas de `sync_mutations` y ver el bloqueo reaparecer con otro `seq` | Se reparó la cola y no el origen. Corrija `user_prompts` / `sessions` primero (HR-2). |
| Respaldar `engram.db` con `cp` estando en WAL | Use `VACUUM INTO` y valide con `integrity_check` (HR-3). |
| Copiar la DB a WSL, mutarla y sobrescribir el original | Corrompe la DB para los agentes que la tienen abierta. Escriba in situ con `node:sqlite` (HR-4). |
| `Stop-Process -Name engram` sin filtrar | Mata los `mcp` de otros agentes. Filtre por `CommandLine -like '*serve*'` (HR-5). |
| Reasignar el proyecto solo en la columna de `sync_mutations` | El cloud recibe el nombre viejo. Actualice también `payload.$.project` (HR-6). |
| Agrupar `00_vba_toolkit_bench` con `vba_toolkit_bench` por el nombre | Su contenido es de `team-skills`. Clasifique leyendo el contenido (HR-8). |
| Añadir a la allowlist todo lo enrolado "para que sincronice todo" | Hay proyectos retirados a propósito. Pregunte siempre (HR-9). |
| Concluir "el autosync no funciona" porque `last_sync_at` está vacío | Es un bug de reporte. Verifique con `acked_at` reciente (HR-10). |
| Renombrar en bloque un proyecto con contenido de varios proyectos | Requiere troceo por sesión. Repórtelo, no lo renombre. |
| Fiarse del `[OK] allowlist.collision` de `diagnose.ps1` | Es un falso positivo. Calcule la colisión con la consulta de §4 paso 2 (HR-12). |
| `Start-Process -NoNewWindow` desde una tool call y esperar el retorno | Hereda la consola y bloquea. Verifique por TCP a 7437 y listado de procesos. |

## §7 Self-compliance

```bash
head -12 SKILL.md                          # seis campos de frontmatter
wc -l SKILL.md                             # body budget <= 1000
head -3 SKILL.md | grep -q "Trigger:"      # description arranca con Trigger
grep -E '^## §' SKILL.md                   # secciones canónicas en orden
grep -cE 'HR-[0-9]+' SKILL.md              # hard rules enumeradas
grep -E '\| (Condition|Symptom|Key) \|' SKILL.md   # gates/anti-patterns/contract en tabla
```

Cumple: 5 secciones canónicas §1–§5 en orden, 12 HR-N con verbo observable, Decision Gates y Anti-patterns y Output Contract en tabla, description monolingüe en castellano, sin emojis, script pesado movido a `assets/audit.mjs`.

## §8 Companion skills

| Skill | Cargar junto cuando |
|---|---|
| `engram-sync-doctor` | La cola está atascada por mutaciones inválidas o el daemon no levanta. Esta skill audita y normaliza; aquella repara la cola. |
| `skill-style-guide` | Refactorice o audite esta skill contra el rubric de authoring. |
| `skill-propagation` | Tras crear o modificar esta skill, para reconciliar el catálogo y los enlaces. |
