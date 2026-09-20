# RED tests — vba-extract-candidates

These are the failing tests (RED) that `vba-extract-candidates` MUST satisfy before being marked production-ready. Each test defines the input contract, expected output structure, and pass criteria.

## Test 1: Procedure > threshold → proposes 2-3 helpers

**Input**:
```json
{
  "procedure_name": "EstablecerDatos",
  "access_path": "<Gestion_Riesgos.accdb bench copy>",
  "threshold_lines": 80
}
```

**Expected output shape**:
```json
{
  "target": { "module": "Form_FormRiesgos...", "name": "EstablecerDatos", "line": 173 },
  "current_signature": "Public Function EstablecerDatos(Optional ByRef p_Error As String) As String",
  "body_size_lines": 142,
  "suggested_helpers": [2 or 3 entries, each { name, line_range, rationale, boundary_respected: true }],
  "coverage": { "total_helper_lines": >= body_size_lines, "overlap": 0, "gaps": 0 }
}
```

**Pass criteria**:
- `body_size_lines > threshold_lines` (142 > 80)
- `suggested_helpers.length` in [2, 3]
- Every helper has `boundary_respected: true`
- `coverage.gaps == 0` AND `coverage.overlap == 0`
- Output latency ≤ 2s

## Test 2: Procedure < threshold → no extraction

**Input**:
```json
{ "procedure_name": "Form_Load_simple", "threshold_lines": 80 }
```

**Expected**:
- `body_size_lines < 80` (e.g., 60)
- `suggested_helpers: null` (not an empty array)
- NO forzado de extracción; el skill declara "no extraction needed"

**Pass criteria**: skill NO propone helpers innecesarios para procedure corto.

## Test 3: Procedure con `With/End With` largo → respeta el bloque

**Input**:
```json
{ "procedure_name": "DoBrowserOps", "threshold_lines": 60 }
```
(Con un `With x.Browser ... End With` de 50 líneas en el cuerpo.)

**Expected**:
- `suggested_helpers` NO parte el bloque `With` a la mitad
- Cada helper propuesto tiene `boundary_respected: true`
- Si fuera imposible partir sin violar el `With`, devuelve `boundary_respected: false` + `gaps > 0` para que humano decida

**Pass criteria**: respeto de boundaries VBA sin partidos a medias.

## Test 4: Procedure inexistente

**Input**:
```json
{ "procedure_name": "ProcedimientoFantasma" }
```

**Expected**:
- Pre-validation hard-fail con `procedure_name` referenciado en el error
- Exit code != 0
- NO propuesta de helpers

**Pass criteria**: error tipado, no respuesta vacía.
