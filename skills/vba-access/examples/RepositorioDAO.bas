Attribute VB_Name = "EjemploRepositorio"
Option Compare Database
Option Explicit

Public Function GetById(ByVal p_lngId As Long) As DAO.Recordset
    On Error GoTo Errores

    Dim db As DAO.Database
    Dim qdf As DAO.QueryDef
    Dim rs As DAO.Recordset

    Set db = CurrentDb
    Set qdf = db.CreateQueryDef(vbNullString, _
        "PARAMETERS p_ID LONG; " & _
        "SELECT * FROM TbEjemplo WHERE ID = [p_ID]")
    qdf.Parameters("p_ID").Value = p_lngId
    Set rs = qdf.OpenRecordset(dbOpenDynaset)

    Set GetById = rs

Salir:
    Set qdf = Nothing
    Set db = Nothing
    Exit Function

Errores:
    Debug.Print "EjemploRepositorio.GetById -> Err " & Err.Number & " - " & Err.Description
    Set GetById = Nothing
    Resume Salir
End Function

Public Sub GuardarTextoLargo(ByVal p_lngId As Long, ByVal p_strContenido As String)
    On Error GoTo Errores

    Dim db As DAO.Database
    Dim qdf As DAO.QueryDef
    Dim rs As DAO.Recordset

    Set db = CurrentDb
    Set qdf = db.CreateQueryDef(vbNullString, _
        "PARAMETERS p_ID LONG; " & _
        "SELECT * FROM TbEjemplo WHERE ID = [p_ID]")
    qdf.Parameters("p_ID").Value = p_lngId
    Set rs = qdf.OpenRecordset(dbOpenDynaset)

    If rs.EOF Then Err.Raise 1001, "EjemploRepositorio.GuardarTextoLargo", "MSG-01: Registro no encontrado"

    rs.Edit
    rs!ContenidoLargo = p_strContenido
    rs.Update

Salir:
    If Not rs Is Nothing Then rs.Close
    Set rs = Nothing
    Set qdf = Nothing
    Set db = Nothing
    Exit Sub

Errores:
    Debug.Print "EjemploRepositorio.GuardarTextoLargo -> Err " & Err.Number & " - " & Err.Description
    Resume Salir
End Sub
