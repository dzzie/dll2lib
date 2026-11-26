Attribute VB_Name = "modMain"
Option Explicit

Private gOut As String

Private Sub L(ByVal msg As String)
    Dim f As Integer
    f = FreeFile
    Open gOut For Append As #f
    Print #f, msg
    Close #f
End Sub

Sub Main()
    gOut = Trim$(Command$())
    If Len(gOut) = 0 Then gOut = App.Path & "\sqlite_result.txt"
    On Error Resume Next
    If Dir(gOut) <> "" Then Kill gOut
    On Error GoTo 0

    On Error GoTo fail
    Dim db As New cSQLite
    L "version=" & db.Version
    db.OpenDB ":memory:"
    L "opened :memory:"
    db.Execute "CREATE TABLE t(id INTEGER PRIMARY KEY, body TEXT)"
    db.Execute "INSERT INTO t(body) VALUES('hello'), ('fused')"
    Dim n As Long, s As String
    n = db.Scalar("SELECT COUNT(*) FROM t")
    s = db.Scalar("SELECT body FROM t WHERE id = 2")
    db.CloseDB
    L "count=" & n & " row2=" & s
    If n = 2 And s = "fused" Then
        L "OK cSQLite classes fused"
    Else
        L "MISMATCH n=" & n & " s=" & s
    End If
    Exit Sub
fail:
    L "FAIL " & Err.Number & ": " & Err.Description
End Sub
