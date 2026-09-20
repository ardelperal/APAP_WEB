VERSION 1.0 CLASS
BEGIN
  MultiUse = -1
END
Attribute VB_Name = "EjemploViewModel"
Option Compare Database
Option Explicit

Private m_lngId As Long
Private m_strNombre As String

Public Property Get Id() As Long
    Id = m_lngId
End Property

Public Property Let Id(ByVal p_lngId As Long)
    m_lngId = p_lngId
End Property

Public Property Get Nombre() As String
    Nombre = m_strNombre
End Property

Public Property Let Nombre(ByVal p_strNombre As String)
    m_strNombre = p_strNombre
End Property

Public Sub Guardar()
    On Error GoTo Errores

    If Len(Trim$(m_strNombre)) = 0 Then
        Err.Raise 1001, "EjemploViewModel.Guardar", "MSG-01: El nombre es obligatorio"
    End If

    Dim objServicio As EjemploServicio
    Set objServicio = New EjemploServicio
    objServicio.Guardar m_strNombre

Salir:
    Set objServicio = Nothing
    Exit Sub

Errores:
    Debug.Print "EjemploViewModel.Guardar -> Err " & Err.Number & " - " & Err.Description
    Resume Salir
End Sub
