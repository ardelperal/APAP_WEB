---
name: vba-sql-impact
description: Trigger: what breaks if I change table X, impact of modifying query X, who reads/writes table X, trace SQL alias lineage. Assesses the impact of changing a table or saved query in an MS Access project: finds VBA callers, form/report bindings, and resolves column/table alias lineage.
license: Apache-2.0
status: active
requires: codegraph MCP (codegraph_explore) with an initialized .codegraph/ index for the target VBA/Access project
metadata:
  author: Andrés Román
  version: 1.0.0
  last_verified: 2026-08-22
  scope: ['vba', 'runtime']
  auto_invoke: ['tracing SQL impact in Access VBA']
  tiers: ['vba', 'runtime']
---



# vba-sql-impact

Assesses the downstream impact of changing an Access table or saved query (QueryDef): VBA callers referencing it, form/report data bindings consuming it, and SQL alias lineage mapping qualified columns back to base tables. Read-only bisturí: one table/query name in, one impact JSON out.

## Activation Contract

- Input: `target_name` — a table name (e.g. `"TbRiesgos"`) or a saved query name.
- Output: a single JSON object (see Output Contract). No writes, no side effects.
- This skill assesses SCHEMA/QUERY impact (what reads or binds to this table/query). For tracing a VBA event or a control's call chain, use `vba-event-tracer` or `vba-handler-backtrace` instead.

## Hard Rules

- **HR-1. Codegraph index required**: The target project directory MUST have a `.codegraph/` index.
- **HR-2. Hard-fail on missing index**: If absent, hard-fail `NO_CODEGRAPH_INDEX`.
- **HR-3. Layout and saved-query support**: This skill also reads exported layout files (`.form.txt`, `.report.txt`) and, where present, saved query definitions. Projects that build all SQL as ad-hoc VBA string literals (no exported `.sql` QueryDef files) will simply have an empty `lineage` from that source — fall back to inline `FROM`/`JOIN` parsing from VBA string literals in that case (see Step 3).

## Decision Gates

| Situation | Action |
| --- | --- |
| Target name matches neither a table, a QueryDef, nor any VBA string literal reference | Hard-fail `TARGET_NOT_FOUND` |
| A column reference has no resolvable alias/table prefix | Append a warning `UNALIASED_COLUMN: <column>` |
| A qualified prefix matches more than one table in scope (rare, only under nested subqueries) | Append `AMBIGUOUS_ALIAS: <prefix>` and skip resolution for that reference rather than guessing |
| No exported `.sql` QueryDef file exists but inline SQL literals reference the target | Still resolve aliases from the inline literal; do not fail |

## Execution Steps

### Step 1: Trace VBA callers
Search the index (or grep VBA source as fallback) for the target name appearing as a literal argument to `OpenRecordset(...)` or as a key into the `QueryDefs` collection (e.g. `db.QueryDefs("<target>")`). For each match, record `file`, `line`, and the matching line's trimmed text as `context`.

### Step 2: Extract form/report bindings
Scan `.form.txt` / `.report.txt` layout files for `RecordSource` (bound to the form/report itself) and `RowSource` (bound to individual controls, typically `ComboBox`/`ListBox`). For each property whose value references the target (as a literal query/table name, or as an inline `SELECT ... FROM <target>` string), record `file`, `control` (or the form/report name itself for `RecordSource`), `property`, and `target`.

### Step 3: Resolve column/table alias lineage
Read the SQL text — either an exported saved-query file, or an inline VBA string literal that references the target. Parse `FROM`/`JOIN` clauses for table names and their aliases (explicit `AS <alias>` or implicit `<Table> <alias>`). Map every qualified column reference (`<alias>.<column>`) to `<Table>.<column>` and add it to `lineage`.

### Step 4: Compute downstream impact
Compile the distinct set of queries, forms/reports, and VBA modules that reference the target (directly, or transitively through a query that reads the target table). Populate `tables_touched` and `downstream_impact`.

### Step 5: Emit output
Format per the Output Contract below.

## Output Contract

| Key | Type | Description |
|---|---|---|
| `query_name` | string | Target table or saved query name being assessed |
| `callers` | array<object> | VBA modules referencing the target with `file`, `line`, `context` |
| `form_bindings` | array<object> | Form/report `RecordSource`/`RowSource` bindings with `file`, `control`, `property`, `target` |
| `tables_touched` | array<string> | Distinct tables referenced by the target SQL |
| `lineage` | array<object> | Column alias→`table.column` resolution mappings with `source` and `resolved` |
| `downstream_impact` | object | Aggregate of `queries`, `forms`, and `vba_callers` affected (transitively) |
| `warnings` | array<string> | `UNALIASED_COLUMN`, `AMBIGUOUS_ALIAS`, and other lineage warnings |

```json
{
  "query_name": "TbRiesgos",
  "callers": [
    { "file": "src/classes/Riesgo.cls", "line": 4131, "context": "Set rcdDatos = getdb().OpenRecordset(m_SQL)" }
  ],
  "form_bindings": [],
  "tables_touched": ["TbRiesgos"],
  "lineage": [
    { "source": "R.IDSuministrador", "resolved": "TbExpedientesSuministradores.IDSuministrador" }
  ],
  "downstream_impact": {
    "queries": [],
    "forms": [],
    "vba_callers": ["Riesgo.cls"]
  },
  "warnings": []
}
```

## Anti-patterns

| Symptom | Fix |
|---|---|
| Ignoring alias lineage and trusting column names verbatim | Parse `FROM`/`JOIN` clauses; emit `UNALIASED_COLUMN` for unresolved references |
| Running without an initialized `.codegraph/` index | Hard-fail `NO_CODEGRAPH_INDEX`; ask the human to run `codegraph init` first |
| Assuming the target is always a base table | Accept both table names and saved `QueryDef` names; branch on `.form.txt`/`.report.txt` and `.sql` presence |
| Guessing when a qualified prefix matches multiple tables | Emit `AMBIGUOUS_ALIAS` and skip resolution for that reference rather than guessing |

## References

- `references/examples.md` — RED test cases (caller tracing, alias resolution with real corpus SQL, form binding — illustrative where the corpus has no exported saved queries).
- Related skills: `vba-handler-backtrace` (control-to-DAO call chains), `vba-event-tracer` (custom event tracing), `vba-symbol-rename` (write-side rename operations — this skill is read-only).
