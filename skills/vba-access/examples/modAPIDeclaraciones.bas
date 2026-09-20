Attribute VB_Name = "modAPIDeclaraciones"
Option Compare Database
Option Explicit

#If VBA7 Then
    #If Win64 Then
        Public Declare PtrSafe Function FindWindow Lib "user32" Alias "FindWindowA" ( _
            ByVal lpClassName As String, _
            ByVal lpWindowName As String) As LongPtr
    #Else
        Public Declare PtrSafe Function FindWindow Lib "user32" Alias "FindWindowA" ( _
            ByVal lpClassName As String, _
            ByVal lpWindowName As String) As Long
    #End If
#Else
    Public Declare Function FindWindow Lib "user32" Alias "FindWindowA" ( _
        ByVal lpClassName As String, _
        ByVal lpWindowName As String) As Long
#End If
