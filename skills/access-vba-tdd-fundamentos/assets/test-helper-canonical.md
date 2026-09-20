# Canonical VBA test helpers

## JSON result contract

Every callable atom is a public, argument-less `Function ... As String` that returns
`{ok,value,payload,error,logs}`. Centralize escaping; never build error JSON ad hoc.

```vb
Public Function BuildJsonOk(ByVal value As Variant, ByRef logs() As String) As String
    BuildJsonOk = "{""ok"":true,""value"":" & JsonValue(value) & _
        ",""payload"":null,""error"":null,""logs"":" & JsonStringArray(logs) & "}"
End Function

Public Function BuildJsonFail(ByVal message As String, ByRef logs() As String) As String
    BuildJsonFail = "{""ok"":false,""value"":null,""payload"":null,""error"":""" & _
        EscapeJsonString(message) & """,""logs"":" & JsonStringArray(logs) & "}"
End Function

Public Function EscapeJsonString(ByVal value As String) As String
    value = Replace(value, "\", "\\")
    value = Replace(value, """", "\""")
    value = Replace(value, vbCrLf, "\n")
    value = Replace(value, vbCr, "\n")
    value = Replace(value, vbLf, "\n")
    EscapeJsonString = value
End Function
```

## Session and database helpers

`BeginTestSession` must validate the configured sandbox before setting test mode. It
invalidates the production database cache, stores the sandbox path/password, and calls
`Test_EVE(True)`. `EndTestSession` calls `Test_EVE(False)`. The final teardown calls
`ResetTestSession`; its complete contract lives in
`../../access-vba-tdd-sandbox/references/test-session-safety.md`.

`GetTestDb` may cache only the sandbox handle while test mode is active. `CloseTestDb`
and the project-specific `CloseGetdbCache` must close and clear their object variables.

## Isolated database helper

Use `DBEngine.Workspaces(0).CreateDatabase(tempPath, dbLangGeneral, dbVersion120)` to
create a fresh database. The caller creates only the required schema, closes the DAO
handle, deletes the file in teardown, and proves both the positive write location and
the absence of leakage into the persistent sandbox.

## Cardinality helper

`CountRows(db, tableName, whereClause)` opens a snapshot over `SELECT COUNT(*)` and is
used before and after every mutation. It must not silently turn a query failure into a
passing assertion; callers treat helper errors as test failures.
