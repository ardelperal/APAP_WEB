VERSION 1.0 CLASS
BEGIN
  MultiUse = -1
END
Attribute VB_Name = "EjemploServicio"
Option Compare Database
Option Explicit

Public Sub Guardar(ByVal p_strNombre As String)
    On Error GoTo Errores

    If Len(Trim$(p_strNombre)) = 0 Then
        Err.Raise 1001, "EjemploServicio.Guardar", "MSG-01: El nombre es obligatorio"
    End If

    Call EjemploRepositorio.Guardar(p_strNombre)

Salir:
    Exit Sub

Errores:
    Debug.Print "EjemploServicio.Guardar -> Err " & Err.Number & " - " & Err.Description
    Err.Raise Err.Number, "EjemploServicio.Guardar", Err.Description
    Resume Salir
End Sub
