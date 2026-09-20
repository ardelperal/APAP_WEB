# vba-access — code patterns

Copy-adapt patterns behind the rules in SKILL.md. Ready-to-use full files live in `examples/`.

## Error handling — `On Error GoTo` + single exit

```vb
Public Sub Ejemplo()
    On Error GoTo EH
    ' ... main work ...
SALIR:
    Exit Sub
EH:
    ' handle / re-raise
    Resume SALIR
End Sub
```

Use `On Error Resume Next` only around a tiny block where failure is expected and `Err` is
checked immediately. If you re-raise, do NOT also `Resume SALIR` in the same branch — execution
stops at the re-raise.

## Telefónica D&S — `p_Error ByRef` propagation

Every public `Function`/`Sub` ends with `Optional ByRef p_Error As String` as the LAST parameter.
On failure set `p_Error` and `Err.Raise` (original code, or `1000` for functional errors). The
caller checks `p_Error` after every call and re-propagates if non-empty. Errors travel through
`p_Error`; a JSON body carries valid data only. (Exception: `condor` does not use this — match the
project's existing signatures. `hps` uses `Optional ByRef p_Db As DAO.Database`.)

```vb
Public Function MyFunction(ByVal param1 As String, Optional ByRef p_Error As String) As String
    p_Error = ""
    On Error GoTo errores
    Dim result As String
    result = InnerFunction(param1, p_Error)
    If p_Error <> "" Then Err.Raise Err.Number, "MyFunction", p_Error
    MyFunction = result
    Exit Function
errores:
    p_Error = "MyFunction: " & Err.Description
    Err.Raise Err.Number, "MyFunction", p_Error
End Function
```

```vb
Dim errMsg As String, json As String
json = MyFunction(param1, errMsg)
If errMsg <> "" Then Exit Function   ' re-propagate or handle
```

## DAO + parameterized QueryDef

```vb
Dim db As DAO.Database, qdf As DAO.QueryDef, rs As DAO.Recordset
Set db = CurrentDb
Set qdf = db.CreateQueryDef(vbNullString, _
    "PARAMETERS p_ID LONG; SELECT * FROM TbEventos WHERE ID = [p_ID]")
qdf.Parameters("p_ID").Value = lngEventoId
Set rs = qdf.OpenRecordset(dbOpenDynaset)
```

## Memo / Long Text > 255 chars — editable recordset, not a string parameter

```vb
Dim db As DAO.Database, rs As DAO.Recordset
Set db = CurrentDb
Set rs = db.OpenRecordset("TbDocumentos", dbOpenDynaset)
rs.AddNew
rs!Titulo = strTitulo
rs!ContenidoLargo = strContenidoMemo   ' >255: assign directly
rs.Update
rs.Close: Set rs = Nothing: Set db = Nothing
```

## Object cleanup

```vb
If Not rs Is Nothing Then
    rs.Close
    Set rs = Nothing
End If
```

## Declaration ordering — anti-pattern vs correct

Consts scattered between procedures cause "Private Const in the middle of a module" compile
errors on source↔binary drift. All declarations at the top:

```vb
' Header (Attribute VB_Name, Option Compare/Explicit, comment)
Private Const FIX_ID As Long = 900001   ' all consts first
Private Function BuildOk(...)            ' then private helpers
Private Sub SeedFixture(...)
Public Function Test_Atom_Happy()        ' then public procedures
```

## 64-bit-safe Windows API (centralize in `modAPIDeclaraciones`)

```vb
#If VBA7 Then
    #If Win64 Then
        Public Declare PtrSafe Function FindWindow Lib "user32" Alias "FindWindowA" ( _
            ByVal lpClassName As String, ByVal lpWindowName As String) As LongPtr
    #Else
        Public Declare PtrSafe Function FindWindow Lib "user32" Alias "FindWindowA" ( _
            ByVal lpClassName As String, ByVal lpWindowName As String) As Long
    #End If
#Else
    Public Declare Function FindWindow Lib "user32" Alias "FindWindowA" ( _
        ByVal lpClassName As String, ByVal lpWindowName As String) As Long
#End If
```

## Recommended module template

```vb
Option Compare Database
Option Explicit

Public Sub EjemploOperacion()
    On Error GoTo EH
    Dim db As DAO.Database, rs As DAO.Recordset, lngId As Long
    Set db = CurrentDb
    Set rs = db.OpenRecordset("SELECT ID FROM TbEjemplo", dbOpenDynaset)
SALIR:
    If Not rs Is Nothing Then rs.Close: Set rs = Nothing
    Set db = Nothing
    Exit Sub
EH:
    Debug.Print "EjemploOperacion -> Err " & Err.Number & " - " & Err.Description
    Resume SALIR
End Sub
```

## Official Microsoft sources

Option Explicit, Declaring variables, Using data types efficiently, Creating object variables,
Elements of run-time error handling (Access VBA), and Choosing ADO or DAO — all on
learn.microsoft.com. The VB.NET conventions page helps with layout but its `Try...Catch` model
does not apply to classic VBA; prefer `On Error` guidance.
