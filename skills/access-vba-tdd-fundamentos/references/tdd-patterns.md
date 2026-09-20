# TDD fundamentos — code patterns

Code behind the rules in SKILL.md.

## Dysflow-friendly wrapper for a generic aggregator

The manifest `procedure` must be a global, unique, argument-less, unqualified `Public Function`.
If a module already has a generic `RunAll`, wrap it:

```vb
Public Function Test_PCSUB_RunAll() As String
    Test_PCSUB_RunAll = RunAll()
End Function
```

## Schema-first — inspect required fields before any INSERT

```vb
Sub InspectarCamposObligatorios(tabla As String)
    Dim tdf As DAO.TableDef, fld As DAO.Field
    Set tdf = GetTestDb().TableDefs(tabla)
    For Each fld In tdf.Fields
        If fld.Required Or Not fld.AllowZeroLength Then
            Debug.Print fld.Name & " [" & fld.Type & "] → OBLIGATORIO"
        End If
    Next fld
End Sub
```

Omitting a `Required` field yields a cryptic DAO error (`Could not update; currently locked`)
indistinguible de un fallo de lógica — the test fails by setup, not by code.

## Inter-test isolation — clean shared working tables before each test

```vb
Private Sub EnsureTableClean(ByVal p_Db As DAO.Database, _
                             ByVal p_TableName As String, _
                             Optional ByVal p_WhereClause As String = "")
    On Error Resume Next
    If Len(p_WhereClause) = 0 Then
        p_Db.Execute "DELETE FROM " & p_TableName, dbFailOnError
    Else
        p_Db.Execute "DELETE FROM " & p_TableName & " WHERE " & p_WhereClause, dbFailOnError
    End If
End Sub

' In the test, BEFORE the Arrange:
Set db = TestHelper.GetTestDb()
Call EnsureTableClean(db, "tbWorkingList")
```

`SeedAll`/`TeardownAll` (shared parent graph) stays intact; `EnsureTableClean` complements it.

## Local JSON wrapper template (top of every test module)

```vb
Private Function BuildOk(ByVal value As Variant, ByRef logs() As String) As String
    BuildOk = Test_Helper.BuildJsonOk(value, logs)
End Function

Private Function BuildFail(ByVal msg As String, ByRef logs() As String) As String
    BuildFail = Test_Helper.BuildJsonFail(msg, logs)
End Function
```

## Signature-match failure mode (§1.10)

When a helper signature changes, every atom that calls it must change in the SAME commit or the
binary compiles but atoms fail at runtime with a type mismatch / wrong-position parameter.

```vb
' Old (wrong) call shape:  (Long p_IDEdicion, ..., p_URLInforme, p_Error, db)
' New helper signature:    p_IDEdicion As String, ..., db As DAO.Database, p_Error As String
```

Protocol: change the helper → `grep` the helper name across all `Test_*.bas` and forms → fix each
call site's types + order (e.g. wrap a `Long` const with `CStr(...)` when it became `String`) →
update the test's header docstring → re-import → do not compile until grep shows zero old-shape
call sites. Detect drift with `verify_code diff:true` cross-referenced against the grep.

## JSON building — never inline

```vb
' ❌ Fragile — one unescaped char breaks parsing
Test_X = "{""ok"":false,""error"":""" & Err.Description & """}"
' ✅ Use the helpers
Test_X = BuildJsonFail(Err.Description, logs)
```

Prefer `Scripting.Dictionary` + `JsonConverter.ConvertToJson` when the project can add the
dependency (handles Unicode/quotes/escapes automatically — what NO_CONFORMIDADES does); otherwise
`EscapeJsonString` + `BuildJsonOk/BuildJsonFail` in a dedicated module. Never JSON inline in test
code.
