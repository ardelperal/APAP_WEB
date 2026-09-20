---
name: vba-control-rename-safe
description: Trigger: renombra el control X, qué pasa si cambio X por Y, safe-rename de X, consolida forms y renombra controles. Renombra un control de Access de forma segura, mapeando refs Me.X, bang refs, event handlers y consumers antes de aplicar con form_rename_control.
license: Apache-2.0
status: active
requires: dysflow MCP, codegraph v1.5.0+; for current tool names, flags, defaults and error codes → see `dysflow-usage` skill.
supersedes: v1.0.0 (2026-06-29, editaba .form.txt a mano; bang refs eran hueco de codegraph)
metadata:
  author: Andrés Román
  version: 2.0.0
  last_verified: 2026-08-22
  scope: ['vba', 'runtime']
  auto_invoke: ['renaming an Access form control']
  tiers: ['vba', 'runtime']
---



# vba-control-rename-safe

Renombra un control de Access identificando todos los puntos de cambio antes de aplicar. La mutación va por la primitiva `form_rename_control` (no edición manual del `.form.txt`), con round-trip verificado.

## Activation Contract

- Inputs: `form` (qualified, ej. `Form_FormRiesgosGestionRiesgo`), `control_name`, `new_name`, `dry_run` (default true), `access_path`.
- Output: `rename_plan_json` (dry_run) o plan + resultado aplicado — ver Output Contract.
- No decide qué nombre es mejor, no commitea, no abre PRs.

## División de la verdad

dysflow es la verdad del binario (.accdb real); codegraph es la verdad del grafo de source (árbol exportado). Si difieren, hay drift: ejecutar `vba-binary-sync` antes de confiar en cualquier análisis. `find_references symbol=X scope=all` es la sonda de drift por símbolo.

## Hard Rules

- **HR-1.** El rename del control en el binario se hace con `form_rename_control` — nunca editando `Name = "X"` a mano en el `.form.txt`.
- **HR-2.** Codegraph v1.5.0 modela bang refs (`Me!Ctl`, `Forms!Form!Ctl`) y bindings RowSource/RecordSource como edges: pedir las referencias UI al grafo, no reconstruirlas con grep.
- **HR-3.** El rename del control arrastra sus event handlers por convención (`X_Click` → `Y_Click`, `_BeforeUpdate`, `_AfterUpdate`, `_Change`, `_Enter`, `_Exit`, `_GotFocus`, `_LostFocus`, `_KeyDown/Press/Up`, `_MouseDown/Move/Up`): todos se renombran en sync en el `.cls`, o el binding evento-control se rompe.
- **HR-4.** Colisión de `new_name` en el MISMO form → hard-fail. `new_name` usado en OTROS forms → warning (decisión humana).
- **HR-5.** Punto ciego conocido: refs late-bound `CallByName(form, "X", ...)` y strings `Me("X")` — grep manual por `"control_name"` entre comillas; hits → warning, no fail.
- **HR-6.** Convención de split: el código va en el `.cls`; la definición UI va en el `.form.txt`. El rename toca ambos lados y deben quedar consistentes.

## Decision Gates

| Situación | Acción |
| --- | --- |
| Control no existe en el form | Hard-fail (verificar con `inspect_form` o el grafo) |
| `new_name` ya existe en el mismo form | Hard-fail `NAME_COLLISION` |
| `new_name` usado en otros forms | Warning; `feasibility: risky` si son muchos |
| Variable local VBA con el mismo nombre que el control (shadowing) | Marcar como probable falso positivo y warn |
| Hits en strings (late-bound) | Warning `LATE_BOUND_RISK`; humano decide |
| Drift binario vs source antes de aplicar | Abortar → `vba-binary-sync` |

## Execution Steps

> **Token economy (v2.1.7+).** Las form tools de lectura (`inspect_form`, `form_serialize`, `compare_form`, `lint_form_code`, `harvest_form_catalog`) aceptan `outputMode: "summary" | "file" | "full"`. Para el round-trip de verificación del rename, `form_serialize` + `compare_form` con `outputMode:"summary"` alcanza en la mayoría de los casos.

### Plan (dry_run=true, default)

1. Validación: `inspect_form <form>` (o codegraph) confirma que `control_name` existe; check de colisión de `new_name` en el mismo form (hard-fail) y cross-form (warn).
2. Mapa de refs de código: `find_references symbol=<control_name> scope=all` → refs con module/kind/line/context y drift binario vs source.
3. Mapa de refs UI: `codegraph_explore` → edges bang (`Me!X`, `Forms!F!X`), `Me.X`, bindings RowSource/RecordSource que mencionen el control.
4. Mapa de handlers: identificar todos los `X_<Evento>` presentes en el `.cls`; todos entran al plan de rename.
5. Check late-bound: grep `"<control_name>"` en `.cls`/`.bas` → warnings.
6. Emitir `rename_plan_json` con `feasibility`, `rename_steps` ordenados y patch preview. No tocar nada.

### Apply (dry_run=false)

1. Re-validar el plan (drift check con `find_references scope=all`).
2. `form_rename_control` → renombra el control en el binario.
3. Editar el `.cls` del source: `Me.X`/`Me!X` → nuevo nombre; handlers `X_*` → `Y_*`; importar el módulo actualizado.
4. Verificación round-trip: `form_serialize` (read-only) del form + `compare_form` contra el estado esperado → confirmar que solo cambió el nombre del control.
5. Gates finales: `lint_form_code` + **humano compila** en Access (Debug ▸ Compile). → See `dysflow-usage` skill for current compile contract. Reindexar codegraph.

## Output Contract

`rename_plan_json`: `{ feasibility: "safe|risky|blocked", reasons: [], impact_in_source: { direct_refs: [{file, line, kind, context}], event_handlers: [{handler_name, file, line}], docmd_openers: [] }, forms_also_using_this_control_name: [], drift_check: {source_clean, binary_clean}, rename_steps: [{step_id, action, before, after, risk}], estimated_diff_lines, patch_preview }`.

En apply, añadir: `applied: true`, `roundtrip_check: {serialize_diff_clean, compare_form_clean}`, `post_gates: {lint, compile}`.

## References

- `references/examples-and-edge-cases.md` — ejemplo JSON completo, edge cases (shadowing, refactor masivo) y criterios v1.0.0.
- Skills relacionados: `vba-symbol-rename` (símbolos de código, no controles), `vba-form-repair` (forms rotos/inconsistentes), `vba-binary-sync` (drift).

## Anti-patterns

| Symptom | Fix |
|---|---|
| Renombrar el control sin pedir primero las refs UI al grafo (bang refs, RowSource/RecordSource) | Correr `codegraph_explore` + `find_references` antes; cualquier ref UI no detectada rompe el binding evento-control al aplicar |
| Renombrar un control que tiene event handlers sin planificar el rename de cada `X_<Evento>` → `Y_<Evento>` | Listar todos los handlers primero (`X_Click`, `_BeforeUpdate`, `_AfterUpdate`, `_Change`, `_Enter`, `_Exit`, `_GotFocus`, `_LostFocus`, `_KeyDown/Press/Up`, `_MouseDown/Move/Up`) y renombrarlos en sync en el `.cls` |
| Editar `Name = "X"` a mano en el `.form.txt` y luego importar | Usar siempre la primitiva `form_rename_control`; edición manual del `.form.txt` deja el binario inconsistente con el source |
| Ignorar hits de grep `"control_name"` entre comillas (refs late-bound / `Me("X")`) | Marcar como warning `LATE_BOUND_RISK` y pedir decisión humana antes de aplicar; no descartar como falso positivo sin evidencia |
