# RED tests — vba-handler-backtrace

Failing tests (RED) that `vba-handler-backtrace` MUST satisfy. Tests 1-3 use a real call chain from the `Gestion_Riesgos` Access project corpus; Tests 4-5 (cycle detection, depth cap) are illustrative synthetic scenarios since no genuine mutual-recursion or 6+-level chain was found rooted at a single control handler in this corpus.

## Test 1: Happy path — control to handler to DAO call

**Input**:
```json
{ "control": "ComandoRechazar" }
```

Real corpus facts: button `ComandoRechazar` in `Form_FormCalidadRiesgoAceptadoRetiradoVisado.cls` wires to `Private Sub ComandoRechazar_Click()` (line 87), which calls `m_ObjRiesgoActivo.AceptacionRechazo m_EstadoRiesgo, Date, m_Error` (line 98). `Riesgo.AceptacionRechazo` (`Riesgo.cls`, line 4095) performs `Set rcdDatos = getdb().OpenRecordset(m_SQL)` at line 4131.

**Expected output**:
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

**Pass criteria**: full 3-level path resolved (`control` -> `event` -> `function`); `sql_hint` and `parameters` populated on the correct node; execution under 150ms.

## Test 2: DAO query string reconstruction from multiline concatenation

**Input**:
```json
{ "handler": "Riesgo.AceptacionRechazo" }
```

Real corpus facts, `Riesgo.cls` lines 4124-4126:
```vb
m_SQL = "SELECT * " & _
        "FROM TbRiesgos " & _
        "WHERE IDRiesgo=" & Me.IDRiesgo & ";"
```

**Expected**: the node for `AceptacionRechazo` carries `"sql_hint": "SELECT * FROM TbRiesgos WHERE IDRiesgo=<IDRiesgo>;"` — the three continuation lines are concatenated into a single reconstructed literal, with the dynamic `Me.IDRiesgo` expression rendered as a placeholder token (`<IDRiesgo>`) rather than omitted.

**Pass criteria**: reconstruction spans all `_`-continued lines; quoted literal segments are joined in source order; result truncated to 200 characters if it exceeds that length (not the case here — this hint is well under the cap).

## Test 3: UDT parameter mapping (enum type)

**Input**:
```json
{ "handler": "Riesgo.AceptacionRechazo" }
```

Real corpus facts, `Riesgo.cls` line 4095-4099:
```vb
Public Function AceptacionRechazo( _
                                        Optional ByRef p_Estado As EnumRiesgoEstado, _
                                        Optional p_Fecha As String, _
                                        Optional ByRef p_Error As String _
                                        ) As String
```

**Expected**: `"parameters": [{ "name": "p_Estado", "type": "EnumRiesgoEstado" }]` — `p_Fecha` and `p_Error` are excluded because `String` is a VBA primitive; `EnumRiesgoEstado` survives because it is a project-defined enum, not a primitive.

**Pass criteria**: primitive-typed parameters never appear in `parameters`; custom/enum types always do; parameter order in the array matches declaration order for the surviving parameters.

## Test 4: Cycle detection (illustrative)

**Input**:
```json
{ "handler": "SubA" }
```

Synthetic setup: `SubA` calls `SubB`, and `SubB` calls back into `SubA`.

**Expected**:
```json
{
  "tree": {
    "id": "SubA",
    "name": "SubA",
    "kind": "function",
    "parameters": [],
    "children": [
      {
        "id": "SubB",
        "name": "SubB",
        "kind": "function",
        "parameters": [],
        "children": [
          { "id": "SubA", "name": "SubA", "kind": "function", "cycle_detected": true, "children": [] }
        ]
      }
    ]
  },
  "cycle_detected": true,
  "warnings": []
}
```

**Pass criteria**: the second occurrence of `SubA` is included as a leaf tagged `cycle_detected: true` and is NOT expanded again; top-level `cycle_detected` mirrors the presence of any tagged node; traversal terminates without recursion errors.

## Test 5: Depth cap and truncation warning (illustrative)

**Input**:
```json
{ "handler": "Sub1", "max_depth": 5 }
```

Synthetic setup: `Sub1 -> Sub2 -> Sub3 -> Sub4 -> Sub5 -> Sub6`, a 6-level chain.

**Expected**: the tree expands through `Sub5` (depth 5) and stops; `Sub6` is not included as a child of `Sub5`. Top-level `warnings` contains `"MAX_DEPTH_EXCEEDED"`.

**Pass criteria**: traversal never exceeds `max_depth`; the warning is a trace-level signal in the top-level `warnings` array, not attached to an individual node (contrast with `CYCLE_DETECTED`, which is per-node).
