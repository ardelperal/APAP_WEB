Attribute VB_Name = "modErrorPattern"
Option Compare Database
Option Explicit

Public Sub EjemploOperacion()
    On Error GoTo Errores

    ' Trabajo principal

Salir:
    Exit Sub

Errores:
    Debug.Print "EjemploOperacion -> Err " & Err.Number & " - " & Err.Description
    Resume Salir
End Sub

Public Sub EjemploOperacionPropagando()
    On Error GoTo Errores

    ' Trabajo principal

Salir:
    Exit Sub

Errores:
    Debug.Print "EjemploOperacionPropagando -> Err " & Err.Number & " - " & Err.Description
    Err.Raise 1002, "EjemploOperacionPropagando", "MSG-02: Error propagado con contexto"
End Sub
