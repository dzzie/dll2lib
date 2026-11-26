# Example 01 — fuse a C DLL (UCL compression)

A VB6 app that calls a C compression DLL (`ucl_dll.dll`) via `Declare`, fused
into a standalone exe that needs no `ucl_dll.dll` at runtime.

### Files
- `UclTest.vbp` / `modMain.bas` / `CUclCompression.cls` — the VB6 app.
  `Sub Main` compresses a buffer, decompresses it, checks the roundtrip, and
  prints a report to the console (built with `--console`). The
  `Declare ... Lib "ucl_dll.dll"` lines in `CUclCompression.cls` are left
  **exactly as written** — fusion needs no source edit.
- `ucl_dll.dll` — the C DLL to fuse.
- `ucltest_fused.exe` — the prebuilt fused result (checked in for analysis).

### Build
```
python build.py            (or:  build.cmd)
python build.py --run      build, then run (prints to the console)
```
`build.py` invokes `vbfuse UclTest.vbp --fuse ucl_dll.dll --console`.

### Expected output
```
==============================================
  UCL compression  -  fused standalone (vbfuse)
==============================================
ucl_dll.dll (C compression DLL) is FUSED into this exe.
No ucl_dll.dll is needed at runtime.

  input        : 2250 bytes
  compressed   : 64 bytes  (35.2x smaller)
  decompressed : 2250 bytes
  roundtrip    : OK - matches the original

[SUCCESS] Real UCL compression ran entirely from fused code.
          Everything is awesome.
```
Delete `ucl_dll.dll` first if you like — the fused exe doesn't need it.

### Credits
- UCL compression library © Markus F.X.J. Oberhumer — https://www.oberhumer.com/opensource/ucl/ (GPL).
- The VB6 UCL wrapper sample is a long-standing community sample; `ucl_dll.dll`
  here is that GPL wrapper. Fusion mechanics build on **VB6‑LinkAlchemy** by
  **UltraAlex0** (see the top-level README and `../../VB6_FUSION_NOTES.md`).
