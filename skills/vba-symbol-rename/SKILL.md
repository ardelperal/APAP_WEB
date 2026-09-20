---
name: vba-symbol-rename
description: Trigger: rename X a Y, qué se rompe si renombro X, rename this VBA symbol, rename across modules. Renombra un símbolo VBA (Sub/Function/Variable/Const) cross-module con verificación de impacto binario+source antes de escribir.
license: Apache-2.0
status: active
requires: dysflow MCP, codegraph v1.5.0+; for current tool names, flags, defaults and error codes → see `dysflow-usage` skill.
supersedes: v1.0.0 (2026-06-30, escrita contra tooling sin find_references)
metadata:
  author: Andrés Román
  version: 2.0.0
  last_verified: 2026-08-22
  scope: ['vba', 'runtime']
  auto_invoke: ['renaming a VBA symbol across modules']
  tiers: ['vba', 'runtime']
---



# vba-symbol-rename

Renombra un símbolo VBA a través del proyecto con verificación de impacto antes de aplicar. Default: modo `plan` (read-only).

## Activation Contract

- Inputs: `symbol_name` (opcionalmente calificado `Module.Sub`), `new_name`, `module_qualifier` (opcional, desambiguación), `mode` (`plan` default | `apply`), `access_path` (requerido para `apply`).
- Output: `impact_list_json` (plan) o `apply_result_json` (apply). Ver Output Contract.
- Para renombrar CONTROLES de forms usar `vba-control-rename-safe`, no este skill.

## División de la verdad

dysflow es la verdad del binario (.accdb real); codegraph es la verdad del grafo de source (árbol exportado). Si difieren, hay drift: ejecutar `vba-binary-sync` antes de confiar en cualquier análisis. `find_references symbol=X scope=all` es la sonda de drift por símbolo.

## Hard Rules

HR-1. `plan` NO escribe al binario ni al source (read-only puro).
HR-2. `apply` requiere opt-in explícito y re-ejecuta el plan primero (race protection: si el source cambió desde el plan → abortar con `SOURCE_CHANGED`).
HR-3. Nunca renombrar sobre un binario que no compila: el **humano debe compilar** en Access (Debug ▸ Compile) antes de `apply`. → See `dysflow-usage` skill for current compile contract.
HR-4. Colisión de `new_name` en el mismo scope → hard-fail `NAME_COLLISION`; ambigüedad (overloads) → hard-fail `PROCEDURE_AMBIGUOUS` y pedir `module_qualifier`.
HR-5. Punto ciego conocido: referencias late-bound `CallByName obj, "Proc", VbMethod` (string-based) NO aparecen en codegraph ni en find_references. Grep manual obligatorio por `"symbol_name"` entre comillas en `.bas`/`.cls` antes de declarar el plan completo.

## Decision Gates

| Situación | Acción |
| --- | --- |
| `find_references` devuelve typed error (símbolo no existe) | Abortar: `SYMBOL_NOT_FOUND` |
| `scope=all` reporta drift binario vs source | Abortar y ejecutar `vba-binary-sync` primero |
| `new_name` ya referenciado en el mismo scope | Hard-fail `NAME_COLLISION` |
| Hits de grep manual `"symbol"` en strings | Warning `LATE_BOUND_RISK`; decisión humana |
| >50% de matches en strings/comments | Warning de falsos positivos (find_references ya los excluye; contrastar) |
| mode=apply y source cambió desde el plan | Hard-fail `SOURCE_CHANGED` con diff resumido |

## Execution Steps

### Modo `plan` (default)

1. `find_references symbol=<symbol_name> scope=all` → lista completa de referencias (module/kind/line/context) Y comparación binario vs source. Si reporta drift → gate. Si el símbolo no existe → typed error, abortar.
2. `codegraph_explore <symbol_name>` → blast radius del grafo: callers/callees cross-module, bang refs (`Me!X`, `Forms!F!X`), With-blocks, llamadas statement-form, DoCmd targets (todo modelado nativamente por codegraph v1.5.0 — no hace falta heurística manual).
3. Cruce: cada referencia de dysflow debe tener nodo/edge en codegraph. Discrepancias → listar en `warnings` (probable drift o símbolo solo en binario).
4. Colisión: `find_references symbol=<new_name> scope=all`. Si existe en el mismo scope → `NAME_COLLISION`.
5. Check manual CallByName: grep `"<symbol_name>"` (entre comillas) en `.bas`/`.cls` → hits como `LATE_BOUND_RISK`.
6. Emitir `impact_list_json`.

### Modo `apply`

1. Re-ejecutar plan completo (pasos 1-6).
2. Pre-flight: **humano compiló** en Access (Debug ▸ Compile) OK; símbolo aún existe; sin colisión nueva; source idéntico al del plan. → See `dysflow-usage` skill for current compile / verify contract.
3. Editar los archivos del source tree según `impact_entries`.
4. `lint_module` sobre cada módulo editado; `import_modules` de los módulos cambiados. Si el rename toca un control/form declarado en un módulo con `DoCmd.OpenForm` OpenArgs literals, agregar la rule `openargs-contract-mismatch` (v2.19.0+) al gate — un rename de control puede romper silenciosamente el contract que el consumer parser esperaba.
5. Post-flight: humano compiló en Access (Debug ▸ Compile) + `verify_code` (round-trip binario=source). Reindexar codegraph (`codegraph sync`). → See `dysflow-usage` skill for current compile contract.
6. Emitir `apply_result_json` con `changed/skipped/errors`.

## Output Contract

| Key | Type | Description |
|---|---|---|
| `target` | object | Resolved rename target with `kind`, `module`, `name`, `qualified` |
| `impact_entries` | array<object> | Per-file/per-line references to be renamed, with `file`, `line`, `current_text`, `qualified` (plan mode) |
| `total_changes` | number | Count of `impact_entries` (plan mode) |
| `warnings` | array<object> | Drift, late-bound, false-positive warnings with `reason_code` and `message` |
| `changed` | array<object> | Applied changes with `file`, `line`, `before`, `after` (apply mode) |
| `skipped` | array<object> | Entries not changed with `file`, `line`, `reason_code` (apply mode) |
| `errors` | array<object> | Hard failures with `reason_code` (apply mode) |
| `post_validation` | object | `import_gate`, `compile_check`, `verify_code` results (apply mode) |

`plan` mode returns `target + impact_entries + total_changes + warnings`. `apply` mode returns `target + changed + skipped + errors + post_validation`. Precisión exigida: 0% falsos negativos en `impact_entries` (todos los callers cross-module y handlers de forms cubiertos).

## Anti-patterns

| Symptom | Fix |
|---|---|
| Renaming without a cross-module impact check | Run `find_references scope=all` + `codegraph_explore` first; never apply blind |
| Confusing `plan` and `apply` modes | Default to `plan` (read-only); `apply` requires explicit opt-in and a fresh re-run of the plan |
| Skipping the late-bound `CallByName` grep | Always grep `"<symbol_name>"` between quotes in `.bas`/`.cls`; flag hits as `LATE_BOUND_RISK` |
| Renaming a control of an Access form with this skill | Use `vba-control-rename-safe` instead — this skill is for VBA code symbols only |

## References

- `references/examples-and-failure-modes.md` — ejemplos JSON completos de plan/apply, escenarios de aceptación y failure modes tipados.
- Skills relacionados: `vba-source-impact` (impacto en source), `vba-control-rename-safe` (controles de forms), `vba-binary-sync` (resolver drift).
