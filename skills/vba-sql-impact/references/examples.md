# RED tests — vba-sql-impact

Failing tests (RED) that `vba-sql-impact` MUST satisfy. Tests 1-2 use real SQL from the `Gestion_Riesgos` Access project corpus (which builds all SQL as ad-hoc VBA string literals — there is no exported `.sql` QueryDef file or bound `RecordSource`/`RowSource` property anywhere in this corpus). Tests 3-5 (QueryDefs literal reference, form binding, combined downstream impact) are illustrative since this specific corpus has no matching real occurrence of those patterns.

## Test 1: VBA caller tracing (inline SQL literal, real corpus)

**Input**:
```json
{ "target_name": "TbRiesgos" }
```

Real corpus facts, `Riesgo.cls` (`AceptacionRechazo`, lines 4124-4131):
```vb
m_SQL = "SELECT * " & _
        "FROM TbRiesgos " & _
        "WHERE IDRiesgo=" & Me.IDRiesgo & ";"
...
Set rcdDatos = getdb().OpenRecordset(m_SQL)
```

**Expected output** (excerpt):
```json
{
  "query_name": "TbRiesgos",
  "callers": [
    { "file": "src/classes/Riesgo.cls", "line": 4131, "context": "Set rcdDatos = getdb().OpenRecordset(m_SQL)" }
  ],
  "tables_touched": ["TbRiesgos"],
  "warnings": []
}
```

**Pass criteria**: the caller is detected even though the query text is not a literal argument to `OpenRecordset` — the skill MUST resolve the `m_SQL` variable back to its inline-built literal within the same procedure to confirm the table match before reporting the `OpenRecordset` call line as a caller.

## Test 2: Column/table alias resolution (real corpus, implicit aliases)

**Input**:
```json
{ "target_name": "TbExpedientesSuministradores" }
```

Real corpus facts, `Constructor.bas` (~line 5016-5019):
```vb
m_SQL = "SELECT T.* " & _
        "FROM TbExpedientesSuministradores R " & _
        "INNER JOIN TbSuministradores T ON R.IDSuministrador = T.IDSuministrador " & _
        "WHERE R.IDExpediente=" & p_IDExpediente & " " & _
        "AND R.SubContratista='Sí';"
```

**Expected output** (excerpt):
```json
{
  "query_name": "TbExpedientesSuministradores",
  "lineage": [
    { "source": "R.IDSuministrador", "resolved": "TbExpedientesSuministradores.IDSuministrador" },
    { "source": "T.IDSuministrador", "resolved": "TbSuministradores.IDSuministrador" },
    { "source": "R.IDExpediente", "resolved": "TbExpedientesSuministradores.IDExpediente" },
    { "source": "R.SubContratista", "resolved": "TbExpedientesSuministradores.SubContratista" }
  ],
  "tables_touched": ["TbExpedientesSuministradores", "TbSuministradores"],
  "warnings": []
}
```

**Pass criteria**: implicit aliases (`TbExpedientesSuministradores R`, without the `AS` keyword) resolve exactly like explicit `AS` aliases; every qualified reference in the `WHERE` clause is resolved, not just the `FROM`/`JOIN` clauses.

## Test 3: QueryDefs literal reference (illustrative)

**Input**:
```json
{ "target_name": "qryGetRiesgos" }
```

Synthetic setup: a VBA module contains `Set qdf = db.QueryDefs("qryGetRiesgos")`.

**Expected**: `callers` includes an entry with the file, line, and `context: "Set qdf = db.QueryDefs(\"qryGetRiesgos\")"`.

**Pass criteria**: `QueryDefs("...")` string-literal access is detected identically to a literal `OpenRecordset("...")` argument — both are equally valid caller signals.

## Test 4: Form/report binding extraction (illustrative)

**Input**:
```json
{ "target_name": "qryGetRiesgos" }
```

Synthetic setup: `frmRiesgos.form.txt` contains `RecordSource = "qryGetRiesgos"`, and a `ComboBox` control on the same form has `RowSource = "SELECT id, nombre FROM tblUsuarios"`.

**Expected**:
```json
{
  "form_bindings": [
    { "file": "frmRiesgos.form.txt", "control": "frmRiesgos", "property": "RecordSource", "target": "qryGetRiesgos" }
  ]
}
```

Note: the `RowSource` binding on the `ComboBox` targets `tblUsuarios`, NOT `qryGetRiesgos` — it MUST NOT appear in this result set since it does not reference the queried target.

**Pass criteria**: bindings are matched by resolved target, not by co-location on the same form; a form can have bindings to multiple different queries/tables and only the matching ones are returned.

## Test 5: Downstream impact aggregation (illustrative)

**Input**:
```json
{ "target_name": "TbRiesgos" }
```

Synthetic setup: query `qryGetRiesgos` references `TbRiesgos`; form `frmRiesgos` binds `RecordSource` to `qryGetRiesgos`; a VBA module calls `db.OpenRecordset("qryGetRiesgos")`.

**Expected**:
```json
{
  "downstream_impact": {
    "queries": ["qryGetRiesgos"],
    "forms": ["frmRiesgos"],
    "vba_callers": ["<VbaModuleName>"]
  }
}
```

**Pass criteria**: impact is computed transitively — a VBA caller of a query that itself reads the target table is reported as downstream impact of the target table, not just direct callers of the table itself.
