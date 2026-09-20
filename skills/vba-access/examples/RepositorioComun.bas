Attribute VB_Name = "RepositorioComun"
Option Compare Database
Option Explicit

Public Function AbrirRecordsetParametrizado(ByVal p_strSql As String, ByVal p_Params As Object, Optional ByVal p_Tipo As DAO.RecordsetTypeEnum = dbOpenDynaset) As DAO.Recordset
    On Error GoTo Errores

    Dim db As DAO.Database
    Dim qdf As DAO.QueryDef
    Dim rs As DAO.Recordset
    Dim vKey As Variant

    Set db = CurrentDb
    Set qdf = db.CreateQueryDef(vbNullString, p_strSql)

    If Not p_Params Is Nothing Then
        For Each vKey In p_Params.Keys
            qdf.Parameters(CStr(vKey)).Value = p_Params(vKey)
        Next vKey
    End If

    Set rs = qdf.OpenRecordset(p_Tipo)
    Set AbrirRecordsetParametrizado = rs

Salir:
    Set qdf = Nothing
    Set db = Nothing
    Exit Function

Errores:
    Debug.Print "RepositorioComun.AbrirRecordsetParametrizado -> Err " & Err.Number & " - " & Err.Description
    Set AbrirRecordsetParametrizado = Nothing
    Resume Salir
End Function
