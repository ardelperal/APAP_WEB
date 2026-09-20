Attribute VB_Name = "modTestsEjemplo"
Option Compare Database
Option Explicit

Public Sub RunAllTests()
    On Error GoTo ErroresRunner

    Debug.Print "== INICIO TESTS =="

    Test_Guardar_DebeFallarSiNombreVacio
    Test_ViewModel_DebeAsignarNombre

    Debug.Print "== TESTS OK =="

Salir:
    Exit Sub

ErroresRunner:
    Debug.Print "RunAllTests -> Err " & Err.Number & " - " & Err.Description
    MsgBox "Tests fallidos. Revisá la Ventana Inmediata.", vbExclamation, "MSG-90"
    Resume Salir
End Sub

Private Sub Test_Guardar_DebeFallarSiNombreVacio()
    On Error GoTo ErroresTest

    Dim objServicio As EjemploServicio
    Set objServicio = New EjemploServicio

    On Error Resume Next
    objServicio.Guardar vbNullString
    If Err.Number = 0 Then Err.Raise 1101, "modTestsEjemplo.Test_Guardar_DebeFallarSiNombreVacio", "MSG-91: Se esperaba error de validación"
    On Error GoTo ErroresTest

Salir:
    Set objServicio = Nothing
    Exit Sub

ErroresTest:
    Debug.Print "Test_Guardar_DebeFallarSiNombreVacio -> Err " & Err.Number & " - " & Err.Description
    Resume Salir
End Sub

Private Sub Test_ViewModel_DebeAsignarNombre()
    On Error GoTo ErroresTest

    Dim objVM As EjemploViewModel
    Set objVM = New EjemploViewModel
    objVM.Nombre = "Prueba"

    If objVM.Nombre <> "Prueba" Then
        Err.Raise 1102, "modTestsEjemplo.Test_ViewModel_DebeAsignarNombre", "MSG-92: El ViewModel no conservó el nombre"
    End If

Salir:
    Set objVM = Nothing
    Exit Sub

ErroresTest:
    Debug.Print "Test_ViewModel_DebeAsignarNombre -> Err " & Err.Number & " - " & Err.Description
    Resume Salir
End Sub
