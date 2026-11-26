# Example 01 — fuse a C DLL (UCL compression)

A VB6 app that calls a C compression DLL (`ucl_dll.dll`) via `Declare`, fused
into a standalone exe that needs no `ucl_dll.dll` at runtime.

### Files
- `UclTest.vbp` / `modMain.bas` / `CUclCompression.cls` — the VB6 app
  (`Sub Main` compresses a buffer, decompresses it, checks the roundtrip, writes
  the result to the path given on the command line). **Unmodified** — the
  `Declare ... Lib "ucl_dll.dll"` lines are left exactly as written.
- `ucl_dll.dll` — the C DLL to fuse.
- `ucltest_fused.exe` — the prebuilt fused result (checked in for analysis).

### Build
```
python build.py            (or:  build.cmd)
python build.py --run      build, run, and write result.txt
```
`build.py` just invokes `vbfuse UclTest.vbp --fuse ucl_dll.dll`.

### Expected
`ucltest_fused.exe <out.txt>` writes:
```
OK src=2250 comp=64 dec=2250
```
Delete `ucl_dll.dll` first if you like — the fused exe doesn't need it.

### Credits
- UCL compression library © Markus F.X.J. Oberhumer — https://www.oberhumer.com/opensource/ucl/ (GPL).
- The VB6 UCL wrapper sample is a long-standing community sample; `ucl_dll.dll`
  here is that GPL wrapper. Fusion mechanics build on **VB6‑LinkAlchemy** by
  **UltraAlex0** (see the top-level README and `../../VB6_FUSION_NOTES.md`).
