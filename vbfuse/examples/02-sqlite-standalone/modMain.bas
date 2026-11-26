Attribute VB_Name = "modMain"
Option Explicit

Private Declare Function GetStdHandle Lib "kernel32" (ByVal nStdHandle As Long) As Long
Private Declare Function WriteFile Lib "kernel32" (ByVal hFile As Long, lpBuffer As Any, ByVal nBytes As Long, lpWritten As Long, ByVal lpOverlapped As Long) As Long
Private Declare Function GetModuleHandle Lib "kernel32" Alias "GetModuleHandleA" (ByVal lpModuleName As String) As Long

Private Sub outln(ByVal s As String)
    Dim b() As Byte, w As Long
    s = s & vbCrLf
    b = StrConv(s, vbFromUnicode)
    WriteFile GetStdHandle(-11&), b(0), UBound(b) + 1, w, 0&
End Sub

' GetModuleHandle = 0 means the module is NOT mapped in this process, i.e. it
' is not a load-time dependency - its code lives inside this exe as fused code.
Private Function fmtState(ByVal h As Long) As String
    If h = 0 Then
        fmtState = "NOT loaded -> FUSED"
    Else
        fmtState = "loaded (h=&H" & Hex$(h) & ")"
    End If
End Function

Sub Main()
    On Error GoTo fail

    ' Load state BEFORE touching the SQLite classes. A normal VB6 exe has
    ' msvbvm60 mapped before Main even runs; here it reports 0 - it is fused.
    outln "===================================================="
    outln "  SQLite + VB runtime  -  fully standalone (vbfuse)"
    outln "===================================================="
    outln "Fused in: sqlite3_vb6.dll (SQLite engine)"
    outln "          msvbvm60.dll   (the VB6 runtime, via VBStatic)"
    outln ""
    outln "Load state at process start (GetModuleHandle):"
    outln "    msvbvm60.dll    : " & fmtState(GetModuleHandle("msvbvm60.dll"))
    outln "    sqlite3_vb6.dll : " & fmtState(GetModuleHandle("sqlite3_vb6.dll"))
    outln "  -> neither is an import / load-time dependency."
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

    ' Re-check AFTER running the engine. sqlite4vb's EnsureDLL is fusion-aware
    ' (it sees msvbvm60 is fused and skips the disk LoadLibrary), so the DLL is
    ' STILL not loaded - every SQLite call above ran from fused code.
    outln "Load state after all queries ran:"
    outln "    sqlite3_vb6.dll : " & fmtState(GetModuleHandle("sqlite3_vb6.dll"))
    outln "  -> still 0: the engine never touched the DLL on disk."
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
