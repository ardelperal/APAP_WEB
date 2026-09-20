# Canonical E2E example — fat handler → thin form + decoupled helper + atom + UAT card

This is the single worked example of the whole methodology. When in doubt about what "good" looks like, copy this shape. The feature: **saving a RAC dictamen requires a non-empty `racDecision`.**

---

## 0. Before (wrong) — business logic inside the form

```vb
' Form_subfrmDatosPCSUB_DictamenRAC.cls  ❌ untestable
Private Sub cmdGuardar_Click()
    If Len(Trim$(Me.txtRacDecision & "")) = 0 Then
        MsgBox "El campo Decisión es obligatorio", vbExclamation
        Exit Sub
    End If
    Dim db As DAO.Database: Set db = getdb()
    db.Execute "UPDATE TbDictamenRAC SET racDecision='" & Me.txtRacDecision & _
               "' WHERE idSolicitud=" & Me.idSolicitud, dbFailOnError
    MsgBox "Datos guardados", vbInformation
End Sub
```

Why it fails the methodology: validation rule, SQL, and the `MsgBox` all live in an event handler. COM cannot run it; the rule cannot be unit-tested; UAT would test blind.

---

## 1. The helper (decoupled, honest signature)

Decision rule for `db`: *would removing `db` change what the helper returns?* Persisting a row needs DAO → `db` is required (injected, optional default `Nothing`). The `MsgBox` becomes a `ByRef p_PromptResult` seam so atoms assert the message without a modal blocking COM.

```vb
' modDictamenRACHelper.bas
Attribute VB_Name = "modDictamenRACHelper"
Option Compare Database
Option Explicit

' Persists a RAC dictamen. racDecision is mandatory.
' Returns True on success; sets p_PromptResult to the message the form must show.
Public Function DictamenRAC_Guardar(ByVal p_IdSolicitud As Long, _
                                    ByVal p_RacDecision As String, _
                                    Optional ByRef db As DAO.Database = Nothing, _
                                    Optional ByRef p_PromptResult As String = "") As Boolean
    If db Is Nothing Then Set db = getdb()
    If Len(Trim$(p_RacDecision)) = 0 Then
        p_PromptResult = "El campo Decisión es obligatorio"
        DictamenRAC_Guardar = False
        Exit Function
    End If
    db.Execute "UPDATE TbDictamenRAC SET racDecision=" & SqlStr(p_RacDecision) & _
               " WHERE idSolicitud=" & p_IdSolicitud, dbFailOnError
    p_PromptResult = "Datos guardados"
    DictamenRAC_Guardar = True
End Function
```

Public name is prefixed (`DictamenRAC_Guardar`) → collision-proof (see `references/helper-naming.md`). Module name ≠ function name.

---

## 2. After (correct) — the form is thin wiring

```vb
' Form_subfrmDatosPCSUB_DictamenRAC.cls  ✅ thin
Private Sub cmdGuardar_Click()
    Dim msg As String
    If modDictamenRACHelper.DictamenRAC_Guardar(Me.idSolicitud, _
                                                Me.txtRacDecision & "", _
                                                , msg) Then
        ' success path
    End If
    MsgBox msg, vbInformation        ' the ONLY thing the form does with the result
End Sub
```

Read controls → call helper → render result. No rule, no SQL, no decision in the `.cls`.

---

## 3. The TDD atom (mirrors the UAT scenario)

Sad-path atom: blank decision must NOT persist and must return the validation message. Schema-first, sandbox-safe, cardinalidad before/after, JSON contract — per `access-vba-tdd-fundamentos` §1.3/§2/§3/§4.5.

```vb
' Test_DictamenRAC.bas  (Public Function, returns JSON)
Public Function Test_PCSUB_DictamenRAC_BlankDecision_ReturnsValidationError() As String
    Dim logs() As String, db As DAO.Database, msg As String, ok As Boolean
    Dim countAfter As Long
    Set db = TestHelper.GetTestDb()
    Const FIX_ID As Long = 900042

    EnsureTableClean db, "TbDictamenRAC", "idSolicitud=" & FIX_ID
    ' Act: blank decision
    ok = modDictamenRACHelper.DictamenRAC_Guardar(FIX_ID, "", db, msg)

    ' Assert: returned False, no row written, the user-visible message is the validation one
    countAfter = CountRows(db, "TbDictamenRAC", "idSolicitud=" & FIX_ID & " AND racDecision<>''")
    If ok Or countAfter <> 0 Or msg <> "El campo Decisión es obligatorio" Then
        Test_PCSUB_DictamenRAC_BlankDecision_ReturnsValidationError = _
            BuildFail("expected blank-decision rejection, got ok=" & ok & " rows=" & countAfter, logs)
        Exit Function
    End If
    Test_PCSUB_DictamenRAC_BlankDecision_ReturnsValidationError = BuildOk("rejected", logs)
End Function
```

---

## 4. The UAT card (mirror of the atom, user language only)

No jargon (`BR-x`, atom names, commit hashes) in the card body — that goes in the `ref`, which lives in the downloaded/signed record, not on screen.

```text
UAT-2 — "Dictamen RAC exige Decisión"
DADO: una solicitud PCSUB con Código RAC y Nombre RAC llenos pero Decisión vacía
CUANDO: el usuario pulsa "Guardar" en el subform de Dictamen RAC
ENTONCES: aparece "El campo Decisión es obligatorio"
esperado: el dictamen NO queda guardado
pasos:
  1. Abre una solicitud PCSUB existente
  2. Navega al subform "Dictamen RAC"
  3. Completa "Código RAC" y "Nombre RAC"
  4. Deja "Decisión" en blanco
  5. Pulsa "Guardar"
ref (solo en el registro firmado): <sha> → Test_PCSUB_DictamenRAC_BlankDecision_ReturnsValidationError
```

This `usuario`-axis card is routed to the **user acceptance web** by `feature-acceptance-uat`. If the same change had a non-user-observable item (index, migration, encoding), it would become a `desarrollo`-axis case routed to the **developer validation web** (`docs/uat/uat-dev-<date>.html`) — its own signed instrument, NOT a flat markdown.

---

## Minimum helper decomposition for any feature

When extracting logic from a form, the result is usually MORE than one helper. Create the shared utilities FIRST:

```
modFormInteractionHelper.bas   ' all form/control access (FormularioAbierto, ObtenerValorControl, EstablecerValorControl, Mensaje wrapper of MsgBox)
modTestingCoreHelper.bas        ' all test infra (BuildJsonOk/Fail, BuildOk/Fail, RaiseError, InitLogs, EscapeJsonString, SqlText)
mod<Feature>Helper.bas          ' the feature logic (one per feature) — the example above
Test_<Feature>.bas              ' TDD atoms — imports modTestingCoreHelper, never redefines BuildOk locally
```

Do not create `mod<Feature>Helper.bas` until the two shared utilities exist (or you've confirmed they're not needed). Re-export existing legacy functions (`FormularioAbierto`) if they're private to `Funciones Generales.bas`; do NOT redefine them. If you find yourself writing `Me.Controls("X")` in a second helper, you forgot `modFormInteractionHelper`. If you find `BuildOk` boilerplate in a second `Test_*.bas`, you forgot `modTestingCoreHelper`.
