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
    outln "===================================================="
    outln "  SQLite + VB runtime  -  fully standalone (vbfuse)"
    outln "===================================================="
    outln "Fused in: sqlite3_vb6.dll (SQLite engine)"
    outln "          msvbvm60.dll   (the VB6 runtime, via VBStatic)"
    outln "This exe imports ONLY base Windows DLLs - run"
    outln "  dumpbin /imports on it: no msvbvm60, no sqlite3_vb6."
    outln ""

    Dim db As New cSQLite
    outln "  SQLite version         : " & db.Version
    db.OpenDB ":memory:"
    outln "  opened                 : :memory:"
    db.Execute "CREATE TABLE t(id INTEGER PRIMARY KEY, body TEXT)"
    db.Execute "INSERT INTO t(body) VALUES('hello'), ('fused')"
    outln "  created + inserted     : table t, 2 rows"

    Dim n As Long, s As String
    n = db.Scalar("SELECT COUNT(*) FROM t")
    s = db.Scalar("SELECT body FROM t WHERE id = 2")
    db.CloseDB
    outln "  SELECT COUNT(*)        : " & n
    outln "  SELECT body WHERE id=2 : '" & s & "'"
    outln ""
    If n = 2 And s = "fused" Then
        outln "[SUCCESS] A full SQLite engine + the VB6 runtime, running"
        outln "          from one self-contained exe. Everything is awesome."
    Else
        outln "[FAIL] n=" & n & " s=" & s
    End If
    Exit Sub
fail:
    outln "[ERROR] " & Err.Number & ": " & Err.Description
End Sub
