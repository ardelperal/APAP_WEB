# RED tests — vba-symbol-rename

Failing tests (RED) that `vba-symbol-rename` MUST satisfy before production. Each test defines the input, expected output, and pass criteria.

## Test 1: Procedure con 3 callers cross-module (plan mode)

**Input**:
```json
{
  "symbol_name": "Form_FormX.OldName",
  "new_name": "NewName",
  "mode": "plan"
}
```
(El procedure tiene 3 callers: 2 en `Form_FormX.cls` y 1 en `modY.bas`.)

**Expected output shape**:
```json
{
  "target": {
    "kind": "function",
    "module": "Form_FormX",
    "name": "OldName",
    "qualified": "Form_FormX.OldName"
  },
  "impact_entries": [
    { "file": "src/forms/Form_FormX.cls", "line": 165, "current_text": "OldName m_Error", "qualified": "Form_FormX.Form_Load" },
    { "file": "src/forms/Form_FormX.cls", "line": 231, "current_text": "Call OldName()", "qualified": "Form_FormX.cmdSave_Click" },
    { "file": "src/modules/modY.bas", "line": 87, "current_text": "result = OldName()", "qualified": "modY.SomeCaller" }
  ],
  "total_changes": 3,
  "token_estimate": 480,
  "warnings": []
}
```

**Pass criteria**:
- `impact_entries.length == 3`
- Cada entry tiene `file`, `line`, `current_text`, `qualified` resueltos
- `total_changes == 3`
- Output latency ≤ 2s

## Test 2: Procedure sin callers (plan mode)

**Input**:
```json
{ "symbol_name": "Form_FormX.UnusedHelper", "new_name": "NewName", "mode": "plan" }
```

**Expected**:
- `impact_entries: []`
- `warnings: [{ "reason_code": "NO_CALLERS", "message": "this symbol has no callers; consider deletion instead of rename" }]`

**Pass criteria**: skill NO recomienda el rename ciegamente — sugiere borrado en su lugar si no hay callers.

## Test 3: Target ambiguo (overloads)

**Input**:
```json
{ "symbol_name": "DoSomething", "new_name": "DoSomethingElse", "mode": "plan" }
```
(Existen `Sub DoSomething()` y `Sub DoSomething(ByVal i As Long)`.)

**Expected**:
- Pre-validation hard-fail con `reason_code: "PROCEDURE_AMBIGUOUS"`
- Output incluye `candidates: [{ qualified: "modA.DoSomething()", signature: "Sub DoSomething()" }, { qualified: "modA.DoSomething(i)", signature: "Sub DoSomething(ByVal i As Long)" }]`

**Pass criteria**: skill pide desambiguación antes de planear, no asume.

## Test 4: Source race entre plan y apply

**Input**:
```json
{
  "plan_run_id": "precomputed-id-abc",
  "symbol_name": "Form_FormX.OldName",
  "new_name": "NewName",
  "mode": "apply"
}
```
(Source cambió entre el `plan` y el `apply` — el caller en línea 165 ya no llama `OldName`, ahora llama `OldMethod`.)

**Expected**:
- Hard-fail `reason_code: "SOURCE_CHANGED"`
- Output incluye `diff_summary: [{ file: "src/forms/Form_FormX.cls", line: 165, before: "OldName m_Error", after: "OldMethod m_Error" }]`
- NINGÚN cambio aplicado (verificación pre-flight previo a write)

**Pass criteria**: race protection prevented corruption. Skill NO aplica nada si el snapshot no matchea.

## Test 5: apply con binary not compiled

**Input**:
```json
{
  "symbol_name": "Form_FormX.OldName",
  "new_name": "NewName",
  "mode": "apply",
  "access_path": "<.accdb with compile error>"
}
```

**Expected**:
- Hard-fail `reason_code: "BINARY_NOT_COMPILED"`
- Output incluye `suggestion: "run COMPILE_VBA_REMOVED_v1.19.0 before apply"`
- NINGÚN cambio aplicado

**Pass criteria**: skill NO aplica rename si el binario no compila (evita dejar el .accdb en estado roto).

## Test 6: apply con colisión (new_name ya existe)

**Input**:
```json
{
  "symbol_name": "Form_FormX.OldName",
  "new_name": "NewName",
  "mode": "apply"
}
```
(`NewName` ya existe como procedure en `modZ`.)

**Expected**:
- Hard-fail `reason_code: "NAME_COLLISION"`
- Output incluye `existing_qualified: "modZ.NewName"` + `existing_kind: "function"`
- NINGÚN cambio aplicado

**Pass criteria**: skill NO aplica y deja decisión al humano (incluyendo desambiguación o rename del nuevo collider).

## Test 7: apply con event handlers en forms

**Input**:
```json
{
  "symbol_name": "Form_FormY.cmdDelete",
  "new_name": "cmdDeleteItem",
  "mode": "apply"
}
```
(`cmdDelete` está expuesto como event handler `cmdDelete_Click` por convención VBA, pero el procedure real se llama `cmdDelete` y el handler está separado.)

**Expected**:
- `impact_entries` (en plan): incluye el handler wiring detectado por heurística `form_event_handler_name_convention`
- `apply` exitoso: el handler sigue apuntando al nuevo nombre sin romper

**Pass criteria**: rename de un control/procedure captura BOTH el call site explícito Y el wiring del handler. 0% false negatives en `form_instance_control_refs`.

## Test 8: Idempotencia — correr 2 veces seguidas produce mismo result

**Input**:
```json
{ "symbol_name": "Form_FormX.OldName", "new_name": "NewName", "mode": "plan" }
```
(Correr el mismo `plan` 2 veces seguidas sin cambios en source.)

**Expected**:
- Ambos runs retornan `impact_entries` idénticos (módulo, file, line, current_text)
- Output 1 y Output 2 byte-equivalent (excluyendo timestamps si los hubiera)

**Pass criteria**: skill no acumula state entre invocaciones; el plan es puro sobre el estado actual del source.

## Test 9: Símbolo en string literal NO es caller

**Input**:
```json
{ "symbol_name": "Form_FormX.OldName", "new_name": "NewName", "mode": "plan" }
```
(Aparece solo en `' Comentario sobre OldName '` y `' MsgBox "OldName" '`.)

**Expected**:
- `impact_entries: []` (strings y comments NO son callers)
- `warnings: [{ "reason_code": "STRING_LITERAL_ONLY", "message": "symbol appears only in string literals / comments" }]`

**Pass criteria**: skill distingue entre matches textuales (irrelevantes) y calls reales (relevantes).
