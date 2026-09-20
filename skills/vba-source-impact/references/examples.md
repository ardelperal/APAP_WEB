# RED tests — vba-source-impact

Failing tests (RED) that `vba-source-impact` MUST satisfy before production.

## Test 1: Procedure con refs UI ocultas (`Me.X`) en otros forms

**Input**:
```json
{ "target": "Form_FormRiesgos.EstablecerDatos", "scope": "source-only" }
```
(`Me.txtCodigoRiesgo` referenciado en otros 2 forms.)

**Expected output shape**:
```json
{
  "target": "Form_FormRiesgos.EstablecerDatos",
  "parsed": { "kind": "function", "module": "Form_FormRiesgos", "line": 173 },
  "direct_callers": [...],
  "direct_callees": [...],
  "form_instance_control_refs": [
    { "form": "Form_OtherA", "control_name": "txtCodigoRiesgo", "line_in_cls": 42 }
  ],
  "event_handlers_via_control_name_convention": [
    { "form": "Form_OtherA", "control": "txtCodigoRiesgo", "handler": "txtCodigoRiesgo_BeforeUpdate" }
  ],
  "affected_files": ["src/forms/Form_FormRiesgos.cls", "src/forms/Form_OtherA.cls", ...],
  "related_tests": [{ "name": "...", "procedure": "...", "tag": "..." }]
}
```

**Pass criteria**:
- `form_instance_control_refs` NO vacía si hay refs `Me.X`
- `event_handlers_via_control_name_convention` detecta handlers `_Click`, `_BeforeUpdate`, etc.
- `affected_files` incluye el target + cada archivo donde hay refs
- `related_tests` lista los `Test_*` que llaman al área (no solo importan el módulo)
- Output ≤ 500 tokens, latency ≤ 2s

## Test 2: Wildcard con >100 matches → no expande

**Input**:
```json
{ "target": "modRiesgos.*" }
```

**Expected**:
- `parsed.kind: "wildcard_match_count"`, `count: >100`
- `wildcard_warning: "target too broad, please narrow"`
- NO expansión de los >100 nodos

**Pass criteria**: skill aborta con target amplio, no devuelve un reporte gigante.

## Test 3: Codegraph index stale >1h → warn pero sigue

**Input**:
```json
{ "target": "..." }
```
(Codegraph index fue refrescado hace >1h.)

**Expected**:
- Output incluye `index_stale: true` con last_sync timestamp
- `warnings: [{ "reason_code": "INDEX_STALE", "recommendation": "run vba-binary-sync before evaluating" }]`

**Pass criteria**: warning explícito sin romper el flow.

## Test 4: Target con refs circulares (A → B → A)

**Input**:
```json
{ "target": "ModuleA.FuncA" }
```
(`FuncA` llama `FuncB`, que llama `FuncA`.)

**Expected**:
- Output tiene `cycle_detected: true`
- Reporta la cadena circular

**Pass criteria**: no cae en loop infinito; flag `cycle_detected` claro.
