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
    Dim ucl As New CUclCompression
    Dim i As Long, src() As Byte, comp() As Byte, dec() As Byte, s As String
    For i = 1 To 50
        s = s & "The quick brown fox jumps over the lazy dog. "
    Next
    src = StrConv(s, vbFromUnicode)
    ucl.Level = 8
    ucl.Compress src, comp
    ucl.Decompress comp, UBound(src) + 1, dec
    Dim ok As Boolean
    ok = (UBound(dec) = UBound(src))
    outln IIf(ok, "OK", "FAIL") & " in=" & (UBound(src) + 1) & " comp=" & (UBound(comp) + 1) & " dec=" & (UBound(dec) + 1)
End Sub
