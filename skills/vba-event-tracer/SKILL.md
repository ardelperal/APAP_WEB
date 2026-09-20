---
name: vba-event-tracer
description: Trigger: trace VBA event X, find event handlers for X, who raises event X, who listens to event X. Traces a custom VBA event to its declaration, RaiseEvent call sites, and dynamically resolved WithEvents handlers using the codegraph index.
license: Apache-2.0
status: active
requires: codegraph MCP (codegraph_explore) with an initialized .codegraph/ index for the target VBA/Access project; v1.11.0+ runtime recommended for the direct event-handler edge
metadata:
  author: Andrés Román
  version: 1.1.0
  last_verified: 2026-08-22
  scope: ['vba', 'runtime']
  auto_invoke: ['tracing a VBA event to its handler']
  tiers: ['vba', 'runtime']
---



# vba-event-tracer

Traces a custom VBA event (declared with `Public Event`) to its declaration site, every `RaiseEvent` call site, and every subscriber handler resolved dynamically through `WithEvents` wiring. Read-only bisturí: one event name in, one structured JSON trace out.

## Activation Contract

- Input: `event_name` (unqualified, e.g. `"NCRegistrada"`) or qualified as `"<ClassOrModule> <EventName>"` (e.g. `"Form_FormRiesgoNC NCRegistrada"`) when the caller already knows the declaring class.
- Output: a single JSON object (see Output Contract), target budget under 500 tokens. No writes, no side effects.
- This skill does NOT trace built-in Access form/control events (`Form_Load`, `_Click`, etc.) — those are ordinary procedures, not `Public Event` declarations. Use `vba-handler-backtrace` for control-event call chains instead.

## Hard Rules

- **HR-1. Codegraph index required**: The target project directory MUST have a `.codegraph/` index.
- **HR-2. Hard-fail on missing index**: If absent, hard-fail with `NO_CODEGRAPH_INDEX` and report that `codegraph init <project-path>` must run first.
- **HR-3. No grep fallback**: This skill is a precise graph probe, not a text search tool. Do not fall back to ad-hoc grep scanning.

## Decision Gates

| Situation | Action |
| --- | --- |
| Query is unqualified and matches `event` nodes in 2+ distinct classes/modules | Hard-stop, return `EVENT_AMBIGUOUS` warning with `Class.EventName` candidates; leave `event_declarations`, `raise_sites`, `handlers` empty |
| Resolved event has zero incoming `raises-event` edges | Append `NO_RAISERS` to `warnings`, continue with empty `raise_sites` |
| A `(module, event)` tuple is revisited during traversal | Abort that branch (loop guard); do not recurse further |
| `.codegraph/` index missing for `projectPath` | Hard-fail `NO_CODEGRAPH_INDEX` |
| Event name not found anywhere in the graph | Hard-fail `EVENT_NOT_FOUND` |

## Execution Steps

### Step 1: Query the graph
Invoke `codegraph_explore` with `query` set to the event name (qualified if given) and `projectPath` set to the target project root. The tool returns matching event-declaration nodes plus their incoming `raises-event` edges and their `event-handler` edges (handler procedure → raiser site). On runtimes older than v1.11.0 the `event-handler` edge is not materialized and Step 5 must walk the procedure-name convention; on v1.11.0+ the edge is present directly.

### Step 2: Ambiguity check
Filter returned nodes for `kind: "event"` whose simple name matches `event_name` (case-insensitive). If the query was unqualified and 2+ distinct declaring classes match, stop immediately: emit `EVENT_AMBIGUOUS` with the qualified candidates (e.g. `Form_FormAnexos.AnexoAñadido`, `Form_FormAnexos1.AnexoAñadido`) and return early — do not guess which one the caller meant.

### Step 3: Declaration extraction
For the single resolved event node, record `module` (file basename), `line` (`startLine`), and `signature` (the trimmed `Public Event ...` declaration line).

### Step 4: Raise site resolution
For every incoming `raises-event` edge, resolve the source procedure: `module` (file basename), `line` of the `RaiseEvent` statement, and `context` (the enclosing procedure's declaration signature). If none exist, append `NO_RAISERS` to `warnings`.

### Step 5: Dynamic handler resolution

**v1.11.0+ runtime** — every `event-handler` edge returned in Step 1 already names the
handler procedure on one side and the `RaiseEvent` site on the other. Read the edge
metadata: the handler-side `module` becomes `form`, the handler-procedure name
becomes `handler`, and the `WithEvents` subscription variable comes from
`edge.metadata.variableName` (becomes `via`). No procedure-name walk needed.

**Pre-v1.11.0 runtime (legacy walk, kept for compatibility only)** — find every
`subscribes-event` edge targeting the event's declaring class. For each subscribing
module, read `edge.metadata.variableName` (the `WithEvents` variable, e.g. `m_FormNC`),
then look for a procedure named `<VariableName>_<EventName>` (case-insensitive) inside
that module. On a match, record `form` (subscribing module basename), `handler` (exact
procedure name), `via` (the subscription variable name). This three-hop walk is what
the v1.11.0 `event-handler` edge replaced.

### Step 6: Loop guard
Track visited `(module, event)` tuples during traversal. Never revisit a tuple already seen in this trace — this prevents infinite recursion when two classes subscribe to each other's events, and keeps the trace under 100ms.

### Step 7: Emit output
Format the result per the Output Contract below. Do not include intermediate graph data, raw node payloads, or explanatory prose in the response.

## Output Contract

| Key | Type | Description |
|---|---|---|
| `event_declarations` | `array<object>` | All `Public Event` declarations matching the query, each with `module`, `line`, `signature`. |
| `raise_sites` | `array<object>` | Every `RaiseEvent` call site, each with `module`, `line`, and enclosing procedure `context`. |
| `handlers` | `array<object>` | Subscribed handlers, each with `form`, `handler` procedure name, and `via` (the `WithEvents` subscription variable). |
| `warnings` | `array<string>` | Non-fatal signals (e.g. `EVENT_AMBIGUOUS`, `NO_RAISERS`); on hard-fail, contains the typed error. |

Happy-path shape:

```json
{
  "event_declarations": [
    { "module": "Form_FormRiesgoNC.cls", "line": 5, "signature": "Public Event NCRegistrada()" }
  ],
  "raise_sites": [
    { "module": "Form_FormRiesgoNC.cls", "line": 52, "context": "Private Sub ComandoRegistrar_Click()" }
  ],
  "handlers": [
    { "form": "Form_FormCalidadRiesgoMaterializaciones.cls", "handler": "m_FormNC_NCRegistrada", "via": "m_FormNC" }
  ],
  "warnings": []
}
```

On ambiguity, the shape collapses to:

```json
{
  "event_declarations": [],
  "raise_sites": [],
  "handlers": [],
  "warnings": ["EVENT_AMBIGUOUS: Event name 'AnexoAñadido' is ambiguous. Candidates: Form_FormAnexos.AnexoAñadido, Form_FormAnexos1.AnexoAñadido"]
}
```

## Runtime contract

Requires the codegraph-vba MCP. The handler-resolution path differs between the v1.11.0+
runtime, which materializes `event-handler` edges at index time, and pre-v1.11.0 runtimes,
which require the procedure-name walk in Step 5. Re-fetch `codegraph upgrade --check`
before trusting either path — version your index with the runtime that built it.

## References

- `references/examples.md` — RED test cases (happy path, ambiguity, no-raisers, circular subscription).
- Related skills: `vba-handler-backtrace` (control-event call chains down to DB operations), `vba-sql-impact` (table/query impact analysis), `vba-symbol-rename` (write-side rename operations — this skill is read-only).

## Anti-patterns

| Symptom | Fix |
|---|---|
| Tracing built-in Access form/control events (`Form_Load`, `X_Click`, etc.) with this skill | Use `vba-handler-backtrace`; this skill only traces `Public Event` declarations, not ordinary procedures |
| Falling back to ad-hoc grep scanning when `.codegraph/` index is missing | Hard-fail with `NO_CODEGRAPH_INDEX` and require `codegraph init <project-path>` first; this is a precise graph probe, not a text search tool |
| Tracing public events of system libraries (DAO, VBA, Access, etc.) | Decline and warn — these are runtime-object receivers, never user code; declare the boundary in the skill |
| Recursing into `(module, event)` tuples already visited in the same trace | Use the loop guard: each visited tuple is terminal for that branch; without it, two mutually-subscribing classes loop forever |
