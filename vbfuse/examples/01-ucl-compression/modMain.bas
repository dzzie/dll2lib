Attribute VB_Name = "modMain"
Option Explicit

Sub Main()
    Dim outPath As String
    outPath = Trim$(Command$())
    If Len(outPath) = 0 Then outPath = App.Path & "\ucl_result.txt"

    Dim ucl As New CUclCompression
    Dim i As Long, origSize As Long
    Dim src() As Byte, comp() As Byte, dec() As Byte
    Dim s As String

    For i = 1 To 50
        s = s & "The quick brown fox jumps over the lazy dog. "
    Next
    src = StrConv(s, vbFromUnicode)
    origSize = UBound(src) + 1

    ucl.Level = 8

    If Not ucl.Compress(src, comp) Then
        WriteResult outPath, "FAIL compress: " & ucl.LastError
        Exit Sub
    End If

    If Not ucl.Decompress(comp, origSize, dec) Then
        WriteResult outPath, "FAIL decompress: " & ucl.LastError
        Exit Sub
    End If

    Dim ok As Boolean
    ok = (UBound(dec) = UBound(src))
    If ok Then
        For i = 0 To UBound(src)
            If dec(i) <> src(i) Then
                ok = False
                Exit For
            End If
        Next
    End If

    WriteResult outPath, IIf(ok, "OK", "MISMATCH") & _
        " src=" & origSize & " comp=" & (UBound(comp) + 1) & " dec=" & (UBound(dec) + 1)
End Sub

Private Sub WriteResult(ByVal path As String, ByVal msg As String)
    Dim f As Integer
    f = FreeFile
    Open path For Output As #f
    Print #f, msg
    Close #f
End Sub
