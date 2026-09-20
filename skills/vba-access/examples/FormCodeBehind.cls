VERSION 1.0 CLASS
BEGIN
  MultiUse = -1
END
Attribute VB_Name = "Form_frmEjemplo"
Option Compare Database
Option Explicit

Private m_ObjViewModel As EjemploViewModel

Private Sub Form_Load()
    On Error GoTo Errores

    Set m_ObjViewModel = New EjemploViewModel

    With Me
        .txtNombre.Value = vbNullString
        .txtNombre.Enabled = True
        .btnGuardar.Caption = "Guardar"
    End With

Salir:
    Exit Sub

Errores:
    Debug.Print "Form_frmEjemplo.Form_Load -> Err " & Err.Number & " - " & Err.Description
    MsgBox "MSG-10: Error al cargar el formulario", vbExclamation, "MSG-10"
    Resume Salir
End Sub

Private Sub btnGuardar_Click()
    On Error GoTo Errores

    m_ObjViewModel.Nombre = Nz(Me.txtNombre.Value, vbNullString)
    m_ObjViewModel.Guardar

Salir:
    Exit Sub

Errores:
    Debug.Print "Form_frmEjemplo.btnGuardar_Click -> Err " & Err.Number & " - " & Err.Description
    MsgBox Err.Description, vbExclamation, "MSG-11"
    Resume Salir
End Sub
