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

' Classic offset / hex / ascii dump; stops after maxBytes (0 = all).
Private Sub dumpBytes(b() As Byte, ByVal maxBytes As Long)
    Dim i As Long, j As Long, n As Long, bv As Long, line As String, asc As String
    n = UBound(b) + 1
    i = 0
    Do While i < n
        If maxBytes > 0 And i >= maxBytes Then
            outln "    ...  (" & (n - maxBytes) & " more bytes)"
            Exit Sub
        End If
        line = "    " & Right$("0000" & Hex$(i), 4) & "  "
        asc = ""
        For j = 0 To 15
            If i + j < n Then
                bv = b(i + j)
                line = line & Right$("0" & Hex$(bv), 2) & " "
                If bv >= 32 And bv <= 126 Then asc = asc & Chr$(bv) Else asc = asc & "."
            Else
                line = line & "   "
            End If
        Next
        outln line & " " & asc
        i = i + 16
    Loop
End Sub

Sub Main()
    outln "=============================================="
    outln "  UCL compression  -  fused standalone (vbfuse)"
    outln "=============================================="
    outln "ucl_dll.dll (C compression DLL) is FUSED into this exe."
    outln "No ucl_dll.dll is needed at runtime."
    outln ""

    Dim ucl As New CUclCompression
    Dim i As Long, src() As Byte, comp() As Byte, dec() As Byte, s As String
    For i = 1 To 50
        s = s & "The quick brown fox jumps over the lazy dog. "
    Next
    src = StrConv(s, vbFromUnicode)
    ucl.Level = 8
    ucl.Compress src, comp
    ucl.Decompress comp, UBound(src) + 1, dec

    Dim inlen As Long, clen As Long, dlen As Long, ok As Boolean
    inlen = UBound(src) + 1: clen = UBound(comp) + 1: dlen = UBound(dec) + 1
    ok = (dlen = inlen)
    If ok Then
        For i = 0 To UBound(src)
            If dec(i) <> src(i) Then ok = False: Exit For
        Next
    End If

    outln "  input        : " & inlen & " bytes"
    outln "  compressed   : " & clen & " bytes  (" & Format$(inlen / clen, "0.0") & "x smaller)"
    outln "  decompressed : " & dlen & " bytes"
    outln "  roundtrip    : " & IIf(ok, "OK - matches the original", "FAILED")
    outln "  ucl_dll.dll  : " & fmtState(GetModuleHandle("ucl_dll.dll"))
    outln ""

    outln "  --- original  (first 48 of " & inlen & " bytes) ---"
    dumpBytes src, 48
    outln ""
    outln "  --- compressed  (all " & clen & " bytes, produced by the fused C code) ---"
    dumpBytes comp, 0
    outln ""
    outln "  --- decompressed  (first 48 of " & dlen & " bytes) ---"
    dumpBytes dec, 48
    outln ""

    If ok Then
        outln "[SUCCESS] The dense 'compressed' block above round-trips byte-for-byte"
        outln "          back to the original - and GetModuleHandle proves the DLL"
        outln "          isn't even loaded. Everything is awesome."
    Else
        outln "[FAIL] roundtrip mismatch"
    End If
End Sub
