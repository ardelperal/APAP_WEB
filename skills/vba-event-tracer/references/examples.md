# RED tests — vba-event-tracer

Failing tests (RED) that `vba-event-tracer` MUST satisfy. Entities are drawn from the `Gestion_Riesgos` Access project corpus wherever the spec scenario has a real match; the circular-reference case is illustrative (no genuine mutual-subscription cycle exists in this corpus, since that pattern is an anti-pattern the codebase avoids).

Test 1 validates the **v1.11.0+ runtime path**: the `m_FormNC_NCRegistrada` handler must be
returned via a direct `event-handler` edge in the graph, not via the pre-v1.11.0 procedure-name
walk. A v1.10.0 runtime against the same corpus would return the same handler via the walk;
both paths converge on the same contract output, so the test fixtures are stable across
runtime versions.

## Test 1: Happy path — declaration, raise site, and WithEvents handler

**Input**:
```json
{ "event_name": "NCRegistrada" }
```

Real corpus facts: `Form_FormRiesgoNC.cls` declares `Public Event NCRegistrada()` at line 5 and raises it at line 52 inside `ComandoRegistrar_Click`. `Form_FormCalidadRiesgoMaterializaciones.cls` declares `Private WithEvents m_FormNC As Form_FormRiesgoNC` (line 3) and defines `Private Sub m_FormNC_NCRegistrada()` at line 591.

**Expected output**:
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

**Pass criteria**: all three arrays populated with the exact real module/line/signature values; `warnings` empty; execution under 100ms.

## Test 2: Ambiguity — same event name declared in two classes

**Input**:
```json
{ "event_name": "AnexoAñadido" }
```

Real corpus facts: both `Form_FormAnexos.cls` (line 23) and `Form_FormAnexos1.cls` (line 15) declare `Public Event AnexoAñadido(ByVal p_ObjAnexo As Anexo)`. The query is unqualified.

**Expected output**:
```json
{
  "event_declarations": [],
  "raise_sites": [],
  "handlers": [],
  "warnings": ["EVENT_AMBIGUOUS: Event name 'AnexoAñadido' is ambiguous. Candidates: Form_FormAnexos.AnexoAñadido, Form_FormAnexos1.AnexoAñadido"]
}
```

**Pass criteria**: skill stops immediately on ambiguity detection; does NOT guess a candidate; all trace arrays stay empty; qualifying the query as `"Form_FormAnexos AnexoAñadido"` resolves it to a single candidate on retry.

## Test 3: No raisers

**Input**:
```json
{ "event_name": "NoHayCambios" }
```

Real corpus facts: `Proyecto.cls` declares `Public Event NoHayCambios()` at line 13, but no `RaiseEvent NoHayCambios` call site exists anywhere in the project.

**Expected output**:
```json
{
  "event_declarations": [
    { "module": "Proyecto.cls", "line": 13, "signature": "Public Event NoHayCambios()" }
  ],
  "raise_sites": [],
  "handlers": [],
  "warnings": ["NO_RAISERS"]
}
```

**Pass criteria**: skill does not fail hard on zero raise sites — it reports the declaration and flags `NO_RAISERS` as a warning, letting the caller decide whether the event is dead code.

## Test 4: Circular WithEvents subscription (illustrative — no real match in this corpus)

**Input**:
```json
{ "event_name": "ClassA.Changed" }
```

Synthetic setup: `ClassA` declares `Public Event Changed()` and holds `WithEvents m_B As ClassB`; `ClassB` declares `Public Event Changed()` and holds `WithEvents m_A As ClassA`. Each class's `Changed` handler for the other calls back into a path that would re-trigger the same trace.

**Expected behavior**: the loop guard (visited `(module, event)` tuples) prevents infinite recursion. The trace completes and returns a `handlers` entry for the one resolved handler direction requested, without hanging or exceeding the 100ms budget.

**Pass criteria**: no stack overflow, no timeout; the visited-set check is exercised at least once and the trace terminates deterministically.

## Test 5: Qualified query bypasses ambiguity

**Input**:
```json
{ "event_name": "Form_FormAnexos1 AnexoEliminado" }
```

Real corpus facts: `Form_FormAnexos1.cls` declares `Public Event AnexoEliminado(ByVal IDAnexo As String)` at line 16 and raises it at line 306 inside its delete handler. `Form_FormAnexos.cls` also declares the same event name but is excluded because the query is qualified.

**Expected output**:
```json
{
  "event_declarations": [
    { "module": "Form_FormAnexos1.cls", "line": 16, "signature": "Public Event AnexoEliminado(ByVal IDAnexo As String)" }
  ],
  "raise_sites": [
    { "module": "Form_FormAnexos1.cls", "line": 306, "context": "Private Sub cmdEliminarAnexo_Click()" }
  ],
  "handlers": [],
  "warnings": []
}
```

Note: `raise_sites` is non-empty here so `NO_RAISERS` MUST NOT be emitted. `handlers: []` and `NO_RAISERS` are independent signals — a handler-resolution implementation MUST NOT infer one from the other; `NO_RAISERS` only fires when `raise_sites` itself is empty (see Test 3).

**Pass criteria**: qualification disambiguates without requiring a hard-fail; `event_declarations` and `raise_sites` reflect only the qualified class; no spurious warnings.
