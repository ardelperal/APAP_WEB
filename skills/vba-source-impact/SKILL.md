---
name: vba-source-impact
description: Trigger: impacto en source de X, qué archivos afecta cambiar X, qué tests cubren el área de X. Lista el impacto en el source tree de tocar un símbolo VBA: callers/callees, refs UI (Me.X, bang refs), bindings RecordSource/RowSource, TempVars, DoCmd targets, archivos afectados y tests relacionados.
license: Apache-2.0
status: active
requires: codegraph v1.5.0+, dysflow MCP (cross-check opcional); for current tool names and flags → see `dysflow-usage` skill.
supersedes: v1.0.0 (2026-06-30, usaba heurísticas regex para edges que codegraph ya modela)
metadata:
  author: Andrés Román
  version: 2.0.0
  last_verified: 2026-08-22
  scope: ['vba', 'runtime']
  auto_invoke: ['tracing source-level impact of a VBA change']
  tiers: ['vba', 'runtime']
---



# vba-source-impact

Reporte del impacto en el SOURCE TREE de cambiar un símbolo, leído directamente del grafo de codegraph (que en v1.5.0 modela los edges UI y de datos que antes exigían heurísticas regex).

## Activation Contract

- Inputs: `target` (símbolo, file path o wildcard), `access_path` (opcional), `project_root` (default cwd).
- Output: `source_impact_json` — ver Output Contract.
- Solo lee el source tree/grafo. La verificación del binario es `vba-binary-drift`.

## División de la verdad

dysflow es la verdad del binario (.accdb real); codegraph es la verdad del grafo de source (árbol exportado). Si difieren, hay drift: ejecutar `vba-binary-sync` antes de confiar en cualquier análisis. `find_references symbol=X scope=all` es la sonda de drift por símbolo.

## Hard Rules

HR-1. Pedir los edges al grafo, no reconstruirlos: codegraph v1.5.0 modela bang refs (`Me!X`, `Forms!F!X`), With-blocks, DoCmd.OpenForm/OpenReport/OpenQuery, bindings RecordSource/RowSource como edges, TempVars como nodos de estado cross-form, impacto SQL de tablas (FROM/JOIN/INTO/UPDATE, incluso nombres bracketed con espacios), y binding Report_*.cls ↔ .report.txt.
HR-2. La convención de nombre de event handlers (`X_Click`, `X_BeforeUpdate`) sigue siendo una verificación complementaria SOLO para handlers declarados pero sin edge (control eliminado, handler huérfano) — no el mecanismo primario de detección.
HR-3. Punto ciego conocido: `CallByName` late-bound — grep manual por `"target"` entre comillas.
HR-4. Advisory: no bloquea ni fuerza el cambio; no emite juicios cualitativos.

## Decision Gates

| Situación | Acción |
| --- | --- |
| Wildcard matchea >100 nodos | No expandir; devolver `wildcard_match_count` y pedir target más específico |
| Index de codegraph stale (>1h sin sync tras cambios) | Warning + sugerir `vba-binary-sync` antes de evaluar |
| Refs circulares (A → B → A) | `cycle_detected: true`; el orquestador decide |
| Handler `X_*` presente en .cls sin control X en el grafo | Reportar como handler huérfano (candidato para `vba-form-repair`) |

## Execution Steps

1. Parse del target (símbolo, path o wildcard).
2. `codegraph_explore <target>` → callers/callees directos con file:line.
3. Del mismo grafo, extraer edges UI y de datos del target: refs de controles (incl. bang refs cross-form), bindings RecordSource/RowSource, TempVars leídas/escritas, forms/reports/queries abiertos vía DoCmd, tablas impactadas por SQL embebido.
4. Verificación complementaria de handlers huérfanos: para cada control afectado X, confirmar que cada handler `X_<Evento>` del `.cls` tiene su control en el grafo.
5. Tests que cubren el área → `related_tests`: `codegraph_explore`/`getCallers` sobre los símbolos afectados alcanza los `Test_*`; cada uno lleva un edge entrante `references` tagueado `vba-test-manifest` con `metadata.{testName, tags, manifestFile}`, así que `related_tests` se llena del grafo en una sola pasada, sin grep de los `tests.*.json`.
6. Consolidar `affected_files`: archivo target + todos los archivos con refs.
7. Check manual CallByName (grep de strings) → warnings.

## Output Contract

| Key | Type | Description |
|---|---|---|
| `target` | string | Echo of the parsed input (symbol, file path, or wildcard) |
| `parsed` | object | Resolved target with `kind`, `module`, `line` |
| `direct_callers` | array<object> | Callers of the target with `module`, `name`, `line`, `context` |
| `direct_callees` | array<object> | Callees invoked by the target with `module`, `name`, `line` |
| `ui_refs` | array<object> | UI references (`Me.X`, bang refs, handler mappings) with `form`, `control`, `kind`, `line` |
| `data_bindings` | array<object> | `RecordSource`/`RowSource`/`TempVar`/`DoCmd`/`sql-table` bindings with `source` and `target` |
| `affected_files` | array<string> | Distinct files touched by the impact graph |
| `related_tests` | array<object> | Tests covering the target area with `name`, `procedure`, `tags`, `manifest` |
| `warnings` | array<string> | Drift, orphan handlers, CallByName hits, stale-index notices |

```json
{
  "target": "...",
  "parsed": { "kind": "...", "module": "...", "line": 0 },
  "direct_callers": [{ "module": "...", "name": "...", "line": 0, "context": "..." }],
  "direct_callees": [{ "module": "...", "name": "...", "line": 0 }],
  "ui_refs": [{ "form": "...", "control": "...", "kind": "Me.X|bang|handler", "line": 0 }],
  "data_bindings": [{ "kind": "RecordSource|RowSource|TempVar|DoCmd|sql-table", "source": "...", "target": "..." }],
  "affected_files": [],
  "related_tests": [{ "name": "...", "procedure": "...", "tags": ["..."], "manifest": "..." }],
  "warnings": []
}
```

## Anti-patterns

| Symptom | Fix |
|---|---|
| Running impact analysis without a codegraph index | Hard-fail; tell the user to initialize `.codegraph/` before retrying |
| Trusting regex heuristics for UI edges | Use codegraph v1.5.0+ edges (bang refs, With-blocks, DoCmd targets) directly |
| Expanding a wildcard that matches >100 nodes | Stop and return `wildcard_match_count`; ask for a more specific target |
| Skipping the CallByName late-bound grep | Always grep `"target"` between quotes; flag hits as `LATE_BOUND_RISK` warnings |

## References

- `references/examples-and-failure-modes.md` — ejemplo completo, acceptance scenarios y failure modes.
- Skills relacionados: `vba-binary-drift` (impacto binario), `vba-form-repair` (arreglar handlers huérfanos).
