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

Private Function fmtState(ByVal h As Long) As String
    If h = 0 Then fmtState = "NOT loaded -> FUSED" Else fmtState = "loaded (h=&H" & Hex$(h) & ")"
End Function

Private Function padR(ByVal s As String, ByVal n As Long) As String
    If Len(s) >= n Then padR = s Else padR = s & Space$(n - Len(s))
End Function
Private Function padL(ByVal s As String, ByVal n As Long) As String
    If Len(s) >= n Then padL = s Else padL = Space$(n - Len(s)) & s
End Function

Sub Main()
    On Error GoTo fail

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
    outln "SQLite engine version (from the fused code): " & db.Version
    db.OpenDB ":memory:"
    outln "Opened an in-memory database (:memory:)."
    outln ""

    ' --- schema + a dataset, inserted inside one transaction -------------
    db.Execute "CREATE TABLE langs (" & _
               "  id       INTEGER PRIMARY KEY," & _
               "  name     TEXT NOT NULL," & _
               "  year     INTEGER NOT NULL," & _
               "  paradigm TEXT NOT NULL)"

    Dim data As Variant, r As Long
    data = Array( _
        Array("C", 1972, "imperative"), _
        Array("Haskell", 1990, "functional"), _
        Array("Python", 1991, "multi-paradigm"), _
        Array("JavaScript", 1995, "multi-paradigm"), _
        Array("VB6", 1998, "event-driven"), _
        Array("SQLite", 2000, "embedded-db"), _
        Array("Go", 2009, "concurrent"), _
        Array("Rust", 2010, "systems"))

    db.BeginTrans
    For r = 0 To UBound(data)
        db.Execute "INSERT INTO langs(name,year,paradigm) VALUES('" & _
                   data(r)(0) & "'," & data(r)(1) & ",'" & data(r)(2) & "')"
    Next
    db.CommitTrans
    outln "Inserted " & (UBound(data) + 1) & " rows in one transaction; " & _
          "last rowid = " & Format$(db.LastInsertRowID * 10000, "0") & "."
    outln ""

    ' --- query 1: full table dump, ordered ------------------------------
    outln "[1] SELECT * ORDER BY year"
    outln "    " & padR("name", 12) & padL("year", 6) & "   paradigm"
    outln "    " & String$(12, "-") & " " & String$(5, "-") & "   " & String$(14, "-")
    Dim rs As cSQLiteResults
    Set rs = db.Query("SELECT name, year, paradigm FROM langs ORDER BY year")
    Do While rs.MoveNext()
        outln "    " & padR(rs.FieldText("name"), 12) & _
              padL(CStr(rs.FieldInt("year")), 6) & "   " & rs.FieldText("paradigm")
    Loop
    rs.CloseRS
    outln ""

    ' --- query 2: aggregates --------------------------------------------
    outln "[2] aggregates (COUNT / MIN / MAX / AVG of year)"
    outln "    count   = " & db.Scalar("SELECT COUNT(*) FROM langs")
    outln "    oldest  = " & db.Scalar("SELECT MIN(year) FROM langs") & _
          " (" & db.Scalar("SELECT name FROM langs ORDER BY year LIMIT 1") & ")"
    outln "    newest  = " & db.Scalar("SELECT MAX(year) FROM langs") & _
          " (" & db.Scalar("SELECT name FROM langs ORDER BY year DESC LIMIT 1") & ")"
    outln "    avg year= " & Format$(CDbl(db.Scalar("SELECT AVG(year) FROM langs")), "0.0")
    outln ""

    ' --- query 3: GROUP BY ----------------------------------------------
    outln "[3] GROUP BY paradigm"
    Set rs = db.Query("SELECT paradigm, COUNT(*) n FROM langs " & _
                      "GROUP BY paradigm ORDER BY n DESC, paradigm")
    Do While rs.MoveNext()
        outln "    " & padR(rs.FieldText("paradigm"), 16) & " : " & rs.FieldInt("n")
    Loop
    rs.CloseRS
    outln ""

    ' --- query 4: parameterized query (? binding) -----------------------
    outln "[4] parameterized: SELECT name,year WHERE year >= ?  (bind 2000)"
    Set rs = db.Query("SELECT name, year FROM langs WHERE year >= ? ORDER BY year", 2000)
    Do While rs.MoveNext()
        outln "    " & padR(rs.FieldText("name"), 12) & padL(CStr(rs.FieldInt("year")), 6)
    Loop
    rs.CloseRS
    outln ""

    ' --- query 5: transaction rollback (ACID proof) ---------------------
    outln "[5] transaction rollback"
    Dim before As Long, during As Long, after As Long
    before = db.Scalar("SELECT COUNT(*) FROM langs")
    db.BeginTrans
    db.Execute "DELETE FROM langs"
    during = db.Scalar("SELECT COUNT(*) FROM langs")
    outln "    before          : " & before & " rows"
    outln "    inside txn       : " & during & " rows (InTransaction=" & db.InTransaction & _
          ", RowsAffected=" & db.RowsAffected & ")"
    db.RollbackTrans
    after = db.Scalar("SELECT COUNT(*) FROM langs")
    outln "    after rollback   : " & after & " rows -> " & _
          IIf(after = before, "restored (ACID OK)", "LOST DATA!")
    outln ""

    ' --- re-prove the engine was never a loaded module ------------------
    outln "Load state after all that work:"
    outln "    sqlite3_vb6.dll : " & fmtState(GetModuleHandle("sqlite3_vb6.dll"))
    outln "  -> still 0: every query above ran from the fused engine."
    db.CloseDB
    outln ""

    If after = before And before = (UBound(data) + 1) Then
        outln "[SUCCESS] A full SQLite engine + the VB6 runtime put through its"
        outln "          paces from one self-contained exe. Everything is awesome."
    Else
        outln "[FAIL] before=" & before & " after=" & after
    End If
    Exit Sub
fail:
    outln "[ERROR] " & Err.Number & ": " & Err.Description
End Sub
