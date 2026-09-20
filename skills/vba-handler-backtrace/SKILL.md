---
name: vba-handler-backtrace
description: Trigger: trace handler for control X, what does cmdSave_Click call, backtrace event flow to the database, diagnose form control to SQL path. Traces a VBA form control event handler forward through the call chain to its DAO database operations, extracting SQL hints and custom UDT parameters.
license: Apache-2.0
status: active
requires: codegraph MCP (codegraph_explore) with an initialized .codegraph/ index for the target VBA/Access project
metadata:
  author: Andrés Román
  version: 1.0.0
  last_verified: 2026-08-22
  scope: ['vba', 'runtime']
  auto_invoke: ['tracing a form control event handler']
  tiers: ['vba', 'runtime']
---



# vba-handler-backtrace

Traces a form control's event handler forward through the call graph to the DAO database operations it eventually triggers, reconstructing multiline SQL string concatenations and mapping User-Defined Type (UDT) parameters along the way. Read-only bisturí: one control/handler in, one call-tree JSON out.

## Activation Contract

- Input: `control` (e.g. `"ComandoRechazar"`) or `handler` (e.g. `"Form_FormCalidadRiesgoAceptadoRetiradoVisado.ComandoRechazar_Click"`) plus optional `max_depth` (default `5`).
- Output: a single JSON object (see Output Contract). No writes, no side effects.
- This skill answers "what does this handler eventually touch in the database" — for tracing a custom `Public Event` (not a control click handler) use `vba-event-tracer` instead.

## Hard Rules

- **HR-1. Codegraph index required**: The target project directory MUST have a `.codegraph/` index.
- **HR-2. Hard-fail on missing index**: If absent, hard-fail `NO_CODEGRAPH_INDEX`.

## Decision Gates

| Situation | Action |
| --- | --- |
| A node already visited in the current branch is reached again | Stop that branch, tag the node `CYCLE_DETECTED`, do not recurse further |
| Traversal reaches `max_depth` (default 5) without terminating | Truncate the branch, append `MAX_DEPTH_EXCEEDED` to the top-level `warnings` array |
| Control or handler not found in the graph | Hard-fail `HANDLER_NOT_FOUND` |
| DAO call site spans multiple source lines via `_` continuation and `&` concatenation | Reconstruct the full literal before truncating |
| Reconstructed SQL hint exceeds 200 characters | Truncate to 200 characters, do not fail |
| Parameter type is a VBA primitive (`Long`, `Integer`, `String`, `Boolean`, `Double`, `Single`, `Byte`, `Currency`, `Date`, `Variant`, `Object`, `LongLong`, `LongPtr`, `Decimal`) | Exclude from `parameters`; only custom/enum/UDT types are kept |

## Execution Steps

### Step 1: Graph traversal from the control
Starting from the control or handler node, recursively follow outgoing `defines-event` and `calls` edges via `codegraph_explore`, building a tree. Track a `visited` set of node ids per branch to detect cycles; cap depth at `max_depth` (default `5` — this is a hard cap, not a soft suggestion: it governs correctness of the trace, not just verbosity).

### Step 2: UDT parameter extraction
For each procedure node in the path, read its declaration signature and extract `(paramName, paramType)` pairs. Filter out VBA primitive types (list above); keep only custom classes, enums, and user-defined structs. Attach the surviving pairs as a `parameters` array on that node — do not hoist them to a single top-level list, since a trace tree can have multiple procedures each with their own parameters.

### Step 3: DAO call detection and SQL reconstruction
When a node performs a DAO operation (`OpenRecordset`, `Execute`, `QueryDefs`), read the source line(s). If the SQL string is built via `_` line-continuation and `&` concatenation across multiple lines, reconstruct the full literal by concatenating the quoted segments in order. Attach the result as `sql_hint` on that node, truncated to 200 characters if longer.

### Step 4: Emit output
Format the full call tree per the Output Contract. Cyclic and depth-truncated branches still appear in the tree (marked), they are simply not expanded further.

## Output Contract

| Key | Type | Description |
|---|---|---|
| `tree` | object | Root node with nested `children`; each child carries `id`, `name`, `kind`, optional `parameters`, optional `sql_hint`, and `children` |
| `cycle_detected` | boolean | Convenience flag set to true if any node in the tree was tagged `CYCLE_DETECTED` |
| `warnings` | array<string> | Trace-level conditions such as `MAX_DEPTH_EXCEEDED` |

```json
{
  "tree": {
    "id": "ComandoRechazar",
    "name": "ComandoRechazar",
    "kind": "control",
    "children": [
      {
        "id": "Form_FormCalidadRiesgoAceptadoRetiradoVisado.ComandoRechazar_Click",
        "name": "ComandoRechazar_Click",
        "kind": "event",
        "parameters": [],
        "children": [
          {
            "id": "Riesgo.AceptacionRechazo",
            "name": "AceptacionRechazo",
            "kind": "function",
            "parameters": [{ "name": "p_Estado", "type": "EnumRiesgoEstado" }],
            "sql_hint": "SELECT * FROM TbRiesgos WHERE IDRiesgo=<IDRiesgo>;",
            "children": []
          }
        ]
      }
    ]
  },
  "cycle_detected": false,
  "warnings": []
}
```

`cycle_detected` is a convenience top-level flag (true if any node in the tree was tagged `CYCLE_DETECTED`); the authoritative per-node signal lives on the node itself. `warnings` only carries trace-level conditions such as `MAX_DEPTH_EXCEEDED`.

## Anti-patterns

| Symptom | Fix |
|---|---|
| Tracing a custom `Public Event` declaration with this skill | Use `vba-event-tracer`; this skill is for control click handlers only |
| Running without an initialized `.codegraph/` index | Hard-fail `NO_CODEGRAPH_INDEX`; ask the human to run `codegraph init` first |
| Reconstructing SQL without parsing `_` continuations | Concatenate quoted segments in order before emitting `sql_hint` |
| Tracing system-library events (`DoCmd.OpenForm`, etc.) | Skip — those are runtime objects, not user-written call chains |

## References

- `references/examples.md` — RED test cases (happy path with real SQL/UDT extraction, cycle detection, depth cap).
- Related skills: `vba-event-tracer` (custom `Public Event` tracing), `vba-sql-impact` (reverse direction: table/query to callers), `vba-symbol-rename` (write-side rename operations — this skill is read-only).
