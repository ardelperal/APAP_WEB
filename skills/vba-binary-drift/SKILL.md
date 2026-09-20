---
name: vba-binary-drift
description: Trigger: drift binario, sincronizado, recompila, zombies MSACCESS, readback de .cls. Verifica drift source vs binario Access (.cls = comportamiento, .form.txt = UI/layout); exige .dysflow/project.json por worktree; detecta zombies MSACCESS.
license: Apache-2.0
status: active
requires: dysflow MCP, codegraph-vba MCP (`codegraph_explore`); for current tool names and flags → see `dysflow-usage` skill.
supersedes: v2.0.0 (2026-07-09; añade distinción comportamiento vs UI/layout y gate de read-back tras el incidente EXPEDIENTES donde el .cls commiteado no coincidía con el .accdb commiteado)
metadata:
  author: Andrés Román
  version: 3.1.1
  last_verified: 2026-09-16
  scope: ['vba', 'runtime']
  auto_invoke: ['detecting source vs binary drift', 'running dysflow drift audit']
  tiers: ['vba', 'runtime']
---

# vba-binary-drift

Reporte del estado de sincronización entre el source tree y el binario Access: drift global, sonda por símbolo, recompilación necesaria, zombies MSACCESS.EXE. Read-only.

> **Dysflow tool references.** This skill uses Dysflow tools (`verify_code`, `find_references`, `list_access_operations`, `import_modules`, `export_modules`, `setup_project`, `migrate_project_config`, `resolve_project`, `access_force_cleanup_orphaned`, `compact_repair`, etc.). Tool names, flag shapes, and invocation patterns are maintained by `dysflow-usage` — that skill is the canonical source of truth. If a tool is renamed or its signature changes there, this skill's references should be re-aligned in the same change. Inline references below intentionally keep tool names visible for readability; do not duplicate flag shapes, error codes, or argument schemas here — see `dysflow-usage` for those.

## Activation Contract

- Inputs: `target` (opcional; default binario entero: módulo, archivo, wildcard o símbolo), `access_path` (requerido).
- Output: `binary_drift_json` — ver Output Contract.
- No mata zombies, no recompila, no consulta el grafo de source (eso es `vba-source-impact`). Solo reporta.

## División de la verdad

dysflow es la verdad del binario (.accdb real); codegraph es la verdad del grafo de source (árbol exportado). Si difieren, hay drift: ejecutar `vba-binary-sync` antes de confiar en cualquier análisis. La sonda de drift por símbolo es el tool de references del runtime Dysflow (current name per `dysflow-usage`).

## Hard Rules

HR-1. El tool canónico de drift (current: `verify_code`, per `dysflow-usage`) es la fuente de verdad para drift global (source vs binario, ambos lados exportados y comparados).
HR-2. Para un símbolo concreto, la sonda barata es el tool de references del runtime Dysflow (current: `find_references`, per `dysflow-usage`) con scope amplio: compara referencias en binario vs source y reporta la divergencia sin exportar todo.
HR-3. El zombie check (tool: `list_access_operations`, per `dysflow-usage`) cuenta SOLO procesos MSACCESS.EXE que lockean el `accessPath` objetivo; procesos Access ajenos → warning, no cuenta.
HR-4. Matar zombies es acción separada y confirmada por humano (tool: `access_force_cleanup_orphaned`, per `dysflow-usage`) con `pid`, `implements_check:"orphans_msaccess"` y confirmación explícita — este skill nunca lo hace.
HR-5. **Comportamiento = `.cls`, UI/layout = `.form.txt` (hard gate)**: para Access forms, la fuente de verdad del comportamiento es `Form_FormX.cls`; el segmento de código serializado dentro de `Form_FormX.form.txt` es metadato y NO es autoritativo. La clasificación de drift debe distinguir `behavior-functional` (cambia lo que ejecuta el `.cls`) de `behavior-cosmetic` (sólo normalización de encoding, comentarios, geometría de controles). Un diff cosmético en el `.form.txt` NO bloquea entrega; un diff funcional en el `.cls` SÍ bloquea entrega.
HR-6. **`verify_code` clean no es comportamiento verificado** (per `dysflow-usage`): el tool de drift es una verificación estructural/round-trip; no prueba que el binario ejecute el comportamiento pretendido. Tratá `verify_code` clean como precondición, no como evidencia; para cambios behavior-critical emparejar con read-back (ver Execution Steps) y exigir aserciones de símbolos críticos. Un `import_modules` con status `ok` o un hash git nuevo del `.accdb` no prueban que el código nuevo esté en el binario.
HR-7. **`.dysflow/project.json` por worktree (hard gate, runtime-managed)**: cada repo o worktree real que use dysflow debe tener su propio `.dysflow/project.json` con `projectId` único (campo canónico: `projectId`, no `id`). NO escribas este fichero a mano. Lo regenera el runtime con los tools de gestión de proyecto (current: `setup_project` o `migrate_project_config`, per `dysflow-usage`) cuando hace falta. Reportes de drift contra un binario resuelto por cwd equivocado, contra un `projectId` faltante, o contra un config compartido entre worktrees son no confiables → warning y sugerencia del tool de resolución de proyecto (current: `resolve_project`, per `dysflow-usage`; o `setup_project` si el config no existe).

## Decision Gates

| Situación | Acción |
| --- | --- |
| Binario lockado por proceso activo | Hard-fail + sugerir cleanup de huérfanos |
| `verify_code` falla (binario corrupto/ilegible) | Hard-fail con mensaje claro; considerar tool de repair (current: `compact_repair`, per `dysflow-usage`) |
| Target es un símbolo (no módulo/binario entero) | Usar la sonda de references (per `dysflow-usage`) con scope amplio en vez de export completo |
| Drift detectado | Poblar `diff_summary` file-by-file y marcar `recompile_needed` si algún `.cls`/`.bas` cambió |
| Drift puramente cosmético en `.form.txt` (sólo encoding, comentarios, geometría de controles) | Reportar pero NO bloquear entrega; `behavior_drift.kind: behavior-cosmetic` |
| Drift funcional en `.cls` (helper call ausente, valor hardcodeado que source reemplaza, código viejo retenido) | Bloquear entrega; recomendar `vba-binary-sync` con re-import + read-back; `behavior_drift.kind: behavior-functional` |
| Repo/worktree sin `.dysflow/project.json`, con `projectId` faltante, o con config compartido entre worktrees | Warning; el reporte puede estar apuntando al binario equivocado; sugerir tool de resolución de proyecto (per `dysflow-usage`; o `setup_project` si no existe). NO escribir el config a mano. |
| `import_modules` reciente devolvió `ok` pero el binario conserva código viejo | No reportado por este skill como éxito; requiere `vba-binary-sync` con read-back explícito |

## Execution Steps

1. Tool de drift canónico (current: `verify_code`, per `dysflow-usage`) sobre el target → drift global por archivo (source vs binario).
2. Si el target es un símbolo: tool de references (current: `find_references`, per `dysflow-usage`) sobre el símbolo con scope amplio → divergencia de referencias binario vs source (drift localizado, sin export masivo).
3. Tool de listado de operaciones (current: `list_access_operations`, per `dysflow-usage`) → contar MSACCESS.EXE lockeando el `accessPath`.
4. Si hay drift y necesitás evidencia por archivo: leer `summaryStructured`, `bulkImportable[]`, `bulkExportable[]`, y los `reason` por entrada del tool de drift; usar el filtro per-`moduleNames` solo si hace falta ampliar el diff file-by-file. **NO usar tools de export para inspeccionar drift**: usar el tool de drift. Para una preview de exportación, la forma canónica es `apply:false`; `diff:true` es el único alias legacy y solo para exportaciones cuando aparece en `legacyAliases[]`. Una exportación aplicada debe mantener `mutateBinary:false` y devolver `binaryMutated:false` salvo opt-in legacy explícito.
5. **Config check**: ejecutar el tool de resolución de proyecto (current: `resolve_project`, per `dysflow-usage`) sobre el worktree target y leer `.dysflow/project.json` (vía `bootstrap.projectConfig` o `schema({view:"project-config"})` — NO leer el fichero a mano) para confirmar `outcome:"resolved"` y que `projectId`/`accessPath` corresponden al target. Si falta o colisiona, NO escribir el fichero a mano: ejecutar `setup_project` o `migrate_project_config` y volver al tool de resolución. Persistir el warning (`dysflow_project_config.present: false`) mientras los reportes siguientes pueden estar apuntando al binario equivocado.
6. **Clasificar drift por archivo** (extensión de la evidencia del tool de drift + tool de references): por cada `.cls` → `behavior-functional` si cambia comportamiento (helper calls, asignaciones, eventos); `behavior-cosmetic` si sólo normalización. Por cada `.form.txt` → `layout` (no es comportamiento; reportar pero no clasificar como bloqueante). El segmento de código embebido en `.form.txt` es metadato y NO se usa como evidencia de comportamiento.
7. **Read-back opcional para drift behavior-critical**: si el target incluye un `.cls` con cambios de comportamiento, exportar ese `.cls` desde el `target_binary` a un temp dir nuevo y comparar contenido funcional contra el source `.cls`; calcular `source_hash`/`export_hash`, ejecutar aserciones de símbolos críticos; poblar `readback_verified`. Si el read-back contradice el tool de drift (drift clean pero read-back muestra código viejo retenido) → elevar el hallazgo a hard-fail y recomendar `vba-binary-sync` con re-import + read-back.
8. Calcular `recompile_needed`: `true` si cualquier módulo de código cambió y el binario no se recompiló.

## Output Contract

Return an object with the following keys:

| Key | Type | Description |
|---|---|---|
| `target` | string | Module, file, wildcard, or symbol reported on. |
| `drift` | boolean | Whether source vs binary drift exists at the global level. |
| `symbol_drift` | object \| null | Per-symbol divergence `{symbol, binary_refs, source_refs, divergent[]}` when target is a symbol. |
| `binary_chksum_changed` | boolean | Whether the binary checksum changed since the last report. |
| `recompile_needed` | boolean | `true` if any code module changed and the binary was not recompiled. |
| `zombie_msaccess_present` | number | Count of MSACCESS.EXE processes locking the `accessPath`. |
| `dysflow_project_config` | object | `{present, id, matches_cwd}` — worktree config state. |
| `behavior_drift` | object[] | Per-file classification: `{file, kind: "behavior-functional"\|"behavior-cosmetic"\|"layout", details, source_hash, export_hash}`. |
| `readback_verified` | boolean | True when an explicit read-back confirmed the `.cls` content. |
| `diff_summary` | object[] | File-by-file tool-of-drift entries with `classification` + `reason`. |
| `summaryStructured` | object | Raw tool-of-drift summary block. |
| `bulkImportable` | string[] | Modules eligible for the import tool. |
| `bulkExportable` | string[] | Modules eligible for the export tool. |
| `next_recommended` | `"vba-binary-sync" \| "compact_repair" \| "manual_review" \| "none"` | Next step when drift is detected. |

Example JSON shape (`binary_drift_json`):

```json
{
  "target": "...",
  "drift": false,
  "symbol_drift": null,
  "binary_chksum_changed": false,
  "recompile_needed": false,
  "zombie_msaccess_present": 0,
  "dysflow_project_config": { "present": true, "id": "...", "matches_cwd": true },
  "behavior_drift": [
    { "file": "Form_Foo.cls", "kind": "behavior-functional", "details": "...", "source_hash": "sha256:...", "export_hash": "sha256:..." }
  ],
  "readback_verified": false,
  "diff_summary": [{ "file": "...", "classification": "sourceNewer", "reason": "...", "matches": false }],
  "summaryStructured": {},
  "bulkImportable": [],
  "bulkExportable": []
}
```

`behavior_drift[].kind`:
- `behavior-functional`: cambio en `.cls` que altera lo que ejecuta → bloquea entrega.
- `behavior-cosmetic`: cambio en `.cls` que sólo normaliza encoding/comentarios/case → NO bloquea.
- `layout`: cambio en `.form.txt` (UI/posición/controls) → NO bloquea; el segmento de código embebido en `.form.txt` NO se evalúa como comportamiento.

Si `dysflow_project_config.present: false` o `matches_cwd: false` → el reporte es no confiable; warning explícito y recomendar el tool de resolución de proyecto (per `dysflow-usage`) antes de confiar en los findings.

## Anti-patterns

| Symptom | Fix |
|---|---|
| Treating `verify_code` clean as behavior-verified | Run read-back on behavior-critical `.cls`; require assertions on critical symbols (HR-6). Tool flag shape per `dysflow-usage`. |
| Blocking delivery on a cosmetic `.form.txt` diff | Classify as `behavior-cosmetic` or `layout`; do not block on cosmetic encoding or normalization (HR-5). |
| Drift check against a shared `.dysflow/project.json` config | Each worktree needs its own `.dysflow/project.json` with unique `id`, `accessPath`, `backendPath` (HR-7). |
| Killing MSACCESS.EXE orphans to "fix" the drift report | This skill is read-only; cleanup goes through `access_force_cleanup_orphaned` (per `dysflow-usage`) with explicit human confirmation (HR-4). |

## References

- `dysflow-usage` — canonical source for current Dysflow tool names, flag shapes, error codes, and invocation patterns.
- `dysflow-arnes` — operating harness for Dysflow; bootstrap, schema, capabilities.
- `references/examples-and-failure-modes.md` — escenarios de aceptación y failure modes.
- `references/examples.md` — ejemplos de uso del skill.
- `vba-binary-sync/references/incident-readback-failure.md` — rationale del gate de read-back post-import; relevante acá porque este skill debe distinguir drift funcional vs cosmético para que la entrega no se apruebe con un binario que retiene código viejo.
- Skills relacionados: `vba-source-impact` (mitad source del split de `access-vba-impact`), `vba-binary-sync` (resolver el drift detectado).
