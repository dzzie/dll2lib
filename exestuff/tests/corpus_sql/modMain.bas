Attribute VB_Name = "modMain"
Option Explicit

Private Declare Function GetStdHandle Lib "kernel32" (ByVal nStdHandle As Long) As Long
Private Declare Function WriteFile Lib "kernel32" (ByVal hFile As Long, lpBuffer As Any, ByVal nBytes As Long, lpWritten As Long, ByVal lpOverlapped As Long) As Long

Private Sub outln(ByVal s As String)
    Dim b() As Byte, w As Long
    s = s & vbCrLf
    b = StrConv(s, vbFromUnicode)
    WriteFile GetStdHandle(-11&), b(0), UBound(b) + 1, w, 0&
End Sub

Sub Main()
    On Error GoTo fail
    Dim db As New cSQLite
    Dim ver As String, n As Long, s As String
    ver = db.Version
    db.OpenDB ":memory:"
    db.Execute "CREATE TABLE t(id INTEGER PRIMARY KEY, body TEXT)"
    db.Execute "INSERT INTO t(body) VALUES('hello'),('fused')"
    n = db.Scalar("SELECT COUNT(*) FROM t")
    s = db.Scalar("SELECT body FROM t WHERE id = 2")
    db.CloseDB
    outln "OK version=" & ver & " count=" & n & " row2=" & s
    Exit Sub
fail:
    outln "ERR " & Err.Number & " " & Err.Description
End Sub
